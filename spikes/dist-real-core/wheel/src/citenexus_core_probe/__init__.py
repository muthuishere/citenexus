"""Load the bundled prebuilt citenexus-core cdylib via ctypes — no toolchain.

The platform cdylib ships inside this package under ``_lib/``. At import we
locate it next to this file and ``ctypes.CDLL`` it, then expose the real
exported symbol ``citenexus_core_version()``. This is the Python side of the
prebuilt-core distribution model: a wheel that carries the matching native lib
for its platform, so ``pip install`` + ``import`` works with zero Rust.
"""
from __future__ import annotations

import ctypes
import os

_LIB_DIR = os.path.join(os.path.dirname(__file__), "_lib")


def _find_lib() -> str:
    for name in sorted(os.listdir(_LIB_DIR)):
        if name.endswith((".so", ".dylib", ".dll")):
            return os.path.join(_LIB_DIR, name)
    raise FileNotFoundError(f"no bundled cdylib (.so/.dylib/.dll) in {_LIB_DIR}")


_lib = ctypes.CDLL(_find_lib())
_lib.citenexus_core_version.restype = ctypes.c_char_p
_lib.citenexus_core_version.argtypes = []


def core_version() -> str:
    """Return the crate version reported by the bundled native core."""
    return _lib.citenexus_core_version().decode()
