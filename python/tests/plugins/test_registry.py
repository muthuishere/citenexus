"""PluginRegistry: typed registration, single-slot vs retriever fusion set, use()."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from citenexus.plugins import (
    EmbeddingPlugin,
    PluginRegistry,
    RerankerPlugin,
    RetrieverPlugin,
)


class FakeEmbedder(EmbeddingPlugin):
    plugin_version = "embed-1"

    def __init__(self, tag: str = "a") -> None:
        self.tag = tag

    def embed(self, texts: Sequence[str]) -> list[Any]:
        return [float(len(t)) for t in texts]


class FakeReranker(RerankerPlugin):
    plugin_version = "rerank-1"

    def rerank(self, query: str, candidates: Sequence[Any]) -> list[Any]:
        return list(candidates)


class FakeRetriever(RetrieverPlugin):
    plugin_version = "retr-1"

    def __init__(self, tag: str = "vector") -> None:
        self.tag = tag

    def retrieve(self, query: str, k: int) -> list[Any]:
        # A ranked candidate list — descending score order; it cannot fuse.
        return [{"id": f"{self.tag}-{i}", "score": float(k - i)} for i in range(k)]


# A "built-in" default uses the exact same base — no privileged path.
class BuiltinEmbedder(EmbeddingPlugin):
    plugin_version = "builtin-bge-m3"

    def embed(self, texts: Sequence[str]) -> list[Any]:
        return [0.0 for _ in texts]


def test_conforming_plugin_registers_and_resolves_by_type() -> None:
    reg = PluginRegistry()
    plugin = FakeEmbedder()
    reg.register(plugin)
    assert reg.resolve(EmbeddingPlugin) is plugin


def test_non_conforming_object_is_rejected() -> None:
    reg = PluginRegistry()

    class NotAPlugin:
        plugin_version = "x"

        def embed(self, texts: Sequence[str]) -> list[Any]:
            return []

    with pytest.raises(TypeError):
        reg.register(NotAPlugin())  # type: ignore[arg-type]
    # nothing stored
    with pytest.raises(KeyError):
        reg.resolve(EmbeddingPlugin)


def test_empty_plugin_version_is_rejected() -> None:
    reg = PluginRegistry()

    class NoVersion(EmbeddingPlugin):
        plugin_version = ""

        def embed(self, texts: Sequence[str]) -> list[Any]:
            return []

    with pytest.raises(ValueError):
        reg.register(NoVersion())
    with pytest.raises(KeyError):
        reg.resolve(EmbeddingPlugin)


def test_single_slot_is_last_wins() -> None:
    reg = PluginRegistry()
    first = FakeEmbedder(tag="first")
    second = FakeEmbedder(tag="second")
    reg.register(first)
    reg.register(second)
    resolved = reg.resolve(EmbeddingPlugin)
    assert resolved is second
    assert isinstance(resolved, FakeEmbedder)
    assert resolved.tag == "second"


def test_register_retriever_accumulates_a_fusion_set() -> None:
    reg = PluginRegistry()
    r1 = FakeRetriever(tag="vector")
    r2 = FakeRetriever(tag="sparse")
    reg.register_retriever(r1)
    reg.register_retriever(r2)
    assert reg.retrievers == (r1, r2)


def test_register_rejects_a_retriever_as_single_slot() -> None:
    reg = PluginRegistry()
    with pytest.raises(TypeError):
        reg.register(FakeRetriever())


def test_use_routes_retriever_into_fusion_set() -> None:
    reg = PluginRegistry()
    r1 = FakeRetriever(tag="vector")
    r2 = FakeRetriever(tag="sparse")
    reg.use(r1)
    reg.use(r2)
    assert reg.retrievers == (r1, r2)


def test_use_routes_single_slot_plugin_to_its_slot() -> None:
    reg = PluginRegistry()
    reranker = FakeReranker()
    reg.use(reranker)
    assert reg.resolve(RerankerPlugin) is reranker


def test_use_rejects_non_plugin() -> None:
    reg = PluginRegistry()
    with pytest.raises(TypeError):
        reg.use(object())  # type: ignore[arg-type]


def test_object_matching_two_protocols_is_rejected() -> None:
    reg = PluginRegistry()

    class DualPlugin(EmbeddingPlugin, RerankerPlugin):
        plugin_version = "dual"

        def embed(self, texts: Sequence[str]) -> list[Any]:
            return []

        def rerank(self, query: str, candidates: Sequence[Any]) -> list[Any]:
            return list(candidates)

    with pytest.raises(TypeError):
        reg.use(DualPlugin())


def test_builtin_registers_via_the_same_path() -> None:
    reg = PluginRegistry()
    builtin = BuiltinEmbedder()
    reg.use(builtin)
    assert reg.resolve(EmbeddingPlugin) is builtin


def test_retriever_yields_a_ranked_candidate_list() -> None:
    retriever = FakeRetriever(tag="vector")
    candidates = retriever.retrieve("q", k=3)
    assert len(candidates) == 3
    scores = [c["score"] for c in candidates]
    assert scores == sorted(scores, reverse=True)
