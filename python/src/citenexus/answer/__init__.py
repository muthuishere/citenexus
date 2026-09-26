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

# verify_answer's evidence and options (ADR-0016). The function itself is
# exported top-level as ``citenexus.verify_answer``; it is NOT re-bound here,
# where the name is the submodule the guards import.
from citenexus.answer.verify_answer import EvidenceUnit, Facet, VerifyOptions

__all__ = [
    "AnthropicGenerator",
    "Claim",
    "Decision",
    "EvidenceSignals",
    "EvidenceUnit",
    "Facet",
    "LoopSignals",
    "LoopStopReason",
    "OpenAICompatibleGenerator",
    "ProvenanceEntry",
    "Result",
    "SourceRef",
    "VerifyOptions",
]
