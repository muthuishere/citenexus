"""Python loader — ctypes (stdlib, zero deps). Loads the REAL prebuilt core.

Unlike the toy spike, this binds the actual `citenexus-core` cdylib (lancedb +
arrow + tokio + fasttext inside) and calls a real exported symbol,
`citenexus_core_version()`. Proves the real engine loads with no Rust toolchain.
"""
import ctypes
import os
import re
import sys

lib_path = os.environ["CORE_LIB"]
lib = ctypes.CDLL(lib_path)

# `citenexus_core_version` returns a pointer to a 'static NUL-terminated string
# (crate version). It is NOT malloc'd, so it must NOT be freed.
lib.citenexus_core_version.restype = ctypes.c_char_p
lib.citenexus_core_version.argtypes = []

ver = lib.citenexus_core_version().decode()
print(f"[python] citenexus_core_version()={ver!r}")

expected = os.environ.get("EXPECT_CORE_VERSION", "").strip()
if not re.match(r"^\d+\.\d+\.\d+", ver):
    print(f"[python] MISMATCH: not a semver: {ver!r}", file=sys.stderr)
    sys.exit(1)
if expected and ver != expected:
    print(f"[python] MISMATCH: got {ver!r}, expected {expected!r}", file=sys.stderr)
    sys.exit(1)
print("[python] OK")
