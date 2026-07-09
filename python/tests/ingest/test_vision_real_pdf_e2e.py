"""Real PDF image → vision description → grounded, cited answer (end to end).

Proves the full loop the companion spec (SPEC-vision-image-description-v1)
fixes: a real ``PdfExtractor.extract()`` pulls real, Pillow-decodable image
bytes out of an actual embedded JPEG (not injected into an ``ImageRef``
directly); ``IngestPipeline`` persists them via the storage backend and stamps
``blob_key``; ``describe_image`` (via ``FakeVision``, the repo's deterministic
vision double — never live network here) turns them into a figure Evidence
Unit; and ``CiteNexus.ask()`` retrieves + cites it like any other passage.
"""

from __future__ import annotations

from pathlib import Path

from citenexus import CiteNexus
from citenexus.answer.result import Decision
from citenexus.testing import FakeEmbedding, FakeLLM
from citenexus.vision import FakeVision
from tests.extract.fixtures.pdf_builder import build_pdf_with_image


def test_real_pdf_image_is_described_retrieved_and_cited(tmp_path: Path) -> None:
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(
        build_pdf_with_image(text="Quarterly narrative text, unrelated to the chart.")
    )

    rag = CiteNexus(
        tmp_path / "store",
        embedder=FakeEmbedding(),
        generator=FakeLLM(),
        vision=FakeVision(),
    )

    result = rag.ingest(str(pdf_path), document_id="report")
    assert result.status == "ingested"
    # The figure EU (real bytes -> described -> shaped) rode along with the
    # paragraph EU — proves extraction actually produced usable bytes, the
    # pipeline persisted + stamped blob_key, and describe_image ran.
    assert any(eu_id.endswith("::img::page1-img0") for eu_id in result.eu_ids)

    # FakeVision's deterministic description for this image_id includes
    # "axis", "line", "legend" and the OCR line "label: page1-img0" — ask a
    # question that only the figure's description can ground.
    answer = rag.ask("What objects — axis, line, legend — appear in the figure?")

    assert answer.evidence.decision is Decision.answered
    assert answer.claims[0].supported
    assert answer.sources[0].document == "report"
    # Cited passage is the vision-generated figure description, not the
    # unrelated page text.
    assert "axis" in answer.sources[0].passage
    assert "legend" in answer.sources[0].passage
    assert "Figure page1-img0" in answer.sources[0].passage
    # Citation lands on the image's real page (bbox is not carried through
    # retrieve.Candidate/SourceRef today — untouched, out of scope per the spec).
    assert answer.sources[0].page == 1
