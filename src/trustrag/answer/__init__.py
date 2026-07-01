"""The grounded answer Result, its parts, and the answering-model clients."""

from trustrag.answer.anthropic import AnthropicGenerator
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
    "AnthropicGenerator",
    "Claim",
    "Decision",
    "EvidenceSignals",
    "OpenAICompatibleGenerator",
    "ProvenanceEntry",
    "Result",
    "SourceRef",
]
