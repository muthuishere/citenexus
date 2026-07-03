"""Embedding endpoints: the concrete OpenAI-compatible dense plugin + batching."""

from citenexus.embed.batcher import DEFAULT_BATCH_SIZE, embed_in_batches
from citenexus.embed.client import OpenAICompatibleEmbedding
from citenexus.http import Transport

__all__ = [
    "DEFAULT_BATCH_SIZE",
    "OpenAICompatibleEmbedding",
    "Transport",
    "embed_in_batches",
]
