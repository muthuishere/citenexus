"""WikiStore — distilled builds, the browsable Markdown tree, and lint (§10b).

pages.json stays the machine manifest the retriever reads; alongside it the
store writes a human-browsable tree (wiki/index.md + wiki/pages/<page>.md).
With a distiller the pages are LLM-distilled; a failing distiller degrades to
the deterministic per-document pages. lint() reports typed maintenance issues
without any model.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from citenexus.domain.partition import PartitionPath
from citenexus.storage.backend import LocalFsBackend
from citenexus.wiki import WikiPage, WikiStore
from citenexus.wiki.distill import PagesInput

_PARTITION = PartitionPath.of(("org", "acme"))


class FakeLeafStore:
    """A minimal VectorStore: only scan() matters to the wiki layer."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def upsert(self, rows: Any) -> None:
        raise NotImplementedError

    def search(self, vector: Any, limit: int = 10) -> list[dict[str, Any]]:
        raise NotImplementedError

    def scan(self, limit: int | None = None) -> list[dict[str, Any]]:
        return self.rows


def _rows() -> list[dict[str, Any]]:
    return [
        {"eu_id": "nda::0", "document_id": "nda", "text": "No disclosure of secrets."},
        {"eu_id": "policy::0", "document_id": "policy", "text": "Approved devices only."},
    ]


_DISTILLED = (
    WikiPage(
        page_id="confidentiality",
        title="Confidentiality",
        summary="Both documents restrict confidential information.",
        keywords=("confidential",),
        eu_refs=("nda::0", "policy::0"),
        links=("doc-nda",),
    ),
    WikiPage(
        page_id="doc-nda",
        title="NDA",
        summary="Non-disclosure agreement.",
        keywords=("nda",),
        eu_refs=("nda::0",),
        links=("confidentiality",),
    ),
)


class FakeDistiller:
    def __init__(self, pages: tuple[WikiPage, ...] | None) -> None:
        self.pages = pages
        self.calls: list[PagesInput] = []

    def distill(self, pages_input: PagesInput) -> tuple[WikiPage, ...] | None:
        self.calls.append(pages_input)
        return self.pages


def test_distiller_pages_become_the_manifest(tmp_path: Path) -> None:
    backend = LocalFsBackend(tmp_path)
    distiller = FakeDistiller(_DISTILLED)
    store = WikiStore(backend, _PARTITION, distiller=distiller)
    pages = store.build_from_store(FakeLeafStore(_rows()))
    assert pages == _DISTILLED
    assert store.load() == _DISTILLED
    # The distiller saw the corpus grouped by document.
    assert distiller.calls[0]["nda"] == (("nda::0", "No disclosure of secrets."),)


def test_failing_distiller_degrades_to_deterministic_pages(tmp_path: Path) -> None:
    backend = LocalFsBackend(tmp_path)
    store = WikiStore(backend, _PARTITION, distiller=FakeDistiller(None))
    pages = store.build_from_store(FakeLeafStore(_rows()))
    assert [page.page_id for page in pages] == ["wiki:nda", "wiki:policy"]
    assert pages[0].links == ()


def test_markdown_tree_written_alongside_manifest(tmp_path: Path) -> None:
    backend = LocalFsBackend(tmp_path)
    store = WikiStore(backend, _PARTITION, distiller=FakeDistiller(_DISTILLED))
    store.build_from_store(FakeLeafStore(_rows()))

    index = backend.get_bytes(store.index_key).decode("utf-8")
    assert "# Wiki Index" in index
    assert "[Confidentiality](pages/confidentiality.md)" in index
    assert "[NDA](pages/doc-nda.md)" in index

    page_md = backend.get_bytes(store.page_key("confidentiality")).decode("utf-8")
    assert "# Confidentiality" in page_md
    assert "Both documents restrict confidential information." in page_md
    assert "[[doc-nda]]" in page_md
    assert "- nda::0" in page_md
    assert "- policy::0" in page_md


def test_rebuild_clears_stale_markdown_pages(tmp_path: Path) -> None:
    backend = LocalFsBackend(tmp_path)
    store = WikiStore(backend, _PARTITION, distiller=FakeDistiller(_DISTILLED))
    store.build_from_store(FakeLeafStore(_rows()))
    assert backend.exists(store.page_key("doc-nda"))

    smaller = WikiStore(backend, _PARTITION, distiller=FakeDistiller(_DISTILLED[:1]))
    smaller.build_from_store(FakeLeafStore(_rows()))
    assert not backend.exists(store.page_key("doc-nda"))
    assert backend.exists(store.index_json_key)  # the light index survives the sweep


def test_old_pages_json_without_links_still_loads(tmp_path: Path) -> None:
    backend = LocalFsBackend(tmp_path)
    store = WikiStore(backend, _PARTITION)
    backend.put_json(
        store.key,
        [
            {
                "page_id": "wiki:nda",
                "title": "nda",
                "summary": "No disclosure.",
                "keywords": ["disclosure"],
                "eu_refs": ["nda::0"],
            }
        ],
    )
    pages = store.load()
    assert pages[0].page_id == "wiki:nda"
    assert pages[0].links == ()


def test_lint_reports_each_issue_kind(tmp_path: Path) -> None:
    backend = LocalFsBackend(tmp_path)
    store = WikiStore(backend, _PARTITION)
    store.save(
        (
            WikiPage(
                page_id="a",
                title="A",
                summary="",
                keywords=(),
                eu_refs=("nda::0", "gone::7"),
                links=("missing-page",),
            ),
            WikiPage(page_id="b", title="B", summary="", keywords=(), eu_refs=()),
        )
    )
    issues = store.lint(FakeLeafStore(_rows()))
    by_kind = {(issue.kind, issue.page_id, issue.ref) for issue in issues}
    assert by_kind == {
        ("dangling_link", "a", "missing-page"),
        ("missing_eu", "a", "gone::7"),
        ("orphan_page", "b", ""),
    }


def test_lint_clean_wiki_has_no_issues(tmp_path: Path) -> None:
    backend = LocalFsBackend(tmp_path)
    store = WikiStore(backend, _PARTITION)
    store.save(_DISTILLED)
    assert store.lint(FakeLeafStore(_rows())) == []
