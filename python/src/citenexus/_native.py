"""ctypes seam to the prebuilt citenexus-core native library.

Distribution model (SPEC-PORTS-v1 §3.4 consume side): platform wheels ship the
matching ``libcitenexus_core.{so,dylib}`` / ``citenexus_core.dll`` bundled inside
this package under ``_lib/``. This module resolves and ``ctypes.CDLL``-loads it
with **no Rust toolchain** required at install or run time.

Resolution order:
1. ``$CITENEXUS_CORE_LIB`` — explicit absolute path override (dev / custom builds).
2. the bundled lib in ``citenexus/_lib/`` — what a platform wheel installs.
3. otherwise a clear, actionable error.

Kept dependency-free (stdlib ``ctypes`` only) so it loads even if the rest of the
``citenexus`` runtime deps are absent — the native core is an independent seam.
"""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parent / "_lib"


def _platform_libname() -> str:
    if sys.platform == "darwin":
        return "libcitenexus_core.dylib"
    if sys.platform == "win32":
        return "citenexus_core.dll"
    return "libcitenexus_core.so"


def core_lib_path() -> str:
    """Return the path to the native core, or raise a clear error."""
    override = os.environ.get("CITENEXUS_CORE_LIB")
    if override:
        if not Path(override).exists():
            raise FileNotFoundError(
                f"CITENEXUS_CORE_LIB={override!r} does not exist."
            )
        return override
    bundled = _LIB_DIR / _platform_libname()
    if bundled.exists():
        return str(bundled)
    # last resort: any lib in _lib/ (covers unexpected naming)
    if _LIB_DIR.is_dir():
        for p in sorted(_LIB_DIR.iterdir()):
            if p.suffix in (".so", ".dylib", ".dll"):
                return str(p)
    raise FileNotFoundError(
        "citenexus-core native library not found. A platform wheel bundles it "
        f"at {bundled}. Install the matching wheel (pip install citenexus), or "
        "set CITENEXUS_CORE_LIB to an absolute path to the built cdylib "
        "(cd rust && cargo build --release)."
    )


_lib_cache: ctypes.CDLL | None = None


def load_core() -> ctypes.CDLL:
    """Load (once) and return the native core handle."""
    global _lib_cache
    if _lib_cache is None:
        lib = ctypes.CDLL(core_lib_path())
        lib.citenexus_core_version.restype = ctypes.c_char_p
        lib.citenexus_core_version.argtypes = []
        _lib_cache = lib
    return _lib_cache


def core_version() -> str:
    """Return the crate version reported by the bundled native core."""
    return load_core().citenexus_core_version().decode()
