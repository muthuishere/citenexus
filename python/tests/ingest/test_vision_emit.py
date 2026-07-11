"""Emit phase — the core parses and gates, producing `PendingVisionRequest`s (§9).

The emit half of the two-phase seam runs the §9 `decide()` gate and builds a
model-ready request per vision-routed figure — the base64 ``image_url`` data URI
+ prompt + the `source_ref` (page/bbox) — WITHOUT calling any model and WITHOUT
ever putting a credential in the payload.
"""

from __future__ import annotations

import base64
from pathlib import Path

from citenexus.domain.partition import PartitionPath
from citenexus.extract.types import ExtractedBlock, ExtractedDoc, ImageRef, SourceType
from citenexus.ingest import IngestPipeline
from citenexus.storage.backend import LocalFsBackend
from citenexus.storage.paths import Layer, layer_prefix
from citenexus.testing import FakeEmbedding

PART = PartitionPath.of(("workspace", "w1"))
_PNG = b"\x89PNG\r\n\x1a\n fake image bytes"


def _pipeline(tmp_path: Path) -> IngestPipeline:
    return IngestPipeline(
        backend=LocalFsBackend(tmp_path),
        base_uri=str(tmp_path),
        partition=PART,
        embedder=FakeEmbedding(),
        signals=["embedding", "text"],
    )


def _persist_image(tmp_path: Path) -> str:
    blob_key = f"{layer_prefix(Layer.raw, PART)}/img-blob"
    LocalFsBackend(tmp_path).put_bytes(blob_key, _PNG)
    return blob_key


def _doc(
    blob_key: str, *, page_area: float | None = None, width: int = 200, height: int = 200
) -> ExtractedDoc:
    image = ImageRef(
        image_id="page4-img0",
        page=4,
        bbox=(10.0, 20.0, 110.0, 220.0),
        width=width,
        height=height,
        blob_key=blob_key,
    )
    page_map = {} if page_area is None else {"page4-img0": page_area}
    return ExtractedDoc(
        document_id="report",
        source_type=SourceType.pdf,
        source_uri="raw/report.pdf",
        blocks=(ExtractedBlock(order=0, kind="paragraph", text="Body.", page=1),),
        images=(image,),
        image_page_area=page_map,
    )


def test_emit_returns_pending_request_with_source_ref_and_data_uri(tmp_path: Path) -> None:
    blob_key = _persist_image(tmp_path)
    # 200*200 / 100_000 = 0.4 area ratio -> well over the 0.05 gate -> vision.
    doc = _doc(blob_key, page_area=100_000.0)
    requests = _pipeline(tmp_path)._emit_vision_requests(doc, doc_id="report")

    assert len(requests) == 1
    req = requests[0]
    assert req.request_id == "report::img::page4-img0"
    # SourceRef carries the figure's real page + bbox for the citation.
    assert req.source_ref.document == "report"
    assert req.source_ref.page == 4
    assert req.source_ref.bbox == (10.0, 20.0, 110.0, 220.0)
    assert req.source_ref.source_uri == "raw/report.pdf"
    # The payload is a base64 image_url data URI carrying the actual image bytes.
    assert req.payload.image_url.startswith("data:image/png;base64,")
    assert base64.b64encode(_PNG).decode() in req.payload.image_url


def test_skip_routed_image_emits_no_request(tmp_path: Path) -> None:
    blob_key = _persist_image(tmp_path)
    # 200*200 / 10_000_000 = 0.004 area ratio -> below 0.05 -> skip.
    doc = _doc(blob_key, page_area=10_000_000.0)
    requests = _pipeline(tmp_path)._emit_vision_requests(doc, doc_id="report")
    assert requests == ()


def test_payload_has_prompt_and_no_credential(tmp_path: Path) -> None:
    blob_key = _persist_image(tmp_path)
    doc = _doc(blob_key, page_area=100_000.0)
    req = _pipeline(tmp_path)._emit_vision_requests(doc, doc_id="report")[0]

    # The prompt is assembled into the payload by the core...
    assert req.payload.prompt.strip()
    assert "JSON" in req.payload.prompt
    # ...and nothing credential-shaped ever appears in the emitted request.
    blob = req.model_dump_json().lower()
    for banned in ("api_key", "authorization", "bearer", "sk-", "token"):
        assert banned not in blob
