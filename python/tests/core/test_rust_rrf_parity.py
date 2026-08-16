"""Python ↔ Rust RRF parity — the relocated fusion arithmetic (ADR-0006).

Reciprocal-rank fusion is the one pure, text-free computation ADR-0006 moves
into the Rust core (no tokenization, no Unicode, no key). The fused ORDERING the
core returns through the C ABI (``citenexus_rrf``) MUST be byte-identical to the
Python reference ``citenexus.retrieve.fusion.rrf_fuse`` for every shared
conformance vector. Skips when the dylib isn't built:

    task core:build   (or: cd rust && cargo build)
"""

from __future__ import annotations

import ctypes
import json
import platform
from pathlib import Path

import pytest

from citenexus.retrieve.fusion import rrf_fuse
from citenexus.retrieve.types import Candidate, RetrievalSignal

_CORE = Path(__file__).resolve().parents[3] / "rust"
_CONFORMANCE = Path(__file__).resolve().parents[3] / "conformance"
_LIB_NAME = {
    "Darwin": "libcitenexus_core.dylib",
    "Linux": "libcitenexus_core.so",
    "Windows": "citenexus_core.dll",
}[platform.system()]


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
        pytest.skip("citenexus-core not built (run: task core:build)")
    lib = ctypes.CDLL(str(path))
    lib.citenexus_rrf.restype = ctypes.c_void_p
    lib.citenexus_rrf.argtypes = [ctypes.c_char_p, ctypes.c_int64]
    lib.citenexus_free_string.argtypes = [ctypes.c_void_p]
    return lib


def rust_rrf(lib: ctypes.CDLL, lists: list[list[str]], k: int) -> list[str]:
    raw = lib.citenexus_rrf(json.dumps(lists).encode("utf-8"), k)
    try:
        payload = json.loads(ctypes.string_at(raw).decode("utf-8"))
    finally:
        lib.citenexus_free_string(raw)
    assert isinstance(payload, list), payload
    return payload


def _python_fused(lists: list[list[str]], k: int) -> list[str]:
    candidate_lists = [
        [
            Candidate(eu_id=eu_id, score=1.0 / (rank + 1), signal=RetrievalSignal.vector)
            for rank, eu_id in enumerate(one_list)
        ]
        for one_list in lists
    ]
    return [c.eu_id for c in rrf_fuse(candidate_lists, k=k)]


def test_rrf_parity_over_conformance_vectors(core: ctypes.CDLL) -> None:
    cases = json.loads((_CONFORMANCE / "cases" / "rrf.json").read_text(encoding="utf-8"))
    assert cases, "no rrf conformance cases"
    for case in cases:
        lists, k = case["lists"], case["k"]
        rust = rust_rrf(core, lists, k)
        # Core matches the committed fixture (generated FROM Python)...
        assert rust == case["fused"], case
        # ...and matches the live Python reference, byte-for-byte on ordering.
        assert rust == _python_fused(lists, k), case


def test_rrf_ffi_reports_bad_json(core: ctypes.CDLL) -> None:
    raw = core.citenexus_rrf(b"not json", 60)
    try:
        payload = json.loads(ctypes.string_at(raw).decode("utf-8"))
    finally:
        core.citenexus_free_string(raw)
    assert "error" in payload, payload
