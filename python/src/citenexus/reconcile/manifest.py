"""The corpus manifest — the caller's declaration of the agreed corpus (ADR-0008).

This is the one input to CiteNexus that is deliberately **not** derived from
anything CiteNexus knows. A manifest generated from the index could never
disagree with the index, and disagreement is the entire product: the manifest is
an independent statement of what the corpus is *supposed* to be, so that a
document which entered by a path the change log never saw has something to fail
against.

It is versioned because supersession is a first-class case: declaring v2 current
and v1 not-current is how a caller says "the old version must not still be
indexed" without saying "this document does not belong here".
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator


class CorpusEntry(BaseModel):
    """One declared version of one document.

    ``sha256`` is the hash of the *file's bytes* — the same value ingest records
    as the document's checksum — which is what makes the manifest comparable to
    the index without either side trusting the other's bookkeeping.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str
    sha256: str
    version: str = "v1"
    current: bool = True
    source_uri: str = ""
    effective_date: str | None = None


class CorpusManifest(BaseModel):
    """A versioned, caller-authored statement of the agreed corpus."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_version: str
    entries: tuple[CorpusEntry, ...] = ()

    @model_validator(mode="after")
    def _one_current_version_per_document(self) -> CorpusManifest:
        """Two current versions of one document is an unanswerable declaration.

        Reconciliation would have no basis to call either the right one, so the
        ambiguity is rejected where it is authored rather than resolved silently
        where it is consumed.
        """
        seen: set[str] = set()
        for entry in self.entries:
            if not entry.current:
                continue
            if entry.document_id in seen:
                raise ValueError(
                    f"manifest declares more than one current version of {entry.document_id!r}"
                )
            seen.add(entry.document_id)
        return self

    def current(self) -> dict[str, CorpusEntry]:
        """The declared current version of every document, by ``document_id``."""
        return {entry.document_id: entry for entry in self.entries if entry.current}

    def declares(self, document_id: str) -> bool:
        """True if ANY version of the document is declared.

        Used to separate orphanhood ("nobody agreed this belongs here") from
        drift ("the wrong agreed version is indexed") — a distinction that
        decides whether remediation deletes or re-ingests.
        """
        return any(entry.document_id == document_id for entry in self.entries)

    def version_with_hash(self, document_id: str, sha256: str) -> CorpusEntry | None:
        """The declared version whose hash matches, if any (the supersession case)."""
        for entry in self.entries:
            if entry.document_id == document_id and entry.sha256 == sha256:
                return entry
        return None
