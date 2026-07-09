"""A REAL ruled table in a PDF (vector lines, detected by pdfplumber's table
finder — not text-alignment guessing) reaches ask() as the cited passage.

Closes docs/CONTENT-COVERAGE-2026-07-08.md row 4b for PDF: previously a table
in a PDF silently flattened into the page's paragraph text with no row
structure; extract/pdf.py now also emits one BlockKind.table block per row
(rendered "col: value", same convention as extract/csv.py) so it becomes its
own citable EUType.table Evidence Unit.
"""

from __future__ import annotations

from pathlib import Path

from citenexus import CiteNexus
from citenexus.answer.result import Decision
from citenexus.testing import FakeEmbedding, FakeLLM
from tests.extract.fixtures.pdf_table_builder import build_pdf_with_table


def test_pdf_table_row_is_retrieved_and_cited_verbatim(tmp_path: Path) -> None:
    pdf_bytes = build_pdf_with_table(
        rows=[
            ["Employee", "NoticeDays"],
            ["B. Singh", "45"],
            ["C. Fernandes", "60"],
        ],
        col_x=[50, 150, 250],
        row_y=[700, 680, 660, 640],
        text="Unrelated narrative text, outside the table.",
    )
    pdf_path = tmp_path / "notice-periods.pdf"
    pdf_path.write_bytes(pdf_bytes)

    rag = CiteNexus(tmp_path / "store", embedder=FakeEmbedding(), generator=FakeLLM())
    result = rag.ingest(pdf_path, document_id="notice-periods-pdf")
    assert result.status == "ingested"
    # 1 paragraph block (unrelated text) + 2 table-row blocks = 3 EUs.
    assert len(result.eu_ids) == 3

    answer = rag.ask("How many NoticeDays does B. Singh have?")

    assert answer.evidence.decision is Decision.answered
    assert answer.claims[0].supported
    assert answer.sources[0].document == "notice-periods-pdf"
    # The cited passage is the rendered table row, not the unrelated page text.
    assert "B. Singh" in answer.sources[0].passage
    assert "NoticeDays: 45" in answer.sources[0].passage
    assert answer.sources[0].page == 1
