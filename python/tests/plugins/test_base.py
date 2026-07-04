"""The versioned Plugin base and the 11 typed protocol ABCs (spec §4b)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from citenexus.plugins import (
    ChunkerPlugin,
    EmbeddingPlugin,
    EvaluatorPlugin,
    ExtractorPlugin,
    GraphExtractorPlugin,
    JudgePlugin,
    LanguageDetectorPlugin,
    MemoryPlugin,
    Plugin,
    RerankerPlugin,
    RetrieverPlugin,
    VisionPlugin,
)

ALL_PROTOCOLS: tuple[type[Plugin], ...] = (
    ExtractorPlugin,
    ChunkerPlugin,
    EmbeddingPlugin,
    VisionPlugin,
    GraphExtractorPlugin,
    RetrieverPlugin,
    RerankerPlugin,
    JudgePlugin,
    EvaluatorPlugin,
    LanguageDetectorPlugin,
    MemoryPlugin,
)


def test_there_are_exactly_eleven_protocols() -> None:
    assert len(ALL_PROTOCOLS) == 11
    assert len(set(ALL_PROTOCOLS)) == 11


def test_every_protocol_derives_from_plugin() -> None:
    for proto in ALL_PROTOCOLS:
        assert issubclass(proto, Plugin)


def test_every_protocol_is_abstract() -> None:
    for proto in ALL_PROTOCOLS:
        with pytest.raises(TypeError):
            proto()


def test_subclass_omitting_contract_method_cannot_instantiate() -> None:
    class HalfEmbedder(EmbeddingPlugin):
        plugin_version = "1.0.0"
        # deliberately omits embed()

    with pytest.raises(TypeError):
        HalfEmbedder()  # type: ignore[abstract]


def test_concrete_plugin_exposes_non_empty_plugin_version() -> None:
    class RealEmbedder(EmbeddingPlugin):
        plugin_version = "bge-m3-1.5"

        def embed(self, texts: Sequence[str]) -> list[Any]:
            return [float(len(t)) for t in texts]

    plugin = RealEmbedder()
    assert isinstance(plugin.plugin_version, str)
    assert plugin.plugin_version != ""


def test_each_protocol_declares_its_contract_method() -> None:
    expected = {
        ExtractorPlugin: "extract",
        ChunkerPlugin: "chunk",
        EmbeddingPlugin: "embed",
        VisionPlugin: "describe",
        GraphExtractorPlugin: "extract_graph",
        RetrieverPlugin: "retrieve",
        RerankerPlugin: "rerank",
        JudgePlugin: "judge",
        EvaluatorPlugin: "evaluate",
        LanguageDetectorPlugin: "detect",
        MemoryPlugin: "store",
    }
    for proto, method in expected.items():
        assert method in proto.__abstractmethods__


def test_memory_plugin_has_both_store_and_recall() -> None:
    assert "store" in MemoryPlugin.__abstractmethods__
    assert "recall" in MemoryPlugin.__abstractmethods__


def test_retriever_contract_is_limited_to_ranked_candidates() -> None:
    # Fusion stays in core: a RetrieverPlugin only yields ranked candidates and
    # exposes NO hook to fuse / rerank / ground / answer.
    assert RetrieverPlugin.__abstractmethods__ == frozenset({"retrieve"})
    for forbidden in ("fuse", "ground", "rerank", "answer", "grounding"):
        assert not hasattr(RetrieverPlugin, forbidden)
