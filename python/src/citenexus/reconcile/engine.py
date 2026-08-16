"""Corpus↔index reconciliation and its (separate) remediation — ADR-0008.

Every other freshness mechanism in the library is change-driven: it reacts to an
ingest, an update, or a revoke. This one is state-driven — it compares the live
index against an independent statement of what belongs in it, which is the only
way to see something that got in without going through ingest at all.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from citenexus.ingest.pipeline import IngestPipeline
from citenexus.reconcile.audit import append_audit
from citenexus.reconcile.report import (
    DriftedDocument,
    ReconcileReport,
    RemediationReport,
    RemovedDocument,
)
from citenexus.storage.manifest import EtagManifest, load_manifest
from citenexus.storage.paths import partition_segment

if TYPE_CHECKING:
    from citenexus.delete import DeleteResult
    from citenexus.domain.partition import PartitionPath
    from citenexus.reconcile.manifest import CorpusManifest
    from citenexus.storage.backend import StorageBackend
    from citenexus.storage.protocols import VectorStore


class Revoker(Protocol):
    """The one deletion mechanism. Remediation goes through this, never around it."""

    def delete(self, document_id: str) -> DeleteResult: ...


def enumerate_index(
    backend: StorageBackend, partition: PartitionPath, store: VectorStore
) -> dict[str, str]:
    """``document_id -> content hash`` for everything currently indexed.

    The union of two records, because each is blind in one direction:

    * the etag manifest is the LOGICAL presence record — it is what ingest
      commits and what revoke forgets last — but an interrupted revoke or an
      out-of-band write can leave retrievable rows it never knew about;
    * the vector store is the PHYSICAL record, but a partition declared without
      ``embedding`` or ``text`` has no rows at all, so it would read as empty.

    The manifest wins on the checksum where both know a document; the scan only
    contributes documents the manifest has never heard of. That ordering also
    keeps the common path O(documents): ``scan()`` has no projection, so it
    materializes every EU row including its vector.
    """
    manifest = load_manifest(backend, partition, IngestPipeline.ETAG, EtagManifest)
    assert isinstance(manifest, EtagManifest)
    indexed: dict[str, str] = dict(manifest.etags)
    for row in store.scan():
        document_id = str(row.get("document_id", ""))
        if document_id and document_id not in indexed:
            indexed[document_id] = str(row.get("checksum", ""))
    return indexed


def reconcile(
    *,
    backend: StorageBackend,
    partition: PartitionPath,
    store: VectorStore,
    manifest: CorpusManifest,
    audit: bool = True,
) -> ReconcileReport:
    """Diff the declared corpus against the live index. Deletes nothing, ever.

    Disjointness is structural rather than asserted: one pass over the indexed
    set puts each ``document_id`` in exactly one branch, and ``missing`` is
    computed over declared ids that are by construction not in the indexed set.

    ``audit=False`` makes the call write nothing at all; the default appends one
    line to the append-only reconciliation stream and touches no other object.
    """
    indexed = enumerate_index(backend, partition, store)
    declared = manifest.current()

    orphans: list[str] = []
    drifted: list[DriftedDocument] = []
    for document_id, indexed_hash in sorted(indexed.items()):
        entry = declared.get(document_id)
        if entry is not None and entry.sha256 == indexed_hash:
            continue
        if not manifest.declares(document_id):
            # Nobody agreed this document belongs here at all → remediation is a
            # deletion.
            orphans.append(document_id)
            continue
        # A declared document is never an orphan, even when no current version
        # matches: the wrong version of an agreed document needs a re-ingest, and
        # classifying it as an orphan would route a version lag into a delete.
        superseded = manifest.version_with_hash(document_id, indexed_hash)
        drifted.append(
            DriftedDocument(
                document_id=document_id,
                indexed_sha256=indexed_hash,
                declared_sha256=entry.sha256 if entry is not None else "",
                reason="superseded_version" if superseded else "content_mismatch",
                indexed_version=superseded.version if superseded else None,
            )
        )

    missing = tuple(sorted(doc_id for doc_id in declared if doc_id not in indexed))

    report = ReconcileReport(
        partition=partition_segment(partition),
        manifest_version=manifest.manifest_version,
        checked_at=_now(),
        orphans=tuple(orphans),
        missing=missing,
        drifted=tuple(drifted),
    )
    if audit:
        append_audit(backend, partition, {"event": "reconcile", **report.model_dump(mode="json")})
    return report


def remediate(
    *,
    backend: StorageBackend,
    partition: PartitionPath,
    revoker: Revoker,
    report: ReconcileReport,
    audit: bool = True,
) -> RemediationReport:
    """Consume a report and remove its ORPHANS — nothing else, and never implicitly.

    Removal goes through ``delete()``, the existing revoke path, so a remediated
    orphan leaves nothing behind in any layer. A second deletion mechanism would
    mean a second definition of "removed", and the weaker one would quietly
    become the real one.

    ``missing`` needs an ingest and ``drifted`` needs a re-ingest; both need
    source bytes the library does not hold, so neither is touched here.

    A report can be stale by the time it is remediated. Rather than re-deriving
    the diff (which would make this a second, hidden reconcile), it relies on
    ``delete``'s idempotence and records the per-document outcome, so an
    already-gone orphan is visible as ``absent`` instead of silent.
    """
    removed = tuple(
        RemovedDocument(
            document_id=result.document_id, status=result.status, n_units=result.n_units
        )
        for result in (revoker.delete(document_id) for document_id in report.orphans)
    )
    remediation = RemediationReport(
        partition=report.partition,
        manifest_version=report.manifest_version,
        remediated_at=_now(),
        removed=removed,
    )
    if audit:
        append_audit(
            backend, partition, {"event": "remediate", **remediation.model_dump(mode="json")}
        )
    return remediation


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
