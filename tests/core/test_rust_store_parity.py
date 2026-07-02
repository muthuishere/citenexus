"""Python ↔ Rust Lance-store interop — the cross-language bucket promise.

SPEC-PORTS-v1 §3.4: one Lance implementation, one on-disk format. This test
has RUST write a Lance table through the real C ABI (ctypes on the built
cdylib), then has PYTHON's ``LanceVectorStore`` open the SAME URI and
scan/search it — the rows must match. Skips when the dylib isn't built:

    task core:build   (or: cd core && cargo build)
"""

from __future__ import annotations

import ctypes
import json
import platform
from pathlib import Path
from typing import Any

import pytest

from trustrag.storage.lance_store import LanceVectorStore

_CORE = Path(__file__).resolve().parents[2] / "core"
_LIB_NAME = {
    "Darwin": "libtrustrag_core.dylib",
    "Linux": "libtrustrag_core.so",
    "Windows": "trustrag_core.dll",
}[platform.system()]

ROWS = [
    {
        "eu_id": "doc::0",
        "vector": [1.0, 0.0, 0.0, 0.0],
        "text": "Employees accrue leave.",
        "document_id": "doc",
        "language": "en",
        "page": 1,
        "checksum": "c0",
        "raw_uri": "s3://bucket/raw/doc",
    },
    {
        "eu_id": "doc::1",
        "vector": [0.0, 1.0, 0.0, 0.0],
        "text": "Remote work needs approval.",
        "document_id": "doc",
        "language": "en",
        "page": 2,
        "checksum": "c1",
        "raw_uri": "s3://bucket/raw/doc",
    },
    {
        "eu_id": "doc::2",
        "vector": [0.0, 0.0, 1.0, 0.0],
        "text": "Les employés accumulent des congés.",
        "document_id": "doc",
        "language": "fr",
        "page": 3,
        "checksum": "c2",
        "raw_uri": "s3://bucket/raw/doc",
    },
]


def _dylib() -> Path | None:
    for profile in ("debug", "release"):
        candidate = _CORE / "target" / profile / _LIB_NAME
        if candidate.exists():
            return candidate
    return None


@pytest.fixture(scope="module")
def core() -> ctypes.CDLL:
    path = _dylib()
    if path is None:
        pytest.skip("trustrag-core not built (run: task core:build)")
    lib = ctypes.CDLL(str(path))
    lib.trustrag_store_open.restype = ctypes.c_void_p
    lib.trustrag_store_open.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    lib.trustrag_store_upsert.restype = ctypes.c_void_p
    lib.trustrag_store_upsert.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.trustrag_store_search.restype = ctypes.c_void_p
    lib.trustrag_store_search.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_size_t,
    ]
    lib.trustrag_store_scan.restype = ctypes.c_void_p
    lib.trustrag_store_scan.argtypes = [ctypes.c_void_p, ctypes.c_int64]
    lib.trustrag_store_drop.restype = ctypes.c_void_p
    lib.trustrag_store_drop.argtypes = [ctypes.c_void_p]
    lib.trustrag_store_close.restype = None
    lib.trustrag_store_close.argtypes = [ctypes.c_void_p]
    lib.trustrag_free_string.argtypes = [ctypes.c_void_p]
    return lib


def take_json(lib: ctypes.CDLL, raw: int | None) -> Any:
    assert raw is not None
    try:
        payload = json.loads(ctypes.string_at(raw).decode("utf-8"))
    finally:
        lib.trustrag_free_string(raw)
    if isinstance(payload, dict) and "error" in payload:
        pytest.fail(f"rust error: {payload['error']}")
    return payload


def comparable(row: dict[str, Any]) -> dict[str, Any]:
    """A row with float noise normalized (vectors stored as f32 on both sides)."""
    out = {k: v for k, v in row.items() if k not in ("vector", "_distance")}
    out["vector"] = [round(float(x), 5) for x in row["vector"]]
    return out


