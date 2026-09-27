"""Corpus↔index reconciliation — ADR-0008.

The question these tests pin is not "is this citation faithful to the index" but
"is this index derived from exactly the corpus we agreed to". So they assert the
three sets are disjoint by construction, that the pass mutates nothing, that
supersession is drift rather than orphanhood, and that remediation only ever
removes orphans — through the one existing revoke path.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from citenexus import CiteNexus, CorpusEntry, CorpusManifest
from citenexus.answer.result import Decision
from citenexus.ingest.pipeline import IngestPipeline
from citenexus.reconcile import (
    DriftedDocument,
    ReconcileReport,
    audit_key,
    enumerate_index,
    read_audit,
)
from citenexus.reconcile.audit import append_audit
from citenexus.storage.paths import Layer, layer_prefix
from citenexus.testing import FakeEmbedding, FakeLLM

_LEASE = "The tenant shall indemnify the landlord for damage to the premises."
_POLICY = "The employee shall not disclose confidential information."
_GHOST = "This memo was never part of the agreed corpus at all."
_GHOST_REVISED = "This memo was never part of the agreed corpus at all. Revised."
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


def _report(**sets: Any) -> ReconcileReport:
    """A minimal, well-formed report with only the sets under test overridden."""
    return ReconcileReport(
        partition="workspace=default",
        manifest_version="2026-08-16",
        checked_at="2026-09-27T00:00:00+00:00",
        **sets,
    )


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


def test_a_declared_entry_carries_its_source_uri_and_effective_date() -> None:
    """ADR-0008: a manifest entry names where the document came from and as of when.

    The diff reads neither field — it compares ``document_id`` and ``sha256`` — so
    both are pure caller-facing knobs: a flipped default or a dropped field would
    break every declaring caller with nothing in the suite to say so.
    """
    entry = CorpusEntry(
        document_id="policy",
        sha256=_sha(_POLICY),
        source_uri="s3://bucket/policy.pdf",
        effective_date="2026-01-01",
    )

    assert entry.source_uri == "s3://bucket/policy.pdf"
    assert entry.effective_date == "2026-01-01"
    assert entry.model_dump()["source_uri"] == "s3://bucket/policy.pdf"
    assert entry.model_dump()["effective_date"] == "2026-01-01"
    # and they survive the manifest the diff actually consumes
    assert _manifest(entry).current()["policy"].source_uri == "s3://bucket/policy.pdf"

    bare = CorpusEntry(document_id="policy", sha256=_sha(_POLICY))
    assert bare.source_uri == ""
    assert bare.effective_date is None


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


class _ScanOnlyStore:
    """Just enough VectorStore for ``enumerate_index``: ``scan()`` is its seam."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def upsert(self, rows: Any) -> None:  # pragma: no cover - fake
        ...

    def search(self, vector: Any, limit: int = 10) -> list[dict[str, Any]]:  # pragma: no cover
        return []

    def scan(self, limit: int | None = None) -> list[dict[str, Any]]:
        return self._rows

    def delete_document(self, document_id: str) -> None:  # pragma: no cover - fake
        return None


def test_rows_without_an_identity_contribute_nothing(tmp_path: Path) -> None:
    """The scan is the physical record, and it can carry half-written rows.

    A row with no ``document_id`` has neither a name to diff nor a target to
    remediate, so it is skipped; a row WITH an id and no checksum is still
    indexed — as the empty string, which is what makes it drift rather than
    disappear from the diff.
    """
    rag = _rag(tmp_path)
    rag.ingest(text=_LEASE, document_id="lease")
    store = _ScanOnlyStore(
        [
            {"eu_id": "e1", "document_id": "", "checksum": "c1"},
            {"eu_id": "e2", "checksum": "c2"},
            {"eu_id": "e3", "document_id": "z", "checksum": "c"},
            {"eu_id": "e4", "document_id": "y"},
        ]
    )

    indexed = enumerate_index(rag._backend, rag.partition, store)

    expected = {"lease": _sha(_LEASE), "z": "c", "y": ""}
    assert indexed == expected, f"half-written rows leaked into the diff: {indexed}"


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


def test_a_single_non_empty_set_is_never_clean() -> None:
    """`clean` is a three-way OR over the sets, not an AND.

    The suite pins all-empty (clean) and all-three-non-empty (not clean), so a
    rewrite to ``and`` passes both while calling a lone orphan — a document
    nobody agreed belongs in the corpus — "clean". That is the silence the
    report exists to break.
    """
    drift = DriftedDocument(
        document_id="lease", indexed_sha256="a", declared_sha256="b", reason="content_mismatch"
    )

    assert _report(orphans=("ghost",)).clean is False
    assert _report(missing=("crashed",)).clean is False
    assert _report(drifted=(drift,)).clean is False
    assert _report().clean is True


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
    assert not rag._backend.exists(f"{layer_prefix(Layer.raw, rag.partition)}/{_sha(_GHOST)}")


