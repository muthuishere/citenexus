"""The grounded answer Result, its parts, and the answering-model client."""

from trustrag.answer.generator import OpenAICompatibleGenerator
from trustrag.answer.result import (
    Claim,
    Decision,
    EvidenceSignals,
    ProvenanceEntry,
    Result,
    SourceRef,
)

__all__ = [
    "Claim",
    "Decision",
    "EvidenceSignals",
    "OpenAICompatibleGenerator",
    "ProvenanceEntry",
    "Result",
    "SourceRef",
]