@pytest.fixture()
def rust_written_store(core: ctypes.CDLL, tmp_path: Path) -> tuple[ctypes.CDLL, int, str]:
    """A leaf database whose rows were written by RUST through the C ABI."""
    uri = str(tmp_path / "leaf")
    handle = core.trustrag_store_open(uri.encode(), b"{}")
    assert handle, "trustrag_store_open returned null"
    ok = take_json(core, core.trustrag_store_upsert(handle, json.dumps(ROWS).encode()))
    assert ok == {"ok": True}
    return core, handle, uri


def test_python_scans_what_rust_wrote(
    rust_written_store: tuple[ctypes.CDLL, int, str],
) -> None:
    core, handle, uri = rust_written_store
    try:
        python_rows = LanceVectorStore(uri).scan()
        assert sorted(map(comparable, python_rows), key=lambda r: r["eu_id"]) == [
            comparable(r) for r in ROWS
        ]
    finally:
        core.trustrag_store_close(handle)


def test_python_searches_what_rust_wrote(
    rust_written_store: tuple[ctypes.CDLL, int, str],
) -> None:
    core, handle, uri = rust_written_store
    try:
        hits = LanceVectorStore(uri).search([0.0, 0.9, 0.1, 0.0], limit=2)
        assert len(hits) == 2
        assert hits[0]["eu_id"] == "doc::1"
        assert hits[0]["_distance"] <= hits[1]["_distance"]

        # Rust searching the same store agrees with Python, row for row.
        rust_hits = take_json(
            core,
            core.trustrag_store_search(handle, json.dumps([0.0, 0.9, 0.1, 0.0]).encode(), 2),
        )
        assert [h["eu_id"] for h in rust_hits] == [h["eu_id"] for h in hits]
        assert [comparable(h) for h in rust_hits] == [comparable(h) for h in hits]
        for rust_hit, py_hit in zip(rust_hits, hits, strict=True):
            assert rust_hit["_distance"] == pytest.approx(py_hit["_distance"])
    finally:
        core.trustrag_store_close(handle)


def test_rust_upsert_is_idempotent_when_python_reads(
    rust_written_store: tuple[ctypes.CDLL, int, str],
) -> None:
    core, handle, uri = rust_written_store
    try:
        updated = [dict(r) for r in ROWS]
        updated[1]["text"] = "Remote work is pre-approved."
        ok = take_json(core, core.trustrag_store_upsert(handle, json.dumps(updated).encode()))
        assert ok == {"ok": True}

        python_rows = LanceVectorStore(uri).scan()
        assert len(python_rows) == 3  # merge-insert, not append
        by_id = {r["eu_id"]: r for r in python_rows}
        assert by_id["doc::1"]["text"] == "Remote work is pre-approved."
    finally:
        core.trustrag_store_close(handle)


def test_rust_drop_leaves_python_an_empty_leaf(
    rust_written_store: tuple[ctypes.CDLL, int, str],
) -> None:
    core, handle, uri = rust_written_store
    try:
        ok = take_json(core, core.trustrag_store_drop(handle))
        assert ok == {"ok": True}
        assert LanceVectorStore(uri).scan() == []
        assert LanceVectorStore(uri).search([1.0, 0.0, 0.0, 0.0]) == []
    finally:
        core.trustrag_store_close(handle)


def test_rust_scans_what_python_wrote(core: ctypes.CDLL, tmp_path: Path) -> None:
    """The reverse direction: PYTHON writes, RUST reads the same URI."""
    uri = str(tmp_path / "leaf-py")
    LanceVectorStore(uri).upsert(ROWS)

    handle = core.trustrag_store_open(uri.encode(), b"{}")
    assert handle, "trustrag_store_open returned null"
    try:
        rust_rows = take_json(core, core.trustrag_store_scan(handle, -1))
        assert sorted(map(comparable, rust_rows), key=lambda r: r["eu_id"]) == [
            comparable(r) for r in ROWS
        ]
    finally:
        core.trustrag_store_close(handle)
