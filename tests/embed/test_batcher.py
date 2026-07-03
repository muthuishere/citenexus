"""embed_in_batches — order-preserving batching over any EmbeddingPlugin."""

from __future__ import annotations

from collections.abc import Sequence

from citenexus.embed import embed_in_batches


class CountingPlugin:
    """Echoes one index-tagged vector per text and counts endpoint calls."""

    plugin_version = "counting-fake-v1"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self._seq = 0

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        out: list[list[float]] = []
        for _ in texts:
            out.append([float(self._seq)])
            self._seq += 1
        return out


def test_batches_preserve_order_and_call_count() -> None:
    plugin = CountingPlugin()
    texts = ["t0", "t1", "t2", "t3", "t4"]
    vecs = embed_in_batches(plugin, texts, batch_size=2)

    assert len(plugin.calls) == 3
    assert [len(c) for c in plugin.calls] == [2, 2, 1]
    assert plugin.calls == [["t0", "t1"], ["t2", "t3"], ["t4"]]

    assert len(vecs) == 5
    assert vecs == [[0.0], [1.0], [2.0], [3.0], [4.0]]


def test_empty_input_makes_no_calls() -> None:
    plugin = CountingPlugin()
    assert embed_in_batches(plugin, [], batch_size=2) == []
    assert plugin.calls == []


def test_default_batch_size_is_64() -> None:
    plugin = CountingPlugin()
    texts = [f"t{i}" for i in range(65)]
    embed_in_batches(plugin, texts)
    assert [len(c) for c in plugin.calls] == [64, 1]
