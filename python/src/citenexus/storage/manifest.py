"""Manifests — the JSON state that drives change-detection and rebuilds (§4c, §5).

Manifests are mutable (unlike the frozen domain value objects) and persist as JSON
under ``manifests/<P>/`` via any ``StorageBackend``. The etag manifest is the
fast-path change signal: a document whose checksum differs from the recorded one
is re-ingested.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from citenexus.storage.paths import Layer, layer_prefix
from citenexus.tokenize import TOKENIZER_VERSION

if TYPE_CHECKING:
    from citenexus.domain.partition import PartitionPath
    from citenexus.storage.backend import StorageBackend


def manifest_key(partition: PartitionPath, name: str) -> str:
    return f"{layer_prefix(Layer.manifests, partition)}/{name}"


class EtagManifest(BaseModel):
    """document_id → recorded ETag/checksum, plus the checksums it has retired.

    ``etags`` is single-valued, so before ``superseded`` existed a re-ingest
    silently forgot the previous checksum and the content-addressed blob it named
    became unreachable: ``delete`` could only ever remove the *current* blob, so a
    revoke reported success while the document's earlier full text stayed in the
    bucket. ``superseded`` is the missing back-reference — the only record that
    ties those bytes to the document that wrote them, and therefore the only thing
    that makes them revocable. It is a list per document (a document can be
    re-ingested many times) and it is authoritative: a checksum absent from BOTH
    maps is not this document's to delete.
    """

    model_config = ConfigDict(extra="forbid")

    etags: dict[str, str] = {}
    superseded: dict[str, list[str]] = {}

    def is_changed(self, document_id: str, checksum: str) -> bool:
        """True if the document is new or its checksum differs (i.e. dirty)."""
        return self.etags.get(document_id) != checksum

    def record(self, document_id: str, checksum: str) -> None:
        """Point ``document_id`` at ``checksum``, retiring whatever it pointed at.

        The retired checksum is remembered rather than dropped, so the blob it
        names stays revocable. Re-recording a checksum that was previously retired
        (A → B → A) un-retires it: the invariant is that ``superseded`` never
        contains the document's current checksum.
        """
        previous = self.etags.get(document_id)
        history = list(self.superseded.get(document_id, ()))
        if previous is not None and previous != checksum and previous not in history:
            history.append(previous)
        history = [retired for retired in history if retired != checksum]
        if history:
            self.superseded[document_id] = history
        else:
            self.superseded.pop(document_id, None)
        self.etags[document_id] = checksum

    def superseded_of(self, document_id: str) -> tuple[str, ...]:
        """Every checksum this document has retired, oldest first."""
        return tuple(self.superseded.get(document_id, ()))

    def clear_superseded(self, document_id: str) -> None:
        """Forget the retired checksums — called once their blobs are gone."""
        self.superseded.pop(document_id, None)

    def forget(self, document_id: str) -> None:
        """Drop a document's entry — the COMMIT POINT of a revoke.

        While the entry is present the document is considered logically present,
        so this is written last (after the derived artifacts are gone). Absent
        entry → no-op, so a re-run of an interrupted revoke is idempotent. The
        retired-checksum history goes with it: by this point its blobs are gone."""
        self.etags.pop(document_id, None)
        self.superseded.pop(document_id, None)

    def owners_of(self, checksum: str, *, excluding: str) -> list[str]:
        """Which OTHER documents CURRENTLY map to ``checksum`` (the refcount for
        content-addressed raw blobs). Empty → the caller is the last owner and
        may delete the shared blob.

        Retired (``superseded``) references deliberately do not count as owners:
        those bytes are dead for their document too, so a live owner is the only
        thing that may keep a blob alive. This is the shared-bucket guard — it is
        what stops one document's revoke from deleting another's evidence."""
        return [
            document_id
            for document_id, recorded in self.etags.items()
            if recorded == checksum and document_id != excluding
        ]


class ProcessingManifest(BaseModel):
    """DEPRECATED — superseded by ``worker.queue.DurableQueue``. Do not use.

    This model (``content_hash`` → queued/running/done/failed/dead) was never
    constructed, written, or read by anything in the library, and its documented
    job is already done by the durable queue — whose SQLite table is literally
    named ``processing_manifest`` and whose ``JobStatus`` enum is exactly this
    status set. Keeping a second, JSON-file status store would have guaranteed
    divergence: whichever one a revoke cleared would become the truth while the
    other rotted.

    It survives only as an importable name, because it appeared in
    ``citenexus.storage.__all__`` and the 0.x policy deprecates public API rather
    than removing it. Constructing it raises a ``DeprecationWarning``; it is
    scheduled for removal in 0.7. The durable queue is the slow-path status of
    record.
    """

    model_config = ConfigDict(extra="forbid")

    statuses: dict[str, str] = Field(default_factory=dict)

    def __init__(self, **data: object) -> None:
        warnings.warn(
            "ProcessingManifest is deprecated and does nothing; slow-path status "
            "lives in worker.queue.DurableQueue. Scheduled for removal in 0.7.",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(**data)


class TokenizerManifest(BaseModel):
    """The tokenizer version a partition's lexical index was built with.

    ADR-0011: a corpus tokenized under v1 keeps working, but it does not benefit
    from the Unicode tokenizer until it is re-indexed — and a non-Latin corpus
    indexed under v1 has *no* lexical terms at all. Recording the version makes
    that mismatch **detectable** rather than silent: an index whose version is
    behind the running tokenizer is stale, and ``is_stale`` says so.

    The default is deliberately ``1``: a partition with no manifest was written
    before this file existed, which means it was written by the v1 tokenizer.
    Defaulting to the current version would report every legacy index as fresh —
    the exact silent-success failure this manifest is here to prevent.
    """

    model_config = ConfigDict(extra="forbid")

    version: int = 1

    @property
    def is_stale(self) -> bool:
        """True when the index was built by a different tokenizer than the one
        now running, so its terms and the query's terms may not be comparable."""
        return self.version != TOKENIZER_VERSION


TOKENIZER = "tokenizer_manifest.json"


def record_tokenizer_version(
    backend: StorageBackend,
    partition: PartitionPath,
    name: str = TOKENIZER,
) -> None:
    """Stamp the partition with the tokenizer that just indexed it."""
    save_manifest(backend, partition, name, TokenizerManifest(version=TOKENIZER_VERSION))


def tokenizer_manifest(
    backend: StorageBackend,
    partition: PartitionPath,
    name: str = TOKENIZER,
) -> TokenizerManifest:
    """Read the partition's tokenizer stamp (``version=1`` when absent)."""
    manifest = load_manifest(backend, partition, name, TokenizerManifest)
    assert isinstance(manifest, TokenizerManifest)
    return manifest


def load_manifest(
    backend: StorageBackend,
    partition: PartitionPath,
    name: str,
    model: type[BaseModel],
) -> BaseModel:
    key = manifest_key(partition, name)
    if backend.exists(key):
        return model.model_validate(backend.get_json(key))
    return model()


def save_manifest(
    backend: StorageBackend,
    partition: PartitionPath,
    name: str,
    manifest: BaseModel,
) -> None:
    backend.put_json(manifest_key(partition, name), manifest.model_dump(mode="json"))
