"""The two-phase seam end-to-end through ingest (ADR-0005, §9).

`ingest()` drives emit → fulfill → assemble internally: with a vision plugin it
auto-fulfills and yields the figure EU; without one it makes no model call and
produces no figure EU. Degrade-to-text is per-request — a failed or unfulfilled
request drops only its own figure EU and never fails ingest. And the pipeline
hands the fulfiller only `PendingVisionRequest`s (the credential stays in the
plugin's transport).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import citenexus.ingest.pipeline as pipeline_mod
from citenexus.domain.partition import PartitionPath
from citenexus.domain.vision import PendingVisionRequest
from citenexus.extract.types import ExtractedBlock, ExtractedDoc, ImageRef, SourceType
from citenexus.ingest import IngestPipeline
from citenexus.storage.backend import LocalFsBackend
from citenexus.storage.paths import Layer, layer_prefix
from citenexus.testing import FakeEmbedding
from citenexus.vision import FakeVision
from citenexus.vision.fulfill import fulfill_vision_requests

PART = PartitionPath.of(("workspace", "w1"))


def _two_image_doc(k0: str, k1: str) -> ExtractedDoc:
    return ExtractedDoc(
        document_id="report",
        source_type=SourceType.pdf,
        source_uri="raw/report.pdf",
        blocks=(ExtractedBlock(order=0, kind="paragraph", text="Body.", page=1),),
        images=(
            ImageRef(image_id="img-a", page=1, bbox=(1.0, 2.0, 3.0, 4.0), blob_key=k0),
            ImageRef(image_id="img-b", page=2, bbox=(5.0, 6.0, 7.0, 8.0), blob_key=k1),
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


def _persist_two(tmp_path: Path) -> tuple[str, str]:
    backend = LocalFsBackend(tmp_path)
    prefix = layer_prefix(Layer.raw, PART)
    k0, k1 = f"{prefix}/a", f"{prefix}/b"
    backend.put_bytes(k0, b"\x89PNG a")
    backend.put_bytes(k1, b"\x89PNG b")
    return k0, k1


class _FailOneVision(FakeVision):
    def describe(self, image_region: Any) -> dict[str, Any]:
        if getattr(image_region, "image_id", "") == "img-a":
            raise RuntimeError("boom")
        return super().describe(image_region)


def test_one_failed_request_others_succeed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    k0, k1 = _persist_two(tmp_path)
    monkeypatch.setattr(pipeline_mod, "extract", lambda *a, **k: _two_image_doc(k0, k1))
    result = _pipeline(tmp_path, vision=_FailOneVision()).ingest(
        source="report.pdf", document_id="report"
    )
    assert result.status == "ingested"
    assert not any(eu_id.endswith("::img::img-a") for eu_id in result.eu_ids)  # failed → dropped
    assert any(eu_id.endswith("::img::img-b") for eu_id in result.eu_ids)  # succeeded


def test_unfulfilled_request_yields_no_figure_and_does_not_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    k0, k1 = _persist_two(tmp_path)
    monkeypatch.setattr(pipeline_mod, "extract", lambda *a, **k: _two_image_doc(k0, k1))

    # A fulfiller that leaves everything unfulfilled (returns an empty join).
    monkeypatch.setattr(pipeline_mod, "fulfill_vision_requests", lambda requests, plugin: {})
    result = _pipeline(tmp_path, vision=FakeVision()).ingest(
        source="report.pdf", document_id="report"
    )
    assert result.status == "ingested"
    assert not any("::img::" in eu_id for eu_id in result.eu_ids)


def test_ingest_passes_fulfiller_only_pending_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    k0, k1 = _persist_two(tmp_path)
    monkeypatch.setattr(pipeline_mod, "extract", lambda *a, **k: _two_image_doc(k0, k1))

    seen: dict[str, Any] = {}
    real = fulfill_vision_requests  # the genuine impl the spy delegates to

    def _spy(requests: Any, plugin: Any) -> Any:
        seen["requests"] = list(requests)
        seen["plugin"] = plugin
        return real(requests, plugin)

    monkeypatch.setattr(pipeline_mod, "fulfill_vision_requests", _spy)
    _pipeline(tmp_path, vision=FakeVision()).ingest(source="report.pdf", document_id="report")

    # The pipeline hands the fulfiller only credential-free PendingVisionRequests.
    assert seen["requests"]
    assert all(isinstance(r, PendingVisionRequest) for r in seen["requests"])
    for r in seen["requests"]:
        dumped = r.model_dump_json().lower()
        for banned in ("api_key", "authorization", "bearer", "token", "secret"):
            assert banned not in dumped
    # The plugin (credential holder) is a separate object, not one of the requests.
    assert seen["plugin"] not in seen["requests"]