def test_remediating_a_reingested_orphan_leaves_no_bytes_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0008: reconcile → remediate → reconcile must not re-certify a dirty bucket.

    The orphan was ingested twice, so its FIRST checksum is retired rather than
    current. The purge that reclaims a retired blob is a separate, restartable
    step after ingest's commit point, so a crash between the two leaves exactly
    this state: the retired checksum recorded, its bytes still on disk. Only
    ``delete``'s sweep over every checksum the document ever wrote can reach
    them — remediation that came back "clean" while those bytes remained would be
    evidence of nothing.
    """
    rag = _rag(tmp_path)
    rag.ingest(text=_LEASE, document_id="lease")
    rag.ingest(text=_GHOST, document_id="ghost")
    # Crash after the ingest commit point, before the retired blob was purged.
    monkeypatch.setattr(IngestPipeline, "_purge_superseded", lambda *a, **k: None)
    rag.ingest(text=_GHOST_REVISED, document_id="ghost")
    monkeypatch.undo()

    raw = layer_prefix(Layer.raw, rag.partition)
    assert rag._backend.exists(f"{raw}/{_sha(_GHOST)}"), "the retired blob is not on disk"

    manifest = _manifest(_declared("lease", _LEASE))
    first = rag.reconcile(manifest)
    assert first.orphans == ("ghost",)

    rag.remediate(first)
    second = rag.reconcile(manifest)

    assert second.clean
    surviving = rag._backend.list_prefix(raw)
    assert [key for key in surviving if key.endswith(_sha(_GHOST))] == []
    assert [key for key in surviving if key.endswith(_sha(_GHOST_REVISED))] == []


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


@pytest.mark.parametrize(
    "record",
    [
        pytest.param(object(), id="object"),
        pytest.param({1, 2}, id="set"),
        pytest.param(b"b", id="bytes"),
    ],
)
def test_an_unserialisable_record_raises_before_anything_is_written(
    record: Any, tmp_path: Path
) -> None:
    """``append_audit`` has no fallback: ``json.dumps`` raises and nothing lands.

    The read of the existing log happens first, so the log survives the failed
    append byte-for-byte — no truncation, no ``default=str`` coercion of a record
    the stream would then be lying about.
    """
    rag = _rag(tmp_path)
    rag.ingest(text=_LEASE, document_id="lease")
    rag.reconcile(_manifest(_declared("lease", _LEASE)))
    before = rag._backend.get_bytes(audit_key(rag.partition))

    with pytest.raises(TypeError):
        append_audit(rag._backend, rag.partition, {"event": "remedy", "payload": record})

    assert rag._backend.get_bytes(audit_key(rag.partition)) == before
    assert len(read_audit(rag._backend, rag.partition)) == 1


def test_a_torn_line_makes_the_whole_log_unreadable(tmp_path: Path) -> None:
    """A crash mid-append leaves a partial line, and nothing repairs it.

    Pinned as a known failure mode rather than endorsed: one torn line raises for
    every record in the file — the intact ones before it become unreachable — and
    the next append is concatenated onto the torn bytes, so the new record is
    glued to the corrupt one instead of starting a fresh line.
    """
    rag = _rag(tmp_path)
    key = audit_key(rag.partition)
    rag._backend.put_bytes(key, b'{"event": "reconcile"}\n{"event": "reconcile", "chec')

    with pytest.raises(json.JSONDecodeError):
        read_audit(rag._backend, rag.partition)

    before = rag._backend.get_bytes(key)
    append_audit(rag._backend, rag.partition, {"event": "remedy"})
    after = rag._backend.get_bytes(key)

    assert after.startswith(before)
    assert len(after.splitlines()) == len(before.splitlines()), "the append started a new line"
    with pytest.raises(json.JSONDecodeError):
        read_audit(rag._backend, rag.partition)


def test_blank_lines_are_skipped_and_a_record_comes_back_as_written(tmp_path: Path) -> None:
    """``read_audit`` filters whitespace-only lines and validates nothing else.

    ``list[dict[str, Any]]`` is an annotation, not a check: whatever JSON type
    was appended comes back as that type. The filter is the only leniency, and
    it is what keeps a trailing newline from turning into a phantom record.
    """
    rag = _rag(tmp_path)
    key = audit_key(rag.partition)
    rag._backend.put_bytes(key, b'{"event": "reconcile"}\n\n   \n{"event": "remedy"}\n')

    assert read_audit(rag._backend, rag.partition) == [
        {"event": "reconcile"},
        {"event": "remedy"},
    ]

    append_audit(rag._backend, rag.partition, "hello")

    assert read_audit(rag._backend, rag.partition) == [
        {"event": "reconcile"},
        {"event": "remedy"},
        "hello",
    ]


# -- opt-in ------------------------------------------------------------------


def test_callers_who_never_supply_a_manifest_lose_nothing(tmp_path: Path) -> None:
    """ADR-0008: "reconciliation is opt-in and every existing flow is untouched".

    A client nobody ever handed a manifest to still ingests, retrieves and
    answers, and the one prefix reconciliation writes to stays empty — while
    ``reconcile`` keeps DEMANDING a manifest. A manifest is deliberately not
    derived from anything CiteNexus knows: one derived from the index could never
    disagree with it, and disagreement is the entire product.
    """
    rag = _rag(tmp_path)
    rag.ingest(text=_LEASE, document_id="lease")

    assert [hit.document_id for hit in rag.retrieve("indemnify the landlord")] == ["lease"]
    assert rag.ask("Who must indemnify the landlord?").evidence.decision is Decision.answered
    assert read_audit(rag._backend, rag.partition) == []
    assert rag._backend.list_prefix(layer_prefix(Layer.eval, rag.partition)) == []

    with pytest.raises(TypeError):  # a manifest is required, never inferred
        rag.reconcile()  # type: ignore[call-arg]
