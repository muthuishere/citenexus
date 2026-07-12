"""CiteNexus — evidence-first, multilingual, S3-native RAG.

Public surface is intentionally tiny (see docs/SPEC-v6.md §15): construct a
client, ``ingest``, ``ask``, and ``evaluate``. The heavy machinery lives behind
typed plugin protocols so nothing in the pipeline is hardwired.
"""

from citenexus.client import CiteNexus
from citenexus.delete import DeleteResult
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
from citenexus.storage.location import S3

__version__ = "0.2.0"

__all__ = [
    "S3",
    "AnthropicHttpEndpoint",
    "CiteNexus",
    "DeleteResult",
    "GeminiHttpEndpoint",
    "Hooks",
    "HttpClient",
    "HttpEndpoint",
    "OllamaHttpEndpoint",
    "OpenAIHttpEndpoint",
    "OpenRouterHttpEndpoint",
    "__version__",
]
