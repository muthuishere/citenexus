"""§9 pre-filter is actually CALLED by the ingest pipeline (not just tested in
isolation) — this is capability #1's remaining gap per
``docs/CONTENT-COVERAGE-2026-07-08.md`` row 5: ``vision/prefilter.decide()``
was defined and unit-tested but never invoked from ``ingest/pipeline.py``.

Two real PDFs, same real embedded JPEG, different DISPLAY size on the page:
a "meaningful figure" (~10% of the page) must reach vision and become a
citable figure EU; a "decoration" strip (~0.4% of the page) must be routed to
``skip`` and never reach the vision plugin or the evidence store at all.
"""

from __future__ import annotations

from pathlib import Path

from citenexus import CiteNexus
from citenexus.testing import FakeEmbedding, FakeLLM
from citenexus.vision import FakeVision
from tests.extract.fixtures.pdf_builder import build_pdf_with_image


class _CountingVision(FakeVision):
    """FakeVision that records how many times it was actually called."""

    def __init__(self) -> None:
        self.calls = 0

    def describe(self, image_region: object) -> dict[str, object]:
        self.calls += 1
        return super().describe(image_region)


def test_meaningful_figure_clears_prefilter_and_is_cited(tmp_path: Path) -> None:
    pdf_path = tmp_path / "figure.pdf"
    pdf_path.write_bytes(
        build_pdf_with_image(text="Unrelated narrative.", display_size=(220, 220))
    )
    vision = _CountingVision()
    rag = CiteNexus(
        tmp_path / "store", embedder=FakeEmbedding(), generator=FakeLLM(), vision=vision
    )

    result = rag.ingest(pdf_path, document_id="figure-doc")

    assert vision.calls == 1
    assert any(eu_id.endswith("::img::page1-img0") for eu_id in result.eu_ids)


def test_decoration_sized_image_is_skipped_before_vision(tmp_path: Path) -> None:
    pdf_path = tmp_path / "decoration.pdf"
    # 40x40pt on a 612x792pt page -> area_ratio ~0.0033, well under the 0.05
    # default min_area_ratio -> the §9 pre-filter must route this to `skip`.
    pdf_path.write_bytes(
        build_pdf_with_image(text="Unrelated narrative.", display_size=(40, 40))
    )
    vision = _CountingVision()
    rag = CiteNexus(
        tmp_path / "store", embedder=FakeEmbedding(), generator=FakeLLM(), vision=vision
    )

    result = rag.ingest(pdf_path, document_id="decoration-doc")

    assert vision.calls == 0
    assert not any(eu_id.endswith("::img::page1-img0") for eu_id in result.eu_ids)
