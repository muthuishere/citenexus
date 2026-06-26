"""ProducedBy provenance stamp — shape + JSON round-trip (spec §4c)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from trustrag.provenance import (
    ModelManifest,
    ProducedBy,
    ProvenanceManifest,
    StageStamp,
)


def _full_stamp() -> ProducedBy:
    return ProducedBy(
        artifact_version=3,
        extractor=StageStamp(plugin="pdfplumber", plugin_version="1.2.0"),
        chunker=StageStamp(plugin="recursive", plugin_version="0.4.1"),
        vision=StageStamp(
            plugin="qwen-vl", plugin_version="1.0.0", endpoint_model="qwen2-vl-7b"
        ),
        embedding=StageStamp(
            plugin="bge-m3", plugin_version="2.0.0", endpoint_model="bge-m3", dim=1024
        ),
        graph_extractor=StageStamp(plugin="llm-graph", plugin_version="0.9.0"),
    )


def test_full_stamp_round_trips() -> None:
    stamp = _full_stamp()
    assert ProducedBy.model_validate_json(stamp.model_dump_json()) == stamp


def test_each_stage_exposes_plugin_and_version() -> None:
    stamp = _full_stamp()
    assert stamp.extractor is not None
    assert stamp.extractor.plugin == "pdfplumber"
    assert stamp.extractor.plugin_version == "1.2.0"
    assert stamp.chunker is not None
    assert stamp.chunker.plugin_version == "0.4.1"
    assert stamp.graph_extractor is not None
    assert stamp.graph_extractor.plugin == "llm-graph"


def test_endpoint_model_and_dim_populated_for_embedding() -> None:
    stamp = _full_stamp()
    assert stamp.embedding is not None
    assert stamp.embedding.endpoint_model == "bge-m3"
    assert stamp.embedding.dim == 1024
    assert stamp.vision is not None
    assert stamp.vision.endpoint_model == "qwen2-vl-7b"


def test_optional_stages_default_to_none() -> None:
    stamp = ProducedBy(
        artifact_version=1,
        extractor=StageStamp(plugin="txt", plugin_version="1.0"),
    )
    assert stamp.chunker is None
    assert stamp.vision is None
    assert stamp.embedding is None
    assert stamp.graph_extractor is None


def test_stage_stamp_dim_defaults_to_none() -> None:
    stamp = StageStamp(plugin="recursive", plugin_version="1.0")
    assert stamp.endpoint_model is None
    assert stamp.dim is None


def test_stamp_is_frozen() -> None:
    stamp = _full_stamp()
    with pytest.raises(ValidationError):
        setattr(stamp, "artifact_version", 9)  # noqa: B010 — exercise frozen guard dynamically


def test_stamp_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ProducedBy.model_validate({"artifact_version": 1, "bogus": "x"})


def test_model_manifest_round_trips() -> None:
    manifest = ModelManifest(
        extractor=StageStamp(plugin="pdfplumber", plugin_version="1.2.0"),
        embedding=StageStamp(
            plugin="bge-m3", plugin_version="2.0.0", endpoint_model="bge-m3", dim=1024
        ),
        reranker=StageStamp(plugin="bge-reranker", plugin_version="2.0.0"),
    )
    assert ModelManifest.model_validate_json(manifest.model_dump_json()) == manifest
    assert manifest.chunker is None
    assert manifest.llm is None


def test_provenance_manifest_round_trips() -> None:
    manifest = ProvenanceManifest(
        stamps={
            "art-1": _full_stamp(),
            "art-2": ProducedBy(
                artifact_version=1,
                extractor=StageStamp(plugin="txt", plugin_version="1.0"),
            ),
        }
    )
    parsed = ProvenanceManifest.model_validate_json(manifest.model_dump_json())
    assert parsed == manifest
    assert parsed.stamps["art-1"] == _full_stamp()
