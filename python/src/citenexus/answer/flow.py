"""Grounded answer orchestration over retrieved Evidence Units."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from citenexus.answer.conflict import (
    CONFLICT_TOP_K,
    ConflictPair,
    collapse_near_duplicates,
    describe_conflicts,
    find_conflicts,
)
from citenexus.answer.result import (
    Claim,
    Decision,
    EvidenceSignals,
    ProvenanceEntry,
    Result,
    SourceRef,
)
from citenexus.answer.segment import split_claims
from citenexus.answer.verify import has_relevance_overlap_v2, is_supported_v2
from citenexus.domain.trust import TrustMode
from citenexus.lang.fallback import resolve_answer_language
from citenexus.retrieve.types import Candidate
from citenexus.tokenize import unsupported_scripts


class Generator(Protocol):
    """The LLM seam used by `ask()`.

    The generator receives the already-selected passage and the required answer
    language. It may call any endpoint, but the verifier decides what is usable.
    """

    def answer(self, question: str, passage: str, answer_language: str = "en") -> str: ...


# How many ranked passages may be offered to the generator before we abstain.
# Bounded because each attempt is a generator call: enough to survive an unlucky
# top passage, small enough that a genuinely unanswerable question stays cheap.
_MAX_GENERATION_ATTEMPTS = 5


def refusal(
    *,
    mode: TrustMode,
    answer_language: str,
    reason: str,
    unsupported: tuple[str, ...] = (),
) -> Result:
    """A localized refusal shell. Full localization lands with model-backed L5."""
    return Result(
        answer="I can't answer that from the available evidence.",
        answer_language=answer_language,
        mode=mode,
        evidence=EvidenceSignals(decision=Decision.refused, unsupported_scripts=unsupported),
        missing_evidence=(reason,),
    )


def _capability_reason(unsupported: tuple[str, ...]) -> str | None:
    """The refusal reason when the tokenizer cannot read the input at all.

    ADR-0011: where the tokenizer cannot process a script, the Result must say
    so, DISTINCT from "no supporting evidence". The two look identical from the
    outside — both are an abstain — but only one of them is a statement about
    the evidence, and conflating them is what kept the ASCII-only tokenizer
    invisible for the whole of 0.x.
    """
    if not unsupported:
        return None
    return f"unsupported script: {', '.join(unsupported)}"


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
        # Which scripts in play the tokenizer does not CLAIM (ADR-0011). Note
        # "claim", not "process": the bigram path will mechanically produce
        # tokens for Khmer, Lao or Myanmar, and the gate will then accept a
        # verbatim quote in them. That is worse than refusing, because it looks
        # exactly like a verified answer while resting on a segmentation no
        # fixture has ever checked. An unclaimed script therefore ABSTAINS, and
        # says why.
        question_gap = unsupported_scripts(relevance_query)
        script_gap: set[str] = set(question_gap)
        for candidate in candidates:
            script_gap.update(unsupported_scripts(candidate.citable_text or candidate.text or ""))
        unsupported = tuple(sorted(script_gap))

        # A question we cannot read is not answerable from anything.
        if question_gap:
            return refusal(
                mode=mode,
                answer_language=language,
                reason=_capability_reason(unsupported) or "",
                unsupported=unsupported,
            )

        grounded = [
            candidate
            for candidate in candidates
            if candidate.text
            and not unsupported_scripts(candidate.citable_text or candidate.text)
            and has_relevance_overlap_v2(relevance_query, candidate.text)
        ]
        if not grounded:
            return refusal(
                mode=mode,
                answer_language=language,
                reason=_capability_reason(unsupported) or "no sufficiently relevant evidence found",
                unsupported=unsupported,
            )

        # Conflict detection runs over the grounded candidates, before anything
        # is generated (ADR-0007). It reports and never resolves: picking a
        # winner by rank, recency or score is a policy decision belonging to the
        # caller and to authority (ADR-0004), and rank order deciding which of
        # two contradictory truths the caller sees is the defect this closes.
        window = grounded[:CONFLICT_TOP_K]
        conflict_pairs = find_conflicts([c.citable_text for c in window])

        # Near-duplicate collapse feeds the corroboration signals only. The same
        # pairwise comparison that finds "same subject, opposite polarity" finds
        # "same subject, same text" -- clones ingested under different document
        # ids -- and those are one piece of evidence, not N.
        independent = [
            grounded[i] for i in collapse_near_duplicates([c.citable_text for c in grounded])
        ]

        # Try the best passages in rank order and keep the first answer that passes
        # the faithfulness gate. Generating only from grounded[0] made the gate a
        # coin flip on that one passage's phrasing: a shop with 122 earrings in the
        # index refused "Do you have earrings?" while answering the same question
        # lowercased, because the capital-D wording nudged the generator into one
        # token the top passage happened not to contain. The guarantee is unchanged
        # -- every returned answer still has to be is_supported() by the passage it
        # cites -- we just stop discarding the other candidates on the first miss.
        #
        # Note we generate from and verify against `citable_text` -- the VERBATIM
        # chunk -- not `text`. Under contextual retrieval `text` carries the context
        # model's situating blurb, and generating from it let that blurb be quoted
        # back as the source's own words (Indie and Harper cited "This chunk lists
        # the items available in the Earrings section..." to indieandharper.com; the
        # shop never wrote that sentence). Worse, the faithfulness gate then verified
        # the answer against text containing the model's prose, so the guard admitted
        # its own output as evidence. Rank on the enrichment, quote only the source.
        #
        # Verification is PER ATOMIC CLAIM (ADR-0009). The answer is segmented and
        # each claim is checked independently against the cited passage;
        # unsupported claims are DROPPED rather than failing the answer whole, so
        # a half-true generation returns its true half instead of nothing. A
        # candidate is accepted as soon as at least one of its claims survives.
        top = None
        top_index = -1
        verdicts: list[tuple[str, bool]] = []
        for index, candidate in enumerate(grounded[:_MAX_GENERATION_ATTEMPTS]):
            attempt = self._generator.answer(question, candidate.citable_text, language)
            attempted = [
                (claim, is_supported_v2(claim, candidate.citable_text))
                for claim in split_claims(attempt)
            ]
            if any(supported for _, supported in attempted):
                top, top_index, verdicts = candidate, index, attempted
                break
        if top is None:
            return Result(
                answer="I can't answer that from the available evidence.",
                answer_language=language,
                mode=mode,
                evidence=EvidenceSignals(
                    decision=Decision.refused,
                    conflicts_detected=len(conflict_pairs),
                    unsupported_scripts=unsupported,
                ),
                missing_evidence=(
                    _capability_reason(unsupported)
                    or "generated answer failed the faithfulness gate",
                ),
            )
        passage = top.citable_text

        # TrustMode coupling. An unresolved conflict touching the answer's own
        # claim -- i.e. one whose two sides include the passage we are about to
        # cite -- is not answerable in strict mode: the honest output is "these
        # sources disagree, here are both", not a coin flip on rank order. This
        # can only ever produce MORE abstention, so it cannot admit an ungrounded
        # claim.
        touching = tuple(pair for pair in conflict_pairs if top_index in (pair.left, pair.right))
        if touching and mode is TrustMode.strict:
            return _conflict_abstention(
                mode=mode,
                answer_language=language,
                window=window,
                touching=touching,
                total_conflicts=len(conflict_pairs),
                independent=independent,
                grounded=grounded,
                languages=languages,
            )
        supported_claims = [claim for claim, supported in verdicts if supported]
        removed = len(verdicts) - len(supported_claims)
        answer = " ".join(supported_claims)

        source = SourceRef(
            document=top.document_id or top.eu_id,
            passage=passage,
            passage_language=top.language or "und",
            page=top.page,
            source_uri=top.raw_uri,
        )
        # Every atomic claim carries its own verdict, so a drop is auditable
        # rather than silent. Only supported claims reach ``answer`` and
        # provenance.
        claims = tuple(
            Claim(claim=claim, supported=supported, sources=(top.eu_id,) if supported else ())
            for claim, supported in verdicts
        )
        provenance = tuple(
            ProvenanceEntry(
                claim=claim,
                evidence_unit=top.eu_id,
                document_id=top.document_id or top.eu_id,
                s3_object=top.raw_uri or "",
                checksum=top.checksum or "",
                page=top.page,
                produced_by={"retrieval_signal": top.signal.value},
            )
            for claim in supported_claims
        )
        signals = EvidenceSignals(
            decision=Decision.answered,
            supporting_sources=len(independent),
            distinct_documents=len({c.document_id or c.eu_id for c in independent}),
            retrieval_score_spread=_score_spread(grounded),
            all_claims_verified=removed == 0,
            unsupported_claims_removed=removed,
            conflicts_detected=len(conflict_pairs),
            languages_in_evidence=languages,
            unsupported_scripts=unsupported,
        )
        # `normal` surfaces the conflict alongside the answer; `exploratory`
        # records the count only. Neither resolves it.
        surfaced = _describe(conflict_pairs, window) if mode is TrustMode.normal else ()
        return Result(
            answer=answer,
            answer_language=language,
            mode=mode,
            evidence=signals,
            claims=claims,
            sources=(source,),
            conflicts=surfaced,
            provenance=provenance,
        )


def _document_of(candidate: Candidate) -> str:
    return candidate.document_id or candidate.eu_id


def _describe(pairs: Sequence[ConflictPair], window: Sequence[Candidate]) -> tuple[str, ...]:
    return describe_conflicts(pairs, [_document_of(c) for c in window])


def _conflict_abstention(
    *,
    mode: TrustMode,
    answer_language: str,
    window: Sequence[Candidate],
    touching: Sequence[ConflictPair],
    total_conflicts: int,
    independent: Sequence[Candidate],
    grounded: Sequence[Candidate],
    languages: tuple[str, ...],
) -> Result:
    """Strict-mode abstention that cites BOTH sides of the disagreement.

    A refusal that hides the evidence is only marginally better than a confident
    pick: the caller cannot check the library's reasoning or resolve the conflict
    themselves. Both passages are returned as sources, verbatim.
    """
    cited: list[SourceRef] = []
    seen: set[str] = set()
    for pair in touching:
        for candidate in (window[pair.left], window[pair.right]):
            if candidate.eu_id in seen:
                continue
            seen.add(candidate.eu_id)
            cited.append(
                SourceRef(
                    document=_document_of(candidate),
                    passage=candidate.citable_text,
                    passage_language=candidate.language or "und",
                    page=candidate.page,
                    source_uri=candidate.raw_uri,
                )
            )
    return Result(
        answer="The available evidence disagrees, so I can't answer that.",
        answer_language=answer_language,
        mode=mode,
        evidence=EvidenceSignals(
            decision=Decision.refused,
            supporting_sources=len(independent),
            distinct_documents=len({_document_of(c) for c in independent}),
            retrieval_score_spread=_score_spread(grounded),
            conflicts_detected=total_conflicts,
            languages_in_evidence=languages,
        ),
        sources=tuple(cited),
        conflicts=_describe(touching, window),
        missing_evidence=("cited sources disagree and the conflict is unresolved",),
    )


def _score_spread(candidates: Sequence[Candidate]) -> float:
    if not candidates:
        return 0.0
    scores = [c.score for c in candidates]
    return max(scores) - min(scores)
