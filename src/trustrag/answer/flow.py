"""Grounded answer orchestration over retrieved Evidence Units."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from trustrag.answer.result import (
    Claim,
    Decision,
    EvidenceSignals,
    ProvenanceEntry,
    Result,
    SourceRef,
)
from trustrag.answer.verify import has_relevance_overlap, is_supported
from trustrag.domain.trust import TrustMode
from trustrag.lang.fallback import resolve_answer_language
from trustrag.retrieve.types import Candidate


class Generator(Protocol):
    """The LLM seam used by `ask()`.

    The generator receives the already-selected passage and the required answer
    language. It may call any endpoint, but the verifier decides what is usable.
    """

    def answer(self, question: str, passage: str, answer_language: str = "en") -> str: ...


def refusal(
    *,
    mode: TrustMode,
    answer_language: str,
    reason: str,
) -> Result:
    """A localized refusal shell. Full localization lands with model-backed L5."""
    return Result(
        answer="I can't answer that from the available evidence.",
        answer_language=answer_language,
        mode=mode,
        evidence=EvidenceSignals(decision=Decision.refused),
        missing_evidence=(reason,),
    )


class AnswerFlow:
    """Retrieve candidates → generate from top evidence → verify → Result."""

    def __init__(
        self,
        *,
        generator: Generator,
        default_answer_language: str = "en",
    ) -> None:
        self._generator = generator
        self._default_answer_language = default_answer_language

    def ask(
        self,
        question: str,
        candidates: Sequence[Candidate],
        *,
        mode: TrustMode = TrustMode.strict,
        answer_language: str | None = None,
        evidence_query: str | None = None,
    ) -> Result:
        relevance_query = evidence_query or question
        languages = tuple(dict.fromkeys(c.language for c in candidates if c.language is not None))
        language = resolve_answer_language(
            detection=None,
            answer_language=answer_language,
            languages_in_evidence=languages,
            default_answer_language=self._default_answer_language,
        )
        grounded = [
            candidate
            for candidate in candidates
            if candidate.text and has_relevance_overlap(relevance_query, candidate.text)
        ]
        if not grounded:
            return refusal(
                mode=mode,
                answer_language=language,
                reason="no sufficiently relevant evidence found",
            )

        top = grounded[0]
        passage = top.text or ""
        answer = self._generator.answer(question, passage, language)
        if not is_supported(answer, passage):
            return refusal(
                mode=mode,
                answer_language=language,
                reason="generated answer failed the faithfulness gate",
            )

        source = SourceRef(
            document=top.document_id or top.eu_id,
            passage=passage,
            passage_language=top.language or "und",
            page=top.page,
            source_uri=top.raw_uri,
        )
        claim = Claim(claim=answer, supported=True, sources=(top.eu_id,))
        provenance = ProvenanceEntry(
            claim=answer,
            evidence_unit=top.eu_id,
            document_id=top.document_id or top.eu_id,
            s3_object=top.raw_uri or "",
            checksum=top.checksum or "",
            page=top.page,
            produced_by={"retrieval_signal": top.signal.value},
        )
        signals = EvidenceSignals(
            decision=Decision.answered,
            supporting_sources=len(grounded),
            distinct_documents=len({c.document_id or c.eu_id for c in grounded}),
            retrieval_score_spread=_score_spread(grounded),
            all_claims_verified=True,
            languages_in_evidence=languages,
        )
        return Result(
            answer=answer,
            answer_language=language,
            mode=mode,
            evidence=signals,
            claims=(claim,),
            sources=(source,),
            provenance=(provenance,),
        )


def _score_spread(candidates: Sequence[Candidate]) -> float:
    if not candidates:
        return 0.0
    scores = [c.score for c in candidates]
    return max(scores) - min(scores)
