"""Manifests: change-detection + persistence via a backend (spec §4c, §5)."""

from pathlib import Path

from citenexus.domain.partition import PartitionPath
from citenexus.storage.backend import LocalFsBackend
from citenexus.storage.manifest import (
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


def test_forget_removes_entry_and_is_idempotent() -> None:
    m = EtagManifest()
    m.record("doc1", "sha256:abc")
    m.record("doc2", "sha256:def")
    m.forget("doc1")
    assert m.is_changed("doc1", "sha256:abc")  # gone → dirty again
    assert not m.is_changed("doc2", "sha256:def")  # neighbor untouched
    m.forget("doc1")  # second forget: no error (idempotent commit point)


def test_owners_of_is_the_shared_blob_refcount() -> None:
    m = EtagManifest()
    m.record("doc1", "shaSHARED")
    m.record("doc2", "shaSHARED")  # identical bytes
    m.record("doc3", "shaUNIQUE")
    # doc1 is not the last owner of the shared checksum
    assert m.owners_of("shaSHARED", excluding="doc1") == ["doc2"]
    # doc3 is the sole owner of its checksum
    assert m.owners_of("shaUNIQUE", excluding="doc3") == []


def test_processing_manifest_clear_status_is_idempotent() -> None:
    m = ProcessingManifest()
    m.set_status("shaX", "done")
    m.clear_status("shaX")
    assert m.get_status("shaX") is None
    m.clear_status("shaX")  # absent → no error


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
