"""Corpus↔index reconciliation — is the index derived from the agreed corpus?

See ADR-0008. The manifest is caller-authored, the diff is read-only, and
remediation is a separate call that removes orphans through the existing revoke
path.
"""

from citenexus.reconcile.audit import audit_key, read_audit
from citenexus.reconcile.engine import enumerate_index, reconcile, remediate
from citenexus.reconcile.manifest import CorpusEntry, CorpusManifest
from citenexus.reconcile.report import (
    DriftedDocument,
    ReconcileReport,
    RemediationReport,
    RemovedDocument,
)

__all__ = [
    "CorpusEntry",
    "CorpusManifest",
    "DriftedDocument",
    "ReconcileReport",
    "RemediationReport",
    "RemovedDocument",
    "audit_key",
    "enumerate_index",
    "read_audit",
    "reconcile",
    "remediate",
]
