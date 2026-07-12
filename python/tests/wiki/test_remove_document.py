"""``WikiStore.remove_document`` — the per-page inverse for a revoke (§10b).

Removing a document drops its page ``.json``/``.md`` and rewrites the light
index without the stale entry, appends a ``delete`` journal line, and leaves
every surviving page in place — no LLM re-distillation over the corpus.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from citenexus.domain.partition import PartitionPath
from citenexus.storage.backend import LocalFsBackend
from citenexus.wiki import WikiStore

_PARTITION = PartitionPath.of(("org", "acme"))


class FakeLeafStore:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def scan(self, limit: int | None = None) -> list[dict[str, Any]]:
        return self.rows


def _store(tmp_path: Path) -> WikiStore:
    backend = LocalFsBackend(tmp_path)
    wiki = WikiStore(backend, _PARTITION)
    leaf = FakeLeafStore(
        [
            {"eu_id": "nda::0", "document_id": "nda", "text": "No disclosure of secrets."},
            {"eu_id": "policy::0", "document_id": "policy", "text": "Approved devices only."},
        ]
    )
    wiki.integrate_document("nda", leaf)
    wiki.integrate_document("policy", leaf)
    return wiki


def test_remove_document_drops_page_and_index_entry(tmp_path: Path) -> None:
    wiki = _store(tmp_path)
    backend = wiki._backend  # type: ignore[attr-defined]
    assert backend.exists(wiki.page_json_key("wiki:nda"))

    wiki.remove_document("nda")

    assert not backend.exists(wiki.page_json_key("wiki:nda"))
    assert not backend.exists(wiki.page_key("wiki:nda"))
    page_ids = {entry["page_id"] for entry in wiki.load_index()}
    assert page_ids == {"wiki:policy"}
    assert wiki.load_page("wiki:policy") is not None  # survivor intact


def test_remove_document_logs_a_delete_line(tmp_path: Path) -> None:
    wiki = _store(tmp_path)
    wiki.remove_document("nda")
    log = wiki._backend.get_bytes(wiki.log_key).decode("utf-8")  # type: ignore[attr-defined]
    assert "delete | nda" in log


def test_remove_absent_document_is_a_noop(tmp_path: Path) -> None:
    wiki = _store(tmp_path)
    wiki.remove_document("ghost")  # never ingested — must not raise
    assert {entry["page_id"] for entry in wiki.load_index()} == {"wiki:nda", "wiki:policy"}
