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
  dropped). This decomposition is net-new; `is_supported_v2` is reused only as the
  per-(claim, EU) predicate.
- **A whole-loop wall clock.** ``timeout_s`` bounds the *entire* run — each tool
  call and the final ``generate()`` too, not just the between-hop check. A hung
  model call cannot exceed it, and an interrupted generation is DISCARDED (its
  partial text has no source span and never enters the pool or the answer).

AUTHORITY (ADR-0004) enters at **pool admission**, hop by hop — not once at the
end. The gate above is single-EU, so *any* pooled unit is on its own sufficient
to carry a claim; a below-floor unit allowed into the pool would also occupy a
``max_evidence_units`` slot, be shown to the decision model (where it can declare
sufficiency and stop the search), and be able to manufacture a conflict. So the
invariant is stated at the pool: **it contains only evidence that could
legitimately be cited**, and no later stage needs to know authority exists.
"""

from __future__ import annotations

import functools
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

from citenexus.answer.authority import (
    INSUFFICIENT_AUTHORITY,
    select_by_authority,
    tier_of,
)
from citenexus.answer.conflict import (
    CONFLICT_TOP_K,
    ConflictPair,
    collapse_near_duplicates,
    describe_conflicts,
    find_conflicts,
)
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
from citenexus.answer.segment import split_claims
from citenexus.answer.verify import is_supported_v2
from citenexus.domain.authority import AuthorityPolicy
from citenexus.domain.trust import TrustMode
from citenexus.lang.codes import Language, LanguageLike
from citenexus.lang.fallback import resolve_requested_answer_language
from citenexus.plugins import LanguageDetectorPlugin

ToolSpec = dict[str, Any]


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
    """One deduped Evidence Unit gathered by the loop.

    Mirrors ``retrieve.types.Candidate``'s two-text split, and for the same reason
    (0697c41): ``text`` is what the EU was INDEXED as — under contextual retrieval
    (spec §7) that carries a small model's situating blurb, which is a ranking and
    *navigation* aid and NOT the source's words. ``citable_text`` is the verbatim
    chunk, and it is the only text that may be generated from, verified against,
    or attributed to the document.
    """

    eu_id: str
    text: str
    document_id: str | None
    page: int | None
    language: str | None
    checksum: str | None
    signal: str
    score: float
    #: Caller-supplied source metadata as canonical JSON (ADR-0004). Opaque:
    #: only an ``AuthorityProfile`` reads it, and never the text above. ``""``
    #: (a tool that does not report it, or a pre-feature corpus) ⇒ unranked.
    authority_meta: str = ""
    #: The VERBATIM chunk as written by the source. ``None`` for a legacy index
    #: with no ``passage`` column, or a third-party tool that does not report one.
    passage: str | None = None

    @property
    def citable_text(self) -> str:
        """The text that may be quoted, generated from, and verified against.

        Falls back to ``text`` when no ``passage`` was reported — un-migrated, not
        broken, exactly as ``Candidate.citable_text`` does. Re-ingest to get the
        guarantee.
        """
        return self.passage if self.passage is not None else self.text


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
        authority_meta=str(row.get("authority_meta") or ""),
        passage=(str(passage) if (passage := row.get("passage")) is not None else None),
    )


class AgenticAnswerFlow:
    """The scripted deep-ask loop, ending in the per-claim single-EU gate."""

    def __init__(
        self,
        *,
        generator: Generator,
        decider: DecisionModel,
        tools: Sequence[ToolSpec],
        budget: LoopBudget | None = None,
        default_answer_language: LanguageLike = Language.ENGLISH,
        authority: AuthorityPolicy | None = None,
        detector: LanguageDetectorPlugin | None = None,
    ) -> None:
        self._generator = generator
        self._decider = decider
        self._search = _find_search(tools)
        self._budget = budget or LoopBudget()
        self._default_answer_language = default_answer_language
        # Used ONLY for ``answer_language="auto"`` -- the same rule as the strict
        # flow, because a guarantee that holds on one strategy is not one.
        self._detector = detector
        # The SAME policy the strict flow takes (ADR-0004). ``default.v1`` with
        # no floor is the default: every tier equal, nothing ever withheld.
        self._authority = authority or AuthorityPolicy.unranked()

    def ask(
        self,
        question: str,
        *,
        mode: TrustMode = TrustMode.strict,
        answer_language: LanguageLike | None = None,
    ) -> Result:
        budget = self._budget
        deadline = time.monotonic() + budget.timeout_s
        pool: dict[str, _PooledEvidence] = {}
        query = question
        tool_calls = 0
        hops = 0
        withheld = 0
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

            # AUTHORITY AT ADMISSION (ADR-0004). Standing is checked BEFORE the
            # pool, so a below-floor unit never occupies a budget slot, never
            # reaches the decision model, never enters the conflict window and
            # can never be the "some single EU" that satisfies a claim. Applying
            # it once at the end would be too late on all four counts.
            admissible = [eu for eu in (_to_pooled(row) for row in rows) if eu is not None]
            selection = select_by_authority(admissible, policy=self._authority, mode=mode)
            withheld += len(selection.excluded)

            added = 0
            capped = False
            for eu in selection.candidates:
                if eu.eu_id in pool:
                    continue
                pool[eu.eu_id] = eu
                added += 1
                if len(pool) >= budget.max_evidence_units:
                    capped = True
                    break
            if capped:
                stop_reason = LoopStopReason.budget
                break
            if added == 0 and not selection.excluded:
                # A hop that adds no unseen EU ends the loop (the deterministic
                # default stop). Draft/model text is never poolable — only EUs.
                #
                # A hop whose rows were all WITHHELD for standing is excluded
                # from this: "I found nothing" is not "what I found has no
                # standing", and conflating them here would repeat, inside the
                # loop, the very defect ADR-0004 exists to end. Such a hop falls
                # through to the decider and may refine — still bounded by
                # max_hops / max_tool_calls / timeout_s.
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
            withheld=withheld,
        )

    def _finish(
        self,
        question: str,
        pool: dict[str, _PooledEvidence],
        *,
        mode: TrustMode,
        answer_language: LanguageLike | None,
        deadline: float,
        stop_reason: LoopStopReason,
        hops: int,
        tool_calls: int,
        withheld: int,
    ) -> Result:
        # Order the pool by descending tier (stable, so equal tiers keep pooling
        # order). This is the same selection point, used for its ORDERING half:
        # the generator sees the strongest standing first, and the single-EU gate
        # attributes each claim to the most authoritative EU that supports it.
        # Nothing is withheld here — admission already did that.
        units = list(
            select_by_authority(list(pool.values()), policy=self._authority, mode=mode).candidates
        )
        floor_applied = withheld > 0
        languages = tuple(dict.fromkeys(e.language for e in units if e.language is not None))
        # The caller's word, then the question, then the configured default --
        # never the pool. ``languages`` stays a reported signal only.
        language = resolve_requested_answer_language(
            question,
            answer_language,
            detector=self._detector,
            default_answer_language=self._default_answer_language,
        )
        loop = LoopSignals(
            stop_reason=stop_reason,
            hops=hops,
            tool_calls=tool_calls,
            evidence_units=len(units),
        )
        if not units:
            # An empty pool because the floor withheld everything is a DIFFERENT
            # fact from an empty corpus, and says so — as in the strict flow, and
            # as here, without ever calling the generator.
            return self._refuse(
                mode=mode,
                language=language,
                reason=(
                    INSUFFICIENT_AUTHORITY
                    if floor_applied
                    else "no sufficiently relevant evidence found"
                ),
                loop=loop,
                authority_floor_applied=floor_applied,
            )

        # Generate from `citable_text` -- the VERBATIM chunks -- exactly as the
        # strict flow does (`answer/flow.py`). Handing the generator the enriched
        # `text` invites it to answer in the context model's words, which are then
        # gated against themselves and cited to the customer.
        passage = "\n".join(e.citable_text for e in units)
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
                authority_floor_applied=floor_applied,
            )

        supported, removed = self._gate(answer_text, units)
        if not supported:
            return self._refuse(
                mode=mode,
                language=language,
                reason="no claim passed the per-claim single-EU faithfulness gate",
                loop=loop,
                authority_floor_applied=floor_applied,
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
                passage=by_id[eu_id].citable_text,
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
        # Conflict surfacing (ADR-0007) applies here for the same reason it
        # applies to the strict flow: the loop pools evidence from several hops,
        # so it is *more* likely than a single-shot retrieval to hold two
        # passages that disagree. Detection reports and never resolves.
        window = units[:CONFLICT_TOP_K]
        conflict_pairs = find_conflicts([e.citable_text for e in window])
        touching = tuple(
            pair
            for pair in conflict_pairs
            if window[pair.left].eu_id in by_id or window[pair.right].eu_id in by_id
        )
        if touching and mode is TrustMode.strict:
            return self._refuse_on_conflict(
                mode=mode,
                language=language,
                window=window,
                touching=touching,
                total_conflicts=len(conflict_pairs),
                units=units,
                languages=languages,
                loop=loop,
                authority_floor_applied=floor_applied,
            )
        independent = [units[i] for i in collapse_near_duplicates([e.citable_text for e in units])]
        signals = EvidenceSignals(
            decision=decision,
            supporting_sources=len(used),
            distinct_documents=len({e.document_id or e.eu_id for e in independent}),
            retrieval_score_spread=_score_spread(units),
            all_claims_verified=removed == 0,
            unsupported_claims_removed=removed,
            conflicts_detected=len(conflict_pairs),
            languages_in_evidence=languages,
            loop=loop,
            # The WEAKEST tier among the cited EUs. A pooled answer rests on all
            # of its sources, so reporting the strongest would let one binding
            # citation launder a weaker co-citation: under "never wrong", an
            # answer's reported standing is the standing of its weakest support.
            authority_tier=_weakest_tier([by_id[eu_id] for eu_id in used], self._authority),
            authority_floor_applied=floor_applied,
        )
        return Result(
            answer=answer,
            answer_language=language,
            mode=mode,
            evidence=signals,
            claims=claims,
            sources=sources,
            conflicts=describe_conflicts(conflict_pairs, _documents(window))
            if mode is TrustMode.normal
            else (),
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
        for claim in split_claims(answer_text):
            source = next((eu for eu in units if is_supported_v2(claim, eu.citable_text)), None)
            if source is not None:
                supported.append((claim, source))
            else:
                removed += 1
        return supported, removed

    def _refuse_on_conflict(
        self,
        *,
        mode: TrustMode,
        language: str,
        window: Sequence[_PooledEvidence],
        touching: Sequence[ConflictPair],
        total_conflicts: int,
        units: Sequence[_PooledEvidence],
        languages: tuple[str, ...],
        loop: LoopSignals,
        authority_floor_applied: bool = False,
    ) -> Result:
        """Strict abstention that cites both sides of the disagreement."""
        cited: list[SourceRef] = []
        seen: set[str] = set()
        for pair in touching:
            for unit in (window[pair.left], window[pair.right]):
                if unit.eu_id in seen:
                    continue
                seen.add(unit.eu_id)
                cited.append(
                    SourceRef(
                        document=unit.document_id or unit.eu_id,
                        passage=unit.citable_text,
                        passage_language=unit.language or "und",
                        page=unit.page,
                    )
                )
        independent = [units[i] for i in collapse_near_duplicates([e.citable_text for e in units])]
        return Result(
            answer="The available evidence disagrees, so I can't answer that.",
            answer_language=language,
            mode=mode,
            evidence=EvidenceSignals(
                decision=Decision.refused,
                supporting_sources=len(independent),
                distinct_documents=len({e.document_id or e.eu_id for e in independent}),
                retrieval_score_spread=_score_spread(units),
                conflicts_detected=total_conflicts,
                languages_in_evidence=languages,
                loop=loop,
                authority_floor_applied=authority_floor_applied,
            ),
            sources=tuple(cited),
            conflicts=describe_conflicts(touching, _documents(window)),
            missing_evidence=("cited sources disagree and the conflict is unresolved",),
        )

    def _refuse(
        self,
        *,
        mode: TrustMode,
        language: str,
        reason: str,
        loop: LoopSignals,
        authority_floor_applied: bool = False,
    ) -> Result:
        return Result(
            answer="I can't answer that from the available evidence.",
            answer_language=language,
            mode=mode,
            evidence=EvidenceSignals(
                decision=Decision.refused,
                loop=loop,
                authority_floor_applied=authority_floor_applied,
            ),
            missing_evidence=(reason,),
        )


def _weakest_tier(units: Sequence[_PooledEvidence], policy: AuthorityPolicy) -> str:
    """The lowest-ranked tier NAME among the cited units ("" when unranked)."""
    if not units:
        return ""
    return min((tier_of(unit, policy) for unit in units), key=lambda tier: tier.rank).name


def _documents(units: Sequence[_PooledEvidence]) -> list[str]:
    return [unit.document_id or unit.eu_id for unit in units]


def _score_spread(units: Sequence[_PooledEvidence]) -> float:
    if not units:
        return 0.0
    scores = [e.score for e in units]
    return max(scores) - min(scores)
