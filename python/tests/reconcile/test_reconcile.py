"""Corpus↔index reconciliation — ADR-0008.

The question these tests pin is not "is this citation faithful to the index" but
"is this index derived from exactly the corpus we agreed to". So they assert the
three sets are disjoint by construction, that the pass mutates nothing, that
supersession is drift rather than orphanhood, and that remediation only ever
removes orphans — through the one existing revoke path.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from citenexus import CiteNexus, CorpusEntry, CorpusManifest
from citenexus.reconcile import ReconcileReport, enumerate_index, read_audit
from citenexus.storage.paths import Layer, layer_prefix
from citenexus.testing import FakeEmbedding, FakeLLM

_LEASE = "The tenant shall indemnify the landlord for damage to the premises."
_POLICY = "The employee shall not disclose confidential information."
_GHOST = "This memo was never part of the agreed corpus at all."
_V2 = "The tenant shall indemnify the landlord for damage, subject to clause nine."


def _rag(tmp_path: Path) -> CiteNexus:
    return CiteNexus(tmp_path, embedder=FakeEmbedding(), generator=FakeLLM())


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _manifest(*entries: CorpusEntry, version: str = "2026-08-16") -> CorpusManifest:
    return CorpusManifest(manifest_version=version, entries=entries)


def _declared(document_id: str, text: str, **kw: Any) -> CorpusEntry:
    return CorpusEntry(document_id=document_id, sha256=_sha(text), **kw)


def _assert_disjoint(report: ReconcileReport) -> None:
    orphans, missing = set(report.orphans), set(report.missing)
    drifted = set(report.drifted_ids)
    assert not (orphans & missing)
    assert not (orphans & drifted)
    assert not (missing & drifted)


def _snapshot(rag: CiteNexus) -> dict[str, Any]:
    """Every evidence layer's keys, contents and rows — the read-only probe.

    Deliberately excludes ``eval/``: that is the append-only audit stream, which
    is the one thing reconcile is allowed to write.
    """
    backend = rag._backend
    keys = [
        key
        for layer in (Layer.raw, Layer.knowledge, Layer.manifests, Layer.graph)
        for key in backend.list_prefix(layer_prefix(layer, rag.partition))
    ]
    return {
        "bytes": {key: backend.get_bytes(key) for key in keys},
        "rows": sorted(str(row["eu_id"]) for row in rag._store.scan()),
    }


# -- the manifest ------------------------------------------------------------


def test_manifest_rejects_two_current_versions_of_one_document() -> None:
    with pytest.raises(ValueError, match="more than one current version"):
        _manifest(
            _declared("lease", _LEASE, version="v1"),
            _declared("lease", _V2, version="v2"),
        )


def test_manifest_allows_one_current_plus_superseded_versions() -> None:
    manifest = _manifest(
        _declared("lease", _LEASE, version="v1", current=False),
        _declared("lease", _V2, version="v2"),
    )
    assert set(manifest.current()) == {"lease"}
    assert manifest.declares("lease")
    assert not manifest.declares("ghost")


# -- enumeration -------------------------------------------------------------


def test_enumeration_reads_document_id_to_hash(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_LEASE, document_id="lease")
    rag.ingest(text=_POLICY, document_id="policy")

    assert enumerate_index(rag._backend, rag.partition, rag._store) == {
        "lease": _sha(_LEASE),
        "policy": _sha(_POLICY),
    }


def test_enumeration_sees_rows_the_etag_manifest_does_not_know(tmp_path: Path) -> None:
    """The union is the point: a half-state must not be invisible.

    Rows without a manifest entry are what an interrupted revoke or an
    out-of-band write into a shared prefix leaves behind — and they are citable.
    """
    rag = _rag(tmp_path)
    rag.ingest(text=_LEASE, document_id="lease")
    rag.ingest(text=_GHOST, document_id="ghost")

    # Forget `ghost` logically while its rows stay physically present.
    from citenexus.storage.manifest import EtagManifest, load_manifest, save_manifest

    manifest = load_manifest(rag._backend, rag.partition, "etag_manifest.json", EtagManifest)
    assert isinstance(manifest, EtagManifest)
    manifest.forget("ghost")
    save_manifest(rag._backend, rag.partition, "etag_manifest.json", manifest)

    indexed = enumerate_index(rag._backend, rag.partition, rag._store)
    assert "ghost" in indexed

    report = rag.reconcile(_manifest(_declared("lease", _LEASE)))
    assert report.orphans == ("ghost",)


def test_enumeration_works_without_vector_rows(tmp_path: Path) -> None:
    """No `embedding`/`text` signal → no rows at all; the manifest is the record."""
    rag = CiteNexus(tmp_path, signals=["structure"], embedder=FakeEmbedding())
    rag.ingest(text=_LEASE, document_id="lease")
    assert rag._store.scan() == []

    assert enumerate_index(rag._backend, rag.partition, rag._store) == {"lease": _sha(_LEASE)}
    assert rag.reconcile(_manifest(_declared("lease", _LEASE))).clean


# -- the three sets ----------------------------------------------------------


def test_matching_corpus_reports_clean(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_LEASE, document_id="lease")
    rag.ingest(text=_POLICY, document_id="policy")

    report = rag.reconcile(_manifest(_declared("lease", _LEASE), _declared("policy", _POLICY)))

    assert report.clean
    assert (report.orphans, report.missing, report.drifted) == ((), (), ())
    assert report.partition == "workspace=default"
    assert report.manifest_version == "2026-08-16"
    _assert_disjoint(report)


def test_undeclared_document_is_an_orphan(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_LEASE, document_id="lease")
    rag.ingest(text=_GHOST, document_id="ghost")

    report = rag.reconcile(_manifest(_declared("lease", _LEASE)))

    assert report.orphans == ("ghost",)
    assert not report.missing and not report.drifted
    _assert_disjoint(report)


def test_declared_but_unindexed_document_is_missing(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_LEASE, document_id="lease")

    report = rag.reconcile(
        _manifest(_declared("lease", _LEASE), _declared("crashed", "an ingest that never landed"))
    )

    assert report.missing == ("crashed",)
    assert not report.orphans and not report.drifted
    _assert_disjoint(report)


def test_changed_source_is_drift(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_LEASE, document_id="lease")
    rag.ingest(text=_V2, document_id="lease")  # the index moved on; the manifest did not

    report = rag.reconcile(_manifest(_declared("lease", _LEASE)))

    assert report.drifted_ids == ("lease",)
    drift = report.drifted[0]
    assert drift.indexed_sha256 == _sha(_V2)
    assert drift.declared_sha256 == _sha(_LEASE)
    assert drift.reason == "content_mismatch"
    assert drift.indexed_version is None
    assert not report.orphans and not report.missing
    _assert_disjoint(report)


def test_superseded_version_is_drift_not_an_orphan(tmp_path: Path) -> None:
    """A version lag must never be routed into a deletion."""
    rag = _rag(tmp_path)
    rag.ingest(text=_LEASE, document_id="lease")  # v1 indexed

    report = rag.reconcile(
        _manifest(
            _declared("lease", _LEASE, version="v1", current=False),
            _declared("lease", _V2, version="v2"),
        )
    )

    assert report.drifted_ids == ("lease",)
    assert "lease" not in report.orphans
    drift = report.drifted[0]
    assert drift.reason == "superseded_version"
    assert drift.indexed_version == "v1"
    assert drift.declared_sha256 == _sha(_V2)
    _assert_disjoint(report)


def test_a_declared_document_indexed_at_an_unknown_hash_is_content_mismatch(
    tmp_path: Path,
) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text="bytes nobody ever declared for this document", document_id="lease")

    report = rag.reconcile(
        _manifest(
            _declared("lease", _LEASE, version="v1", current=False),
            _declared("lease", _V2, version="v2"),
        )
    )

    assert report.drifted[0].reason == "content_mismatch"
    assert report.drifted[0].indexed_version is None


def test_all_three_drift_shapes_at_once_stay_disjoint(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_LEASE, document_id="lease")
    rag.ingest(text=_V2, document_id="lease")
    rag.ingest(text=_GHOST, document_id="ghost")
    rag.ingest(text=_POLICY, document_id="policy")

    report = rag.reconcile(
        _manifest(
            _declared("lease", _LEASE),
            _declared("policy", _POLICY),
            _declared("crashed", "never landed"),
        )
    )

    assert report.orphans == ("ghost",)
    assert report.missing == ("crashed",)
    assert report.drifted_ids == ("lease",)
    assert not report.clean
    _assert_disjoint(report)


# -- read-only + idempotent --------------------------------------------------


def test_reconcile_mutates_no_evidence_layer(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_LEASE, document_id="lease")
    rag.ingest(text=_GHOST, document_id="ghost")
    before = _snapshot(rag)

    rag.reconcile(_manifest(_declared("lease", _LEASE), _declared("crashed", "nope")))

    assert _snapshot(rag) == before


def test_reconcile_with_audit_off_writes_nothing_at_all(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_LEASE, document_id="lease")
    before = sorted(rag._backend.list_prefix(""))

    rag.reconcile(_manifest(_declared("lease", _LEASE)), audit=False)

    assert sorted(rag._backend.list_prefix("")) == before
    assert read_audit(rag._backend, rag.partition) == []


def test_reconcile_is_idempotent(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_LEASE, document_id="lease")
    rag.ingest(text=_GHOST, document_id="ghost")
    manifest = _manifest(_declared("lease", _LEASE), _declared("crashed", "nope"))

    first = rag.reconcile(manifest)
    second = rag.reconcile(manifest)

    assert (first.orphans, first.missing, first.drifted) == (
        second.orphans,
        second.missing,
        second.drifted,
    )


# -- scope honesty -----------------------------------------------------------


def test_a_clean_report_still_states_its_scope(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_LEASE, document_id="lease")

    report = rag.reconcile(_manifest(_declared("lease", _LEASE)))

    assert report.clean
    assert "Document-level only" in report.scope
    assert "not proof that storage is clean" in report.scope


def test_report_does_not_see_byte_level_residue(tmp_path: Path) -> None:
    """A stray blob under raw/ is invisible to a document-keyed diff — by design.

    Pinned as a test so the limitation is a known property rather than a
    surprise the first time an auditor leans on an empty report.
    """
    rag = _rag(tmp_path)
    rag.ingest(text=_LEASE, document_id="lease")
    stray = f"{layer_prefix(Layer.raw, rag.partition)}/{'0' * 64}"
    rag._backend.put_bytes(stray, b"bytes from a crashed ingest")

    report = rag.reconcile(_manifest(_declared("lease", _LEASE)))

    assert report.clean  # and the scope field says why that is not "clean bucket"
    assert rag._backend.exists(stray)


# -- remediation -------------------------------------------------------------


def test_remediation_removes_orphans_through_the_revoke_path(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_LEASE, document_id="lease")
    rag.ingest(text=_GHOST, document_id="ghost")
    manifest = _manifest(_declared("lease", _LEASE))

    remediation = rag.remediate(rag.reconcile(manifest))

    assert remediation.deleted_ids == ("ghost",)
    assert rag.reconcile(manifest).clean
    # Revoke's guarantees come along: no rows, and no raw blob left behind.
    assert all(row["document_id"] != "ghost" for row in rag._store.scan())
    assert not rag._backend.exists(
        f"{layer_prefix(Layer.raw, rag.partition)}/{_sha(_GHOST)}"
    )


def test_remediation_leaves_missing_and_drifted_alone(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_LEASE, document_id="lease")
    rag.ingest(text=_V2, document_id="lease")
    rag.ingest(text=_GHOST, document_id="ghost")
    manifest = _manifest(_declared("lease", _LEASE), _declared("crashed", "nope"))

    before = rag.reconcile(manifest)
    rag.remediate(before)
    after = rag.reconcile(manifest)

    assert after.orphans == ()
    assert after.missing == before.missing
    assert after.drifted == before.drifted
    assert any(row["document_id"] == "lease" for row in rag._store.scan())


def test_remediating_a_stale_report_is_safe(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_LEASE, document_id="lease")
    rag.ingest(text=_GHOST, document_id="ghost")
    report = rag.reconcile(_manifest(_declared("lease", _LEASE)))
    rag.delete("ghost")  # someone got there first

    remediation = rag.remediate(report)

    assert remediation.absent_ids == ("ghost",)
    assert remediation.deleted_ids == ()
    assert any(row["document_id"] == "lease" for row in rag._store.scan())


def test_reconcile_never_deletes_even_with_orphans(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_GHOST, document_id="ghost")

    rag.reconcile(_manifest(_declared("lease", _LEASE)))

    assert any(row["document_id"] == "ghost" for row in rag._store.scan())


# -- audit stream ------------------------------------------------------------


def test_each_reconciliation_is_appended(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_LEASE, document_id="lease")
    manifest = _manifest(_declared("lease", _LEASE))

    rag.reconcile(manifest)
    first = read_audit(rag._backend, rag.partition)
    rag.reconcile(manifest)
    records = read_audit(rag._backend, rag.partition)

    assert len(records) == 2
    assert records[0] == first[0]  # the earlier record is never rewritten
    assert all(r["event"] == "reconcile" for r in records)
    assert records[0]["manifest_version"] == "2026-08-16"
    assert "Document-level only" in records[0]["scope"]


def test_remediation_is_recorded(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_LEASE, document_id="lease")
    rag.ingest(text=_GHOST, document_id="ghost")

    rag.remediate(rag.reconcile(_manifest(_declared("lease", _LEASE))))

    records = read_audit(rag._backend, rag.partition)
    assert [r["event"] for r in records] == ["reconcile", "remediate"]
    assert records[1]["removed"][0]["document_id"] == "ghost"
    assert records[1]["removed"][0]["status"] == "deleted"


def test_audit_lives_outside_every_evidence_layer(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text=_LEASE, document_id="lease")
    rag.reconcile(_manifest(_declared("lease", _LEASE)))

    from citenexus.reconcile import audit_key

    assert audit_key(rag.partition).startswith("eval/")
    assert rag._backend.exists(audit_key(rag.partition))
