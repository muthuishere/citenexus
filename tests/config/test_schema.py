"""Configuration schema parses the §17 surface with sane defaults (spec §17)."""

import pytest
from pydantic import ValidationError

from trustrag.config.schema import LexicalSignal, TrustRAGConfig
from trustrag.config.signals import Signal
from trustrag.domain.trust import TrustMode


def test_defaults_match_specification() -> None:
    config = TrustRAGConfig(storage={"bucket": "s3://my-bucket"})
    assert config.trust.default_mode is TrustMode.strict
    assert config.retrieval.rrf_k == 60
    assert config.retrieval.top_k == 11
    assert config.retrieval.lexical_signal is LexicalSignal.bge_m3_sparse
    assert config.multilingual.detect_confidence_threshold == 0.50
    assert config.multilingual.answer_in_query_language is True


def test_default_client_declares_all_signals() -> None:
    config = TrustRAGConfig(storage={"bucket": "s3://my-bucket"})
    assert set(config.signals) == set(Signal)


def test_unknown_signal_is_rejected_with_validation_error() -> None:
    with pytest.raises(ValidationError) as exc:
        TrustRAGConfig(storage={"bucket": "s3://b"}, signals=["telepathy"])
    assert "telepathy" in str(exc.value)


def test_partition_hierarchy_accepts_any_depth() -> None:
    flat = TrustRAGConfig(
        storage={"bucket": "s3://b", "partition_hierarchy": ["workspace"]}
    )
    three = TrustRAGConfig(
        storage={
            "bucket": "s3://b",
            "partition_hierarchy": ["org", "product_line", "product"],
        }
    )
    four = TrustRAGConfig(
        storage={
            "bucket": "s3://b",
            "partition_hierarchy": ["firm", "practice", "client", "matter"],
        }
    )
    assert flat.storage.partition_hierarchy == ("workspace",)
    assert three.storage.partition_hierarchy == ("org", "product_line", "product")
    assert four.storage.partition_hierarchy == ("firm", "practice", "client", "matter")


def test_partition_hierarchy_rejects_empty() -> None:
    with pytest.raises(ValidationError):
        TrustRAGConfig(storage={"bucket": "s3://b", "partition_hierarchy": []})


def test_full_section17_surface_validates() -> None:
    config = TrustRAGConfig.model_validate(
        {
            "storage": {
                "bucket": "s3://my-bucket",
                "partition_hierarchy": ["org", "product_line", "product"],
            },
            "llm": {"model": "qwen2.5", "endpoint": "http://localhost:11434/v1"},
            "embedding": {"model": "bge-m3"},
            "reranker": {"model": "bge-reranker-v2-m3"},
            "vision": {"enabled": True, "prefilter": {"enabled": True}},
            "vector_store": {"backend": "lancedb"},
            "graph": {"enabled": True, "community_algorithm": "leiden"},
            "retrieval": {"rrf_k": 60, "top_k": 11, "lexical_signal": "bge_m3_sparse"},
            "trust": {"default_mode": "strict"},
            "multilingual": {
                "detector": "fasttext-lid176",
                "detect_confidence_threshold": 0.5,
                "answer_in_query_language": True,
            },
            "access_control": {"enabled": False},
            "plugins": {"embedder": "bge-m3"},
            "provenance": {"enabled": True},
            "worker": {"max_retries": 3},
            "telemetry": {"enabled": True},
            "memory": {"enabled": False},
            "judge": {"enabled": False},
            "streaming": {"enabled": False},
            "signals": ["embedding", "text"],
        }
    )
    assert config.storage.bucket == "s3://my-bucket"
    assert config.vision.prefilter.enabled is True
    assert config.graph.community_algorithm == "leiden"
    assert set(config.signals) == {Signal.embedding, Signal.text}
