"""Embedding endpoints: the concrete OpenAI-compatible dense plugin + batching."""

from trustrag.embed.batcher import DEFAULT_BATCH_SIZE, embed_in_batches
from trustrag.embed.client import OpenAICompatibleEmbedding, Transport

__all__ = [
    "DEFAULT_BATCH_SIZE",
    "OpenAICompatibleEmbedding",
    "Transport",
    "embed_in_batches",
]
