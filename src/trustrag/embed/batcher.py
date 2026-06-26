"""``embed_in_batches`` — order-preserving batching over an ``EmbeddingPlugin``.

A long sequence of texts is split into consecutive batches of at most
``batch_size``, the plugin is called once per batch, and the results are
concatenated so the output order matches the input order. Keeping this a free
function (not a plugin method) lets it wrap *any* ``EmbeddingPlugin``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

DEFAULT_BATCH_SIZE = 64


class _BatchEmbedder(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def embed_in_batches(
    plugin: _BatchEmbedder,
    texts: Sequence[str],
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[list[float]]:
    """Embed ``texts`` in batches of ``batch_size``, preserving order."""
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    out: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        out.extend(plugin.embed(texts[start : start + batch_size]))
    return out
