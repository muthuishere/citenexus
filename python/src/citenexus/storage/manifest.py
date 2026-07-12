"""Manifests — the JSON state that drives change-detection and rebuilds (§4c, §5).

Manifests are mutable (unlike the frozen domain value objects) and persist as JSON
under ``manifests/<P>/`` via any ``StorageBackend``. The etag manifest is the
fast-path change signal: a document whose checksum differs from the recorded one
is re-ingested.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from citenexus.storage.paths import Layer, layer_prefix

if TYPE_CHECKING:
    from citenexus.domain.partition import PartitionPath
    from citenexus.storage.backend import StorageBackend


def manifest_key(partition: PartitionPath, name: str) -> str:
    return f"{layer_prefix(Layer.manifests, partition)}/{name}"


class EtagManifest(BaseModel):
    """document_id → recorded ETag/checksum."""

    model_config = ConfigDict(extra="forbid")

    etags: dict[str, str] = {}

    def is_changed(self, document_id: str, checksum: str) -> bool:
        """True if the document is new or its checksum differs (i.e. dirty)."""
        return self.etags.get(document_id) != checksum

    def record(self, document_id: str, checksum: str) -> None:
        self.etags[document_id] = checksum

    def forget(self, document_id: str) -> None:
        """Drop a document's entry — the COMMIT POINT of a revoke.

        While the entry is present the document is considered logically present,
        so this is written last (after the derived artifacts are gone). Absent
        entry → no-op, so a re-run of an interrupted revoke is idempotent."""
        self.etags.pop(document_id, None)

    def owners_of(self, checksum: str, *, excluding: str) -> list[str]:
        """Which OTHER documents still map to ``checksum`` (the refcount for
        content-addressed raw blobs). Empty → the caller is the last owner and
        may delete the shared blob."""
        return [
            document_id
            for document_id, recorded in self.etags.items()
            if recorded == checksum and document_id != excluding
        ]


class ProcessingManifest(BaseModel):
    """content_hash → slow-path status (queued/running/done/failed/dead)."""

    model_config = ConfigDict(extra="forbid")

    status: dict[str, str] = {}

    def set_status(self, content_hash: str, value: str) -> None:
        self.status[content_hash] = value

    def get_status(self, content_hash: str) -> str | None:
        return self.status.get(content_hash)

    def clear_status(self, content_hash: str) -> None:
        """Forget a checksum's slow-path state — called on a revoke ONLY when no
        other document still owns the checksum (§1). Absent → no-op."""
        self.status.pop(content_hash, None)


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
