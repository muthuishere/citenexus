"""The reconciliation report — what the index and the declared corpus disagree about.

Three disjoint sets, and a scope statement carried as data. The scope statement
is a field rather than a docs footnote on purpose: this report's whole value is
that someone downstream will treat it as evidence, and an empty report must not
be readable as "the bucket is clean" when it only means "no document-level
disagreement".
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

SCOPE = (
    "Document-level only. This report compares declared document_ids and content "
    "hashes against the index (etag manifest unioned with the vector store). It does NOT detect "
    "byte-level residue under raw/ or knowledge/ (e.g. from a crashed ingest), nor "
    "objects written into a shared prefix by anything other than CiteNexus. An "
    "empty report means the declared corpus and the index agree at document level; "
    "it is not proof that storage is clean."
)

DriftReason = Literal["content_mismatch", "superseded_version"]


class DriftedDocument(BaseModel):
    """A declared document whose indexed bytes are not its declared current bytes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str
    indexed_sha256: str
    declared_sha256: str
    reason: DriftReason
    # Set only for ``superseded_version``: the declared version the indexed bytes
    # actually are. Naming it is the difference between "this is wrong" and
    # "this is v1 and you declared v2", which is what tells an operator whether
    # they have a stale ingest or an unknown artifact.
    indexed_version: str | None = None


class ReconcileReport(BaseModel):
    """The result of one reconciliation pass. Read-only, and self-describing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    partition: str
    manifest_version: str
    checked_at: str
    orphans: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    drifted: tuple[DriftedDocument, ...] = ()
    scope: str = SCOPE

    @property
    def clean(self) -> bool:
        """True when the index and the declared corpus agree — at document level."""
        return not (self.orphans or self.missing or self.drifted)

    @property
    def drifted_ids(self) -> tuple[str, ...]:
        return tuple(d.document_id for d in self.drifted)

    def summary(self) -> str:
        return (
            f"{self.partition} vs manifest {self.manifest_version}: "
            f"{len(self.orphans)} orphan(s), {len(self.missing)} missing, "
            f"{len(self.drifted)} drifted"
        )


class RemovedDocument(BaseModel):
    """One orphan that remediation acted on, and what the revoke actually did."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str
    status: Literal["deleted", "absent"]
    n_units: int = 0


class RemediationReport(BaseModel):
    """What remediation removed. Orphans only — never missing, never drifted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    partition: str
    manifest_version: str
    remediated_at: str
    removed: tuple[RemovedDocument, ...] = ()

    @property
    def deleted_ids(self) -> tuple[str, ...]:
        return tuple(r.document_id for r in self.removed if r.status == "deleted")

    @property
    def absent_ids(self) -> tuple[str, ...]:
        """Orphans that were already gone — a report remediated after the fact."""
        return tuple(r.document_id for r in self.removed if r.status == "absent")
