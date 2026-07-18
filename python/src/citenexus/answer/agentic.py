"""Deep-ask: a bounded, library-scripted evidence-gathering loop (§10b).

`ask(strategy="deep")` runs this instead of the single-passage strict flow. The
LIBRARY owns the control flow — retrieve → grade → refine → repeat — pooling
VERBATIM Evidence Units across hops (deduped by ``eu_id``); the model only answers
small structured decisions (`answer/decision.py`). It is NOT a free ReAct agent:
7B drivers collapse on open tool loops, so the protocol is scripted and bounded.

Two invariants carry the guarantee:

- **Budgets bound cost; only the gate bounds truth.** Every exit (sufficient,
  no-new-evidence, budget, timeout) generates from the deduped pool and passes the
  **per-claim single-EU gate** — each claim ⊆ *some single* EU, never the pooled
  union (a claim stitched from EUs that never co-occurred is ungrounded and is
  dropped). This decomposition is net-new; `is_supported` is reused only as the
  per-(claim, EU) predicate.
- **A whole-loop wall clock.** ``timeout_s`` bounds the *entire* run — each tool
  call and the final ``generate()`` too, not just the between-hop check. A hung
  model call cannot exceed it, and an interrupted generation is DISCARDED (its
  partial text has no source span and never enters the pool or the answer).
"""

from __future__ import annotations

import functools
import re
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

from citenexus.answer.decision import DecisionModel
from citenexus.answer.flow import Generator
from citenexus.answer.result import (
    Claim,
    Decision,
    EvidenceSignals,
    LoopSignals,
    LoopStopReason,
    ProvenanceEntry,
    Result,
    SourceRef,
)
from citenexus.answer.verify import is_supported
from citenexus.domain.trust import TrustMode
from citenexus.lang.fallback import resolve_answer_language

ToolSpec = dict[str, Any]

_SENTENCE_SPLIT = re.compile(r"[.!?\n]+")


