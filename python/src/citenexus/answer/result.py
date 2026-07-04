"""The Result object and its parts (spec §16, §12, §11).

A Result is a grounded answer with a reproducible provenance chain. Confidence is
expressed as *structured signals* (§12), never a scalar — an uncalibrated "0.87"
is worse than none in regulated domains. The cited ``passage`` stays verbatim in
its source language; any ``translation`` is additive and never overwrites it (§11).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from citenexus.domain.trust import TrustMode
from citenexus.evidence.unit import BBox


class Decision(StrEnum):
    """The outcome recorded on the evidence signals."""

    answered = "answered"
    refused = "refused"
    partial = "partial"


class EvidenceSignals(BaseModel):
    """Structured retrieval/verification signals — replaces scalar confidence (§12)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: Decision
    supporting_sources: int = 0
    distinct_documents: int = 0
    retrieval_score_spread: float = 0.0
    all_claims_verified: bool = False
    unsupported_claims_removed: int = 0
    conflicts_detected: int = 0
    languages_in_evidence: tuple[str, ...] = ()


class SourceRef(BaseModel):
    """A cited source: verbatim passage in its source language, plus optional
    additive translation (§16, §11)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document: str
    passage: str
    passage_language: str
    page: int | None = None
    bbox: BBox | None = None
    source_uri: str | None = None
    # Optional, MARKED translation in the answer language — never replaces passage.
    translation: str | None = None


class Claim(BaseModel):
    """A single claim in the answer and the EUs that support it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: str
    supported: bool
    sources: tuple[str, ...] = ()


class ProvenanceEntry(BaseModel):
    """One link of the reproducible chain: claim → EU → page+bbox → document →
    S3 object → checksum → producing plugins (§16)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: str
    evidence_unit: str
    document_id: str
    s3_object: str
    checksum: str
    page: int | None = None
    bbox: BBox | None = None
    # The artifact's ``produced_by`` stamp. Typed structurally for now; tightened
    # to the concrete ProducedBy model once `provenance-and-rebuild` lands (§4c).
    produced_by: dict[str, Any] | None = None


class Result(BaseModel):
    """A grounded answer, or a refusal, with full evidence + provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    answer: str
    # The query language L. The answer is guaranteed to be in this language (§11);
    # independent of the evidence languages.
    answer_language: str
    mode: TrustMode
    evidence: EvidenceSignals
    claims: tuple[Claim, ...] = ()
    sources: tuple[SourceRef, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    provenance: tuple[ProvenanceEntry, ...] = ()
