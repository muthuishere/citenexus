"""Vision-into-evidence wiring in ingest (§9).

When a vision plugin is configured and a document carries images with retrievable
bytes, ingest describes each image and adds a figure Evidence Unit — searchable
in context, cited to the image's page/bbox. With NO vision plugin (or no image
bytes), ingest degrades to text-level: no error, just fewer units.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import citenexus.ingest.pipeline as pipeline_mod
from citenexus.domain.partition import PartitionPath
from citenexus.extract.types import ExtractedBlock, ExtractedDoc, ImageRef, SourceType
from citenexus.ingest import IngestPipeline
from citenexus.storage.backend import LocalFsBackend
from citenexus.storage.paths import Layer, layer_prefix
from citenexus.testing import FakeEmbedding
from citenexus.vision import FakeVision

PART = PartitionPath.of(("workspace", "w1"))


def _doc_with_image(blob_key: str) -> ExtractedDoc:
    return ExtractedDoc(
        document_id="report",
        source_type=SourceType.pdf,
        source_uri="raw/report.pdf",
        blocks=(ExtractedBlock(order=0, kind="paragraph", text="Annual revenue summary.", page=1),),
        images=(
            ImageRef(image_id="page1-img0", page=1, bbox=(1.0, 2.0, 3.0, 4.0), blob_key=blob_key),
        ),
    )


def _pipeline(tmp_path: Path, *, vision: object | None) -> IngestPipeline:
    return IngestPipeline(
        backend=LocalFsBackend(tmp_path),
        base_uri=str(tmp_path),
        partition=PART,
        embedder=FakeEmbedding(),
        signals=["embedding", "text"],
        vision=vision,  # type: ignore[arg-type]
    )


def test_vision_plugin_adds_figure_eu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Persist image bytes at a blob key the ImageRef points to.
    backend = LocalFsBackend(tmp_path)
    blob_key = f"{layer_prefix(Layer.raw, PART)}/img-blob"
    backend.put_bytes(blob_key, b"\x89PNG fake")
    monkeypatch.setattr(pipeline_mod, "extract", lambda *a, **k: _doc_with_image(blob_key))

    p = _pipeline(tmp_path, vision=FakeVision())
    result = p.ingest(source="report.pdf", document_id="report")
    # a figure EU (namespaced ::img::) rides alongside the paragraph EU
    assert any(eu_id.endswith("::img::page1-img0") for eu_id in result.eu_ids)


def test_no_vision_plugin_is_text_level_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = LocalFsBackend(tmp_path)
    blob_key = f"{layer_prefix(Layer.raw, PART)}/img-blob"
    backend.put_bytes(blob_key, b"\x89PNG fake")
    monkeypatch.setattr(pipeline_mod, "extract", lambda *a, **k: _doc_with_image(blob_key))

    p = _pipeline(tmp_path, vision=None)
    result = p.ingest(source="report.pdf", document_id="report")
    assert not any("::img::" in eu_id for eu_id in result.eu_ids)


def test_missing_image_bytes_degrades_to_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # blob_key points nowhere → no bytes → text-level, no error.
    monkeypatch.setattr(pipeline_mod, "extract", lambda *a, **k: _doc_with_image("nonexistent/key"))
    p = _pipeline(tmp_path, vision=FakeVision())
    result = p.ingest(source="report.pdf", document_id="report")
    assert result.status == "ingested"
    assert not any("::img::" in eu_id for eu_id in result.eu_ids)