class LoopBudget(BaseModel):
    """Hard cost bounds for one deep-ask run.

    ``stop_when`` defaults to ``no_new_evidence`` — deterministic given a
    deterministic driver, so the loop is provable offline with fakes. ``timeout_s``
    is a WHOLE-LOOP wall-clock bound (new to the codebase): it caps every tool call
    and the final ``generate()``, not just the between-hop check.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_hops: int = 4
    max_tool_calls: int = 10
    max_evidence_units: int = 40
    timeout_s: float = 60.0
    stop_when: str = "no_new_evidence"
    search_k: int = 5


@dataclass(frozen=True)
class _PooledEvidence:
    """One deduped, verbatim Evidence Unit gathered by the loop."""

    eu_id: str
    text: str
    document_id: str | None
    page: int | None
    language: str | None
    checksum: str | None
    signal: str
    score: float


class _LoopTimeout(Exception):
    """Raised when the whole-loop wall clock elapses mid tool-call/generation."""


def _run_bounded(fn: Callable[[], Any], timeout_s: float) -> Any:
    """Run ``fn`` on a daemon thread, abandoning it if it outlives ``timeout_s``.

    A hung tool call or generation cannot exceed the budget: on timeout we raise
    and the caller discards whatever the thread might later produce. The thread is
    a daemon, so it never blocks interpreter exit.
    """
    if timeout_s <= 0:
        raise _LoopTimeout
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # surfaced to the caller after join
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout_s)
    if thread.is_alive():
        raise _LoopTimeout
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _find_search(tools: Sequence[ToolSpec]) -> Callable[..., list[dict[str, Any]]]:
    for spec in tools:
        if spec.get("name") == "search_evidence":
            handler = spec["handler"]
            return handler  # type: ignore[no-any-return]
    raise ValueError("deep-ask requires the 'search_evidence' tool from build_tools()")


def _to_pooled(row: dict[str, Any]) -> _PooledEvidence | None:
    eu_id = row.get("eu_id")
    text = row.get("text")
    if not eu_id or not text:
        return None
    return _PooledEvidence(
        eu_id=str(eu_id),
        text=str(text),
        document_id=row.get("document_id"),
        page=row.get("page"),
        language=row.get("language"),
        checksum=row.get("checksum"),
        signal=str(row.get("signal", "vector")),
        score=float(row.get("score", 0.0)),
    )


def _split_claims(text: str) -> list[str]:
    """Decompose a generated answer into individual claims (sentence-level)."""
    return [claim.strip() for claim in _SENTENCE_SPLIT.split(text) if claim.strip()]


class AgenticAnswerFlow:
    """The scripted deep-ask loop, ending in the per-claim single-EU gate."""

    def __init__(
        self,
        *,
        generator: Generator,
        decider: DecisionModel,
        tools: Sequence[ToolSpec],
        budget: LoopBudget | None = None,
        default_answer_language: str = "en",
    ) -> None:
        self._generator = generator
        self._decider = decider
        self._search = _find_search(tools)
        self._budget = budget or LoopBudget()
        self._default_answer_language = default_answer_language

    def ask(
        self,
        question: str,
        *,
        mode: TrustMode = TrustMode.strict,
        answer_language: str | None = None,
    ) -> Result:
        budget = self._budget
        deadline = time.monotonic() + budget.timeout_s
        pool: dict[str, _PooledEvidence] = {}
        query = question
        tool_calls = 0
        hops = 0
        stop_reason = LoopStopReason.budget

        for _hop in range(budget.max_hops):
            if time.monotonic() >= deadline:
                stop_reason = LoopStopReason.timeout
                break
            if tool_calls >= budget.max_tool_calls:
                stop_reason = LoopStopReason.budget
                break
            hops += 1
            try:
                rows = _run_bounded(
                    functools.partial(self._search, query, budget.search_k),
                    deadline - time.monotonic(),
                )
            except _LoopTimeout:
                stop_reason = LoopStopReason.timeout
                break
            tool_calls += 1

            added = 0
            capped = False
            for row in rows:
                eu = _to_pooled(row)
                if eu is None or eu.eu_id in pool:
                    continue
                pool[eu.eu_id] = eu
                added += 1
                if len(pool) >= budget.max_evidence_units:
                    capped = True
                    break
            if capped:
                stop_reason = LoopStopReason.budget
                break
            if added == 0:
                # A hop that adds no unseen EU ends the loop (the deterministic
                # default stop). Draft/model text is never poolable — only EUs.
                stop_reason = LoopStopReason.no_new_evidence
                break

            try:
                decision = _run_bounded(
                    lambda: self._decider.decide(question, [e.text for e in pool.values()]),
                    deadline - time.monotonic(),
                )
            except _LoopTimeout:
                stop_reason = LoopStopReason.timeout
                break
            if decision.sufficient:
                stop_reason = LoopStopReason.sufficient
                break
            if decision.next_query:
                query = decision.next_query
            else:
                stop_reason = LoopStopReason.no_new_evidence
                break

        return self._finish(
            question,
            pool,
            mode=mode,
            answer_language=answer_language,
            deadline=deadline,
            stop_reason=stop_reason,
            hops=hops,
            tool_calls=tool_calls,
        )

    def _finish(
        self,
        question: str,
        pool: dict[str, _PooledEvidence],
        *,
        mode: TrustMode,
        answer_language: str | None,
        deadline: float,
        stop_reason: LoopStopReason,
        hops: int,
        tool_calls: int,
    ) -> Result:
        units = list(pool.values())
        languages = tuple(dict.fromkeys(e.language for e in units if e.language is not None))
        language = resolve_answer_language(
            detection=None,
            answer_language=answer_language,
            languages_in_evidence=languages,
            default_answer_language=self._default_answer_language,
        )
        loop = LoopSignals(
            stop_reason=stop_reason,
            hops=hops,
            tool_calls=tool_calls,
            evidence_units=len(units),
        )
        if not units:
            return self._refuse(
                mode=mode,
                language=language,
                reason="no sufficiently relevant evidence found",
                loop=loop,
            )

        passage = "\n".join(e.text for e in units)
        try:
            answer_text = _run_bounded(
                lambda: self._generator.answer(question, passage, language),
                deadline - time.monotonic(),
            )
        except _LoopTimeout:
            # Discard any partial generation — it has no source span and must
            # never be gated-and-emitted. Timeout never lowers the gate's bar.
            return self._refuse(
                mode=mode,
                language=language,
                reason="generation exceeded the whole-loop timeout",
                loop=loop.model_copy(update={"stop_reason": LoopStopReason.timeout}),
            )

        supported, removed = self._gate(answer_text, units)
        if not supported:
            return self._refuse(
                mode=mode,
                language=language,
                reason="no claim passed the per-claim single-EU faithfulness gate",
                loop=loop,
            )

        decision = Decision.answered if removed == 0 else Decision.partial
        used = tuple(dict.fromkeys(eu.eu_id for _claim, eu in supported))
        by_id = {eu.eu_id: eu for _claim, eu in supported}
        answer = " ".join(claim for claim, _eu in supported)
        claims = tuple(
            Claim(claim=claim, supported=True, sources=(eu.eu_id,)) for claim, eu in supported
        )
        sources = tuple(
            SourceRef(
                document=by_id[eu_id].document_id or eu_id,
                passage=by_id[eu_id].text,
                passage_language=by_id[eu_id].language or "und",
                page=by_id[eu_id].page,
            )
            for eu_id in used
        )
        provenance = tuple(
            ProvenanceEntry(
                claim=claim,
                evidence_unit=eu.eu_id,
                document_id=eu.document_id or eu.eu_id,
                s3_object="",
                checksum=eu.checksum or "",
                page=eu.page,
                produced_by={"retrieval_signal": eu.signal},
            )
            for claim, eu in supported
        )
        signals = EvidenceSignals(
            decision=decision,
            supporting_sources=len(used),
            distinct_documents=len({e.document_id or e.eu_id for e in units}),
            retrieval_score_spread=_score_spread(units),
            all_claims_verified=removed == 0,
            unsupported_claims_removed=removed,
            languages_in_evidence=languages,
            loop=loop,
        )
        return Result(
            answer=answer,
            answer_language=language,
            mode=mode,
            evidence=signals,
            claims=claims,
            sources=sources,
            provenance=provenance,
        )

    def _gate(
        self, answer_text: str, units: Sequence[_PooledEvidence]
    ) -> tuple[list[tuple[str, _PooledEvidence]], int]:
        """Per-claim single-EU gate: each claim is a subset of SOME single EU.

        Never the pooled union: that reading is strictly weaker — it passes a
        claim stitched from EUs that never co-occurred. Here every claim must fit
        inside one EU; unsupported claims are dropped, never emitted.
        """
        supported: list[tuple[str, _PooledEvidence]] = []
        removed = 0
        for claim in _split_claims(answer_text):
            source = next((eu for eu in units if is_supported(claim, eu.text)), None)
            if source is not None:
                supported.append((claim, source))
            else:
                removed += 1
        return supported, removed

    def _refuse(
        self,
        *,
        mode: TrustMode,
        language: str,
        reason: str,
        loop: LoopSignals,
    ) -> Result:
        return Result(
            answer="I can't answer that from the available evidence.",
            answer_language=language,
            mode=mode,
            evidence=EvidenceSignals(decision=Decision.refused, loop=loop),
            missing_evidence=(reason,),
        )


def _score_spread(units: Sequence[_PooledEvidence]) -> float:
    if not units:
        return 0.0
    scores = [e.score for e in units]
    return max(scores) - min(scores)
