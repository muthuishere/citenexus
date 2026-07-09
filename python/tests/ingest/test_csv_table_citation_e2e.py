"""CSV table rows reach ask() as the cited passage — end to end.

Closes the last open question on ``docs/CONTENT-COVERAGE-2026-07-08.md`` row
4a ("Sent/cited: partial — no retrieve/answer test cites a table EU
end-to-end"): a real CSV, ingested through the public ``CiteNexus`` client, a
numeric question that only one row answers, and the cited passage is the
rendered ``"col: value"`` table row — not paragraph prose.
"""

from __future__ import annotations

from pathlib import Path

from citenexus import CiteNexus
from citenexus.answer.result import Decision
from citenexus.testing import FakeEmbedding, FakeLLM


def test_csv_row_is_retrieved_and_cited_verbatim(tmp_path: Path) -> None:
    csv_text = (
        "Employee,YearsOfService,NoticeDays\n"
        "A. Rao,2,30\n"
        "B. Singh,5,45\n"
        "C. Fernandes,9,60\n"
    )
    csv_path = tmp_path / "notice-periods.csv"
    csv_path.write_text(csv_text)

    rag = CiteNexus(
        tmp_path / "store", embedder=FakeEmbedding(), generator=FakeLLM()
    )
    result = rag.ingest(csv_path, document_id="notice-periods")
    assert result.status == "ingested"
    # Three data rows -> three table EUs, one per row (order = row index).
    assert len(result.eu_ids) == 3

    answer = rag.ask("How many NoticeDays does B. Singh have?")

    assert answer.evidence.decision is Decision.answered
    assert answer.claims[0].supported
    assert answer.sources[0].document == "notice-periods"
    # The cited passage is the rendered table row, not paragraph prose.
    assert "B. Singh" in answer.sources[0].passage
    assert "NoticeDays: 45" in answer.sources[0].passage
