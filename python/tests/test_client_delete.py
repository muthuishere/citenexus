"""``CiteNexus.delete`` / ``revoke`` — first-class, surgical document revocation.

A revoke removes exactly one document and everything derived from it, leaves
every other document answerable, is idempotent, and honors the content-addressed
raw-blob reference guard (identical bytes share ONE blob — it survives while any
owner remains). The manifest entry is the commit point, written last, so an
interrupted revoke re-runs cleanly.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from citenexus import CiteNexus, DeleteResult, Hooks
from citenexus.answer.result import Decision
from citenexus.storage.manifest import EtagManifest, load_manifest
from citenexus.testing import FakeEmbedding, FakeLLM

_NDA = "The employee shall not disclose confidential information."
_LEAVE = "Employees accrue twenty days of annual leave each year."


def _rag(tmp_path: Path) -> CiteNexus:
    return CiteNexus(tmp_path, embedder=FakeEmbedding(), generator=FakeLLM())


def _raw_key(text: str) -> str:
    return f"raw/workspace=default/{hashlib.sha256(text.encode()).hexdigest()}"


def test_revoked_document_is_not_retrievable_or_citable(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_NDA, document_id="nda")
    rag.ingest(text=_LEAVE, document_id="leave")

    result = rag.delete("nda")
    assert result.status == "deleted"
    assert result.removed_eu_ids  # reported what it purged

    hits = rag.retrieve("disclose confidential information")
    assert all(h.document_id != "nda" for h in hits)

    answer = rag.ask("How many days of annual leave?")
    assert answer.evidence.decision is Decision.answered
    assert answer.sources and all(s.document != "nda" for s in answer.sources)


def test_double_delete_is_idempotent(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_NDA, document_id="nda")
    assert rag.delete("nda").status == "deleted"
    second = rag.delete("nda")
    assert second.status == "absent"
    assert second.removed_eu_ids == ()


def test_delete_unknown_document_is_absent(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_NDA, document_id="nda")
    assert rag.revoke("never-ingested").status == "absent"


def test_last_owner_raw_blob_is_removed(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_NDA, document_id="nda")
    assert rag._backend.exists(_raw_key(_NDA))
    rag.delete("nda")
    assert not rag._backend.exists(_raw_key(_NDA))


def test_shared_raw_blob_survives_while_another_owner_remains(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    # Identical bytes, different document_id → ONE shared content-addressed blob.
    rag.ingest(text=_NDA, document_id="nda-a")
    rag.ingest(text=_NDA, document_id="nda-b")
    assert rag._backend.exists(_raw_key(_NDA))

    rag.delete("nda-a")

    # The shared blob is preserved for the surviving twin.
    assert rag._backend.exists(_raw_key(_NDA))
    survivors = [r for r in rag._store.scan() if r["document_id"] == "nda-b"]
    assert survivors and rag._backend.exists(survivors[0]["raw_uri"])

    answer = rag.ask("Can the employee disclose confidential information?")
    assert answer.evidence.decision is Decision.answered
    assert all(s.document != "nda-a" for s in answer.sources)


def test_removal_order_is_resumable_manifest_entry_last(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_NDA, document_id="nda")

    # Simulate a revoke interrupted after the rows are gone but before the
    # manifest entry is forgotten — the document is still "logically present".
    rag._store.delete_document("nda")
    manifest = load_manifest(rag._backend, rag.partition, "etag_manifest.json", EtagManifest)
    assert isinstance(manifest, EtagManifest)
    assert "nda" in manifest.etags

    # Re-running completes cleanly: the entry is forgotten and nothing survives.
    assert rag.delete("nda").status == "deleted"
    reloaded = load_manifest(rag._backend, rag.partition, "etag_manifest.json", EtagManifest)
    assert isinstance(reloaded, EtagManifest)
    assert "nda" not in reloaded.etags
    assert all(h.document_id != "nda" for h in rag.retrieve("confidential"))


def test_on_delete_hook_fires(tmp_path: Path) -> None:
    seen: list[DeleteResult] = []
    rag = CiteNexus(
        tmp_path,
        embedder=FakeEmbedding(),
        generator=FakeLLM(),
        hooks=Hooks(on_delete=seen.append),
    )
    rag.ingest(text=_NDA, document_id="nda")
    rag.delete("nda")
    assert len(seen) == 1
    assert seen[0].document_id == "nda"
    assert seen[0].status == "deleted"


# -- superseded-blob leak (ADR-0008 blocking precondition) -------------------
#
# Re-ingesting a document used to overwrite the single-valued
# ``document_id -> checksum`` map without deleting the prior blob, so the
# revoke path had no way to find it: ``delete()`` reported ``status="deleted"``
# while the revoked document's earlier full text survived at
# ``raw/<P>/<old-hash>`` — unreferenced and unreachable through any API.

_NDA_V2 = "The employee shall not disclose confidential information to third parties."
_NDA_V3 = "The employee shall never disclose confidential information, full stop."


def _raw_keys(rag: CiteNexus) -> list[str]:
    """Every key under this partition's raw layer (the residue probe)."""
    return rag._backend.list_prefix("raw/workspace=default")


def test_revoke_removes_superseded_raw_blob(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_NDA, document_id="nda")
    rag.ingest(text=_NDA_V2, document_id="nda")

    assert rag.delete("nda").status == "deleted"

    # No residue ANYWHERE under raw/ — neither the current nor the prior blob.
    assert _raw_keys(rag) == []
    assert not rag._backend.exists(_raw_key(_NDA))
    assert not rag._backend.exists(_raw_key(_NDA_V2))


def test_revoke_removes_every_superseded_blob_across_many_reingests(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    for text in (_NDA, _NDA_V2, _NDA_V3):
        rag.ingest(text=text, document_id="nda")

    assert rag.delete("nda").status == "deleted"
    assert _raw_keys(rag) == []


def test_superseded_blob_owned_by_a_live_document_survives_revoke(tmp_path: Path) -> None:
    """Shared-bucket safety: never delete bytes another document still owns."""
    rag = _rag(tmp_path)
    rag.ingest(text=_NDA, document_id="nda")
    rag.ingest(text=_NDA_V2, document_id="nda")  # _NDA is now superseded for nda
    rag.ingest(text=_NDA, document_id="twin")  # ...but current for twin

    assert rag.delete("nda").status == "deleted"

    assert rag._backend.exists(_raw_key(_NDA))  # twin's bytes untouched
    assert not rag._backend.exists(_raw_key(_NDA_V2))
    answer = rag.ask("Can the employee disclose confidential information?")
    assert answer.evidence.decision is Decision.answered
    assert all(s.document == "twin" for s in answer.sources)


def test_reingest_does_not_strand_the_prior_blob(tmp_path: Path) -> None:
    """The leak is closed at the source too: a re-ingest reclaims its own past."""
    rag = _rag(tmp_path)
    rag.ingest(text=_NDA, document_id="nda")
    rag.ingest(text=_NDA_V2, document_id="nda")

    assert _raw_keys(rag) == [_raw_key(_NDA_V2)]


def test_reingest_keeps_a_prior_blob_another_document_still_owns(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_NDA, document_id="twin")
    rag.ingest(text=_NDA, document_id="nda")
    rag.ingest(text=_NDA_V2, document_id="nda")

    assert rag._backend.exists(_raw_key(_NDA))
    assert rag._backend.exists(_raw_key(_NDA_V2))
