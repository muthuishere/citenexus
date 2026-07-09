"""A real HTML <table> reaches ask() as the cited passage — end to end.

Closes docs/CONTENT-COVERAGE-2026-07-08.md row 4b-prime for HTML: previously
<table> was outside HtmlExtractor's tag selector ([*_HEADINGS, "p"]) and its
content was dropped entirely — not flattened, not cited, gone.
"""

from __future__ import annotations

from pathlib import Path

from citenexus import CiteNexus
from citenexus.answer.result import Decision
from citenexus.testing import FakeEmbedding, FakeLLM

_HTML = """
<html><body>
<p>Unrelated narrative text, outside the table.</p>
<table>
<tr><th>Employee</th><th>NoticeDays</th></tr>
<tr><td>B. Singh</td><td>45</td></tr>
<tr><td>C. Fernandes</td><td>60</td></tr>
</table>
</body></html>
"""


def test_html_table_row_is_retrieved_and_cited_verbatim(tmp_path: Path) -> None:
    html_path = tmp_path / "notice-periods.html"
    html_path.write_text(_HTML)

    rag = CiteNexus(tmp_path / "store", embedder=FakeEmbedding(), generator=FakeLLM())
    result = rag.ingest(html_path, document_id="notice-periods-html")
    assert result.status == "ingested"

    answer = rag.ask("How many NoticeDays does B. Singh have?")

    assert answer.evidence.decision is Decision.answered
    assert answer.claims[0].supported
    assert "B. Singh" in answer.sources[0].passage
    assert "NoticeDays: 45" in answer.sources[0].passage
