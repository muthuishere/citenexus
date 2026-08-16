"""Manifests: change-detection + persistence via a backend (spec §4c, §5)."""

from pathlib import Path

from citenexus.domain.partition import PartitionPath
from citenexus.storage.backend import LocalFsBackend
from citenexus.storage.manifest import (
    EtagManifest,
    load_manifest,
    manifest_key,
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


def test_etag_manifest_persists_via_backend(tmp_path: Path) -> None:
    backend = LocalFsBackend(tmp_path)
    part = _partition()
    m = EtagManifest()
    m.record("doc1", "sha256:abc")
    save_manifest(backend, part, "etag_manifest.json", m)
    loaded = load_manifest(backend, part, "etag_manifest.json", EtagManifest)
    assert isinstance(loaded, EtagManifest)
    assert not loaded.is_changed("doc1", "sha256:abc")



def test_record_retires_the_previous_checksum() -> None:
    m = EtagManifest()
    m.record("doc1", "shaA")
    assert m.superseded_of("doc1") == ()
    m.record("doc1", "shaB")
    assert m.superseded_of("doc1") == ("shaA",)
    m.record("doc1", "shaC")
    assert m.superseded_of("doc1") == ("shaA", "shaB")


def test_recording_the_same_checksum_retires_nothing() -> None:
    m = EtagManifest()
    m.record("doc1", "shaA")
    m.record("doc1", "shaA")
    assert m.superseded_of("doc1") == ()


def test_returning_to_a_retired_checksum_un_retires_it() -> None:
    """A → B → A: the current checksum is never in the retired list."""
    m = EtagManifest()
    m.record("doc1", "shaA")
    m.record("doc1", "shaB")
    m.record("doc1", "shaA")
    assert m.superseded_of("doc1") == ("shaB",)


def test_retired_references_are_not_owners() -> None:
    """Only a CURRENT reference keeps a shared blob alive."""
    m = EtagManifest()
    m.record("doc1", "shaSHARED")
    m.record("doc1", "shaNEW")  # doc1 retires shaSHARED
    assert m.owners_of("shaSHARED", excluding="doc2") == []
    m.record("doc2", "shaSHARED")
    assert m.owners_of("shaSHARED", excluding="doc1") == ["doc2"]


def test_forget_drops_the_retired_history_too() -> None:
    m = EtagManifest()
    m.record("doc1", "shaA")
    m.record("doc1", "shaB")
    m.forget("doc1")
    assert m.superseded_of("doc1") == ()
    assert m.etags == {}


def test_clear_superseded_is_idempotent() -> None:
    m = EtagManifest()
    m.record("doc1", "shaA")
    m.record("doc1", "shaB")
    m.clear_superseded("doc1")
    assert m.superseded_of("doc1") == ()
    m.clear_superseded("doc1")  # absent → no error


def test_retired_checksums_survive_a_round_trip(tmp_path: Path) -> None:
    backend = LocalFsBackend(tmp_path)
    part = _partition()
    m = EtagManifest()
    m.record("doc1", "shaA")
    m.record("doc1", "shaB")
    save_manifest(backend, part, "etag_manifest.json", m)
    loaded = load_manifest(backend, part, "etag_manifest.json", EtagManifest)
    assert isinstance(loaded, EtagManifest)
    assert loaded.superseded_of("doc1") == ("shaA",)


def test_a_manifest_written_before_superseded_existed_still_loads(tmp_path: Path) -> None:
    """Forward-compat: older manifests have no ``superseded`` key at all."""
    backend = LocalFsBackend(tmp_path)
    part = _partition()
    backend.put_json(manifest_key(part, "etag_manifest.json"), {"etags": {"doc1": "shaA"}})
    loaded = load_manifest(backend, part, "etag_manifest.json", EtagManifest)
    assert isinstance(loaded, EtagManifest)
    assert loaded.superseded_of("doc1") == ()
