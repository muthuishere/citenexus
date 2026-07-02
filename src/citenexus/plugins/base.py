"""The versioned ``Plugin`` base and the 11 typed plugin protocols (spec §4b).

Nothing in the CiteNexus pipeline is hardwired: every stage — extraction,
chunking, embedding, vision, graph extraction, retrieval, reranking, judging,
evaluation, language detection, memory — is a swappable, *typed* extension
point. These are ``abc.ABC`` protocols (NOT ``typing.Protocol``) on purpose: the
registry must *reject* non-conforming objects at runtime, and an ``isinstance``
gate against an ABC is reliable where structural checks are not. Subclassing the
ABC also forces the contract method to exist (instantiation raises ``TypeError``
otherwise) — the "typed, not duck-typed" rule.

Every plugin carries a non-empty ``plugin_version`` so the §4c provenance stamp
can record exactly what produced each artifact (validated at registration).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from citenexus.evidence import EvidenceUnit

# Forward contracts owned by `core-domain-types` and the later stage changes.
# Until those land they are loose aliases so this protocol layer stays IO-free
# and import-light; the concrete shapes arrive in their own changes (§4b).
ExtractedDoc = Any  # the parsed document a single extractor returns
Embedding = Any  # a dense vector + optional sparse term weights
VisionResult = Any  # a vision model's description of an image region
GraphFragment = Any  # entities/relations distilled from evidence units
Candidate = Any  # a scored retrieval candidate resolving down to an EvidenceUnit
Verdict = Any  # a judge's per-answer verdict
Metrics = Any  # an evaluator's aggregate metrics
LanguageResult = Any  # detected language + confidence (§11a)
Turn = Any  # one stored conversation turn (§18 memory)


class Plugin(ABC):
    """Common base for every plugin.

    ``plugin_version`` is the single field the §4c ``produced_by`` stamp reads;
    the registry enforces that it is a non-empty string at registration time.
    """

    plugin_version: str


class ExtractorPlugin(Plugin):
    """Parse a raw source into a document (§8)."""

    @abstractmethod
    def extract(self, source: Any) -> ExtractedDoc: ...


class ChunkerPlugin(Plugin):
    """Split a document into atomic Evidence Units (§7)."""

    @abstractmethod
    def chunk(self, doc: Any) -> list[EvidenceUnit]: ...


class EmbeddingPlugin(Plugin):
    """Embed texts into vectors — dense, with optional sparse weights (§4b)."""

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> list[Embedding]: ...


class VisionPlugin(Plugin):
    """Describe an image region (§9 conditional vision)."""

    @abstractmethod
    def describe(self, image_region: Any) -> VisionResult: ...


class GraphExtractorPlugin(Plugin):
    """Distill a graph fragment from evidence units (§16b)."""

    @abstractmethod
    def extract_graph(self, units: Sequence[EvidenceUnit]) -> GraphFragment: ...


class RetrieverPlugin(Plugin):
    """Return a ranked list of candidates for a query (§4b).

    Deliberately limited: a retriever ONLY contributes a ranked candidate list.
    It exposes no hook to fuse, rerank, ground, or emit an answer, so a
    third-party retriever can never bypass the RRF + grounding guarantees that
    stay in core.
    """

    @abstractmethod
    def retrieve(self, query: str, k: int) -> list[Candidate]: ...


class RerankerPlugin(Plugin):
    """Re-order candidates for a query (§4b rerank seam)."""

    @abstractmethod
    def rerank(self, query: str, candidates: Sequence[Candidate]) -> list[Candidate]: ...


class JudgePlugin(Plugin):
    """Judge an answer against its evidence and golden reference (§11a)."""

    @abstractmethod
    def judge(
        self,
        question: str,
        answer: str,
        evidence: Sequence[EvidenceUnit],
        golden: Any,
    ) -> Verdict: ...


class EvaluatorPlugin(Plugin):
    """Score a corpus against a golden set (§11a)."""

    @abstractmethod
    def evaluate(self, corpus: Any, golden: Any) -> Metrics: ...


class LanguageDetectorPlugin(Plugin):
    """Detect the language of a text (§11a)."""

    @abstractmethod
    def detect(self, text: str) -> LanguageResult: ...


class MemoryPlugin(Plugin):
    """Store and recall conversation turns (§18 memory)."""

    @abstractmethod
    def store(self, turn: Any) -> None: ...

    @abstractmethod
    def recall(self, query: str) -> list[Turn]: ...
