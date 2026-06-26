"""Backend seam contract, exercised hermetically on LocalFsBackend (spec §2, §5)."""

from pathlib import Path

from trustrag.storage.backend import LocalFsBackend


def test_bytes_round_trip(tmp_path: Path) -> None:
    b = LocalFsBackend(tmp_path)
    b.put_bytes("raw/doc.bin", b"hello")
    assert b.get_bytes("raw/doc.bin") == b"hello"
    assert b.exists("raw/doc.bin")
    assert not b.exists("raw/missing.bin")


def test_json_round_trip(tmp_path: Path) -> None:
    b = LocalFsBackend(tmp_path)
    b.put_json("manifests/m.json", {"a": 1, "b": ["x"]})
    assert b.get_json("manifests/m.json") == {"a": 1, "b": ["x"]}


def test_content_addressed_blob_dedups(tmp_path: Path) -> None:
    b = LocalFsBackend(tmp_path)
    d1 = b.put_blob("raw/org=acme", b"same-bytes")
    d2 = b.put_blob("raw/org=acme", b"same-bytes")
    assert d1 == d2
    assert b.list_prefix("raw/org=acme") == [f"raw/org=acme/{d1}"]


def test_delete_prefix_removes_subtree(tmp_path: Path) -> None:
    b = LocalFsBackend(tmp_path)
    b.put_bytes("raw/org=acme/a", b"1")
    b.put_bytes("raw/org=acme/b", b"2")
    b.put_bytes("raw/org=other/c", b"3")
    b.delete_prefix("raw/org=acme")
    assert b.list_prefix("raw/org=acme") == []
    assert b.list_prefix("raw/org=other") == ["raw/org=other/c"]
