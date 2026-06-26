"""Manifests: change-detection + persistence via a backend (spec §4c, §5)."""

from pathlib import Path

from trustrag.domain.partition import PartitionPath
from trustrag.storage.backend import LocalFsBackend
from trustrag.storage.manifest import (
    EtagManifest,
    ProcessingManifest,
    load_manifest,
    save_manifest,
)


def _partition() -> PartitionPath:
    return PartitionPath.of(("workspace", "w1"))


def test_unchanged_checksum_is_not_dirty() -> None:
    m = EtagManifest()
    m.record("doc1", "sha256:abc")
    assert not m.is_changed("doc1", "sha256:abc")


def test_new_or_changed_checksum_is_dirty() -> None:
    m = EtagManifest()
    assert m.is_changed("doc1", "sha256:abc")  # never seen
    m.record("doc1", "sha256:abc")
    assert m.is_changed("doc1", "sha256:DIFFERENT")


def test_etag_manifest_persists_via_backend(tmp_path: Path) -> None:
    backend = LocalFsBackend(tmp_path)
    part = _partition()
    m = EtagManifest()
    m.record("doc1", "sha256:abc")
    save_manifest(backend, part, "etag_manifest.json", m)
    loaded = load_manifest(backend, part, "etag_manifest.json", EtagManifest)
    assert isinstance(loaded, EtagManifest)
    assert not loaded.is_changed("doc1", "sha256:abc")


def test_processing_manifest_round_trip(tmp_path: Path) -> None:
    backend = LocalFsBackend(tmp_path)
    part = _partition()
    m = ProcessingManifest()
    m.set_status("hash1", "done")
    save_manifest(backend, part, "processing_manifest.json", m)
    loaded = load_manifest(backend, part, "processing_manifest.json", ProcessingManifest)
    assert isinstance(loaded, ProcessingManifest)
    assert loaded.get_status("hash1") == "done"
