"""CiteNexus — evidence-first, multilingual, S3-native RAG.

Public surface is intentionally tiny (see docs/SPEC-v6.md §15): construct a
client, ``ingest``, ``ask``, and ``evaluate``. The heavy machinery lives behind
typed plugin protocols so nothing in the pipeline is hardwired.
"""

# The four injected model clients. They share one shape -- keyword-only
# base_url + model + transport + headers -- so any OpenAI-compatible endpoint
# works, and a caller writing their own provider has a surface to match. They
# lived behind deep module paths until now, which made the uniformity invisible.
from citenexus.answer.generator import OpenAICompatibleGenerator
from citenexus.client import CiteNexus

# The published contracts those clients implement (ADR-0014). A provider author
# needs the CONTRACT, not the constructor: match the shape and you are a
# provider -- no CiteNexus base class to inherit, no socket required.
from citenexus.contracts import (
    CompletionProvider,
    EmbeddingProvider,
    GeneratorProvider,
    RerankerProvider,
    SequenceEmbedder,
    SingleTextEmbedder,
    Vector,
    VisionProvider,
)
from citenexus.delete import DeleteResult
from citenexus.embed.client import OpenAICompatibleEmbedding
from citenexus.hooks import Hooks
from citenexus.http import (
    AnthropicHttpEndpoint,
    GeminiHttpEndpoint,
    HttpClient,
    HttpEndpoint,
    OllamaHttpEndpoint,
    OpenAIHttpEndpoint,
    OpenRouterHttpEndpoint,
)
from citenexus.reconcile import (
    CorpusEntry,
    CorpusManifest,
    DriftedDocument,
    ReconcileReport,
    RemediationReport,
)
from citenexus.retrieve.rerank import OpenAICompatibleReranker
from citenexus.storage.location import S3
from citenexus.vision.client import OpenAICompatibleVision

__version__ = "0.2.0"

__all__ = [
    "S3",
    "AnthropicHttpEndpoint",
    "CiteNexus",
    "CompletionProvider",
    "CorpusEntry",
    "CorpusManifest",
    "DeleteResult",
    "DriftedDocument",
    "EmbeddingProvider",
    "GeminiHttpEndpoint",
    "GeneratorProvider",
    "Hooks",
    "HttpClient",
    "HttpEndpoint",
    "OllamaHttpEndpoint",
    "OpenAICompatibleEmbedding",
    "OpenAICompatibleGenerator",
    "OpenAICompatibleReranker",
    "OpenAICompatibleVision",
    "OpenAIHttpEndpoint",
    "OpenRouterHttpEndpoint",
    "ReconcileReport",
    "RemediationReport",
    "RerankerProvider",
    "SequenceEmbedder",
    "SingleTextEmbedder",
    "Vector",
    "VisionProvider",
    "__version__",
]
