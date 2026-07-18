"""The grounded answer Result, its parts, and the answering-model clients."""

from citenexus.answer.anthropic import AnthropicGenerator
from citenexus.answer.generator import OpenAICompatibleGenerator
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

__all__ = [
    "AnthropicGenerator",
    "Claim",
    "Decision",
    "EvidenceSignals",
    "LoopSignals",
    "LoopStopReason",
    "OpenAICompatibleGenerator",
    "ProvenanceEntry",
    "Result",
    "SourceRef",
]
