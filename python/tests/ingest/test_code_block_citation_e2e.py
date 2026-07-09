"""Code blocks reach ask() as their own cited EUType.code_block passage.

Closes docs/CONTENT-COVERAGE-2026-07-08.md row 7: BlockKind.code and
EUType.code_block were defined and mapped (evidence/builder.py:_KIND_TO_TYPE)
but no extractor ever constructed one — dead schema. extract/md.py now
handles the "fence" (```lang) and "code_block" (4-space indented) token
types; extract/html.py now selects <pre> before decomposing it.
"""

from __future__ import annotations

from pathlib import Path

from citenexus import CiteNexus
from citenexus.answer.result import Decision
from citenexus.testing import FakeEmbedding, FakeLLM


def test_markdown_fenced_code_is_retrieved_and_cited(tmp_path: Path) -> None:
    md_path = tmp_path / "config.md"
    md_path.write_text(
        "Unrelated narrative text about the service.\n\n"
        "```python\nAPI_TIMEOUT_SECONDS = 42\n```\n"
    )
    rag = CiteNexus(tmp_path / "store", embedder=FakeEmbedding(), generator=FakeLLM())
    result = rag.ingest(md_path, document_id="config-md")
    assert result.status == "ingested"

    answer = rag.ask("What is the value of API_TIMEOUT_SECONDS?")

    assert answer.evidence.decision is Decision.answered
    assert answer.claims[0].supported
    assert "API_TIMEOUT_SECONDS = 42" in answer.sources[0].passage


def test_html_pre_code_is_retrieved_and_cited(tmp_path: Path) -> None:
    html_path = tmp_path / "config.html"
    html_path.write_text(
        "<html><body><p>Unrelated narrative text about the service.</p>"
        "<pre><code>API_TIMEOUT_SECONDS = 42</code></pre></body></html>"
    )
    rag = CiteNexus(tmp_path / "store", embedder=FakeEmbedding(), generator=FakeLLM())
    result = rag.ingest(html_path, document_id="config-html")
    assert result.status == "ingested"

    answer = rag.ask("What is the value of API_TIMEOUT_SECONDS?")

    assert answer.evidence.decision is Decision.answered
    assert answer.claims[0].supported
    assert "API_TIMEOUT_SECONDS = 42" in answer.sources[0].passage
