"""``embed_in_batches`` — order-preserving batching over an ``EmbeddingPlugin``.

A long sequence of texts is split into consecutive batches of at most
``batch_size``, the plugin is called once per batch, and the results are
concatenated so the output order matches the input order. Keeping this a free
function (not a plugin method) lets it wrap *any* ``EmbeddingPlugin``.
"""

from __future__ import annotations

from collections.abc import Sequence

from citenexus.contracts import SequenceEmbedder, Vector, check_batch_arity

DEFAULT_BATCH_SIZE = 64


def embed_in_batches(
    plugin: SequenceEmbedder,
    texts: Sequence[str],
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[Vector]:
    """Embed ``texts`` in batches of ``batch_size``, preserving order."""
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    out: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        vectors = list(plugin.embed(batch))
        # PER BATCH, not just on the total. A batch that is short by one and a
        # later batch that is long by one net out to the right TOTAL count, so a
        # whole-call arity check passes while every pairing from the first short
        # batch onward is shifted -- an index that is not broken but plausibly
        # wrong forever. Measured: with batch_size=2 over four evidence units,
        # three of four queries then retrieved the wrong passage, with no error.
        check_batch_arity(len(batch), len(vectors))
        out.extend(vectors)
    return out
