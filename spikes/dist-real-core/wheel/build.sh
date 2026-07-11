#!/usr/bin/env bash
# Build a platform wheel that bundles the prebuilt citenexus-core cdylib and
# prove it installs + imports with NO Rust toolchain.
#
# Steps: copy the freshly built cdylib into the package, build a wheel, retag it
# to this platform (it carries a native binary), install it into a throwaway
# venv that has no cargo, and call the bundled symbol.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$here/../../.." && pwd)"
libdir="$here/src/citenexus_core_probe/_lib"

# 1) platform cdylib name + wheel platform tag
uname_s="$(uname -s)"; uname_m="$(uname -m)"
case "$uname_s" in
  Darwin) libname="libcitenexus_core.dylib"
          [ "$uname_m" = "arm64" ] && plat="macosx_11_0_arm64" || plat="macosx_11_0_x86_64" ;;
  Linux)  libname="libcitenexus_core.so"
          [ "$uname_m" = "aarch64" ] && plat="manylinux2014_aarch64" || plat="manylinux2014_x86_64" ;;
  *)      echo "unsupported host $uname_s"; exit 1 ;;
esac

src_lib="$repo_root/rust/target/release/$libname"
test -f "$src_lib" || { echo "build the core first: (cd rust && cargo build --release) — missing $src_lib"; exit 1; }

# 2) stage the cdylib into the package (clean any stale copy)
rm -f "$libdir"/*.so "$libdir"/*.dylib "$libdir"/*.dll 2>/dev/null || true
cp "$src_lib" "$libdir/"
echo "staged $(basename "$src_lib") -> $libdir"

# 3) build the wheel (pure by default), then retag to a platform wheel.
#    Use a dedicated builder venv so we don't touch a PEP 668 system Python.
work="$here/.build"; rm -rf "$work"; mkdir -p "$work"
builder="$work/builder"; python3 -m venv "$builder"
"$builder/bin/pip" install --quiet --upgrade build wheel
"$builder/bin/python" -m build --wheel --outdir "$work/dist" "$here" >/dev/null
purewhl="$(ls "$work/dist"/*.whl)"
echo "built $purewhl"
"$builder/bin/python" -m wheel tags --platform-tag "$plat" --remove "$purewhl" >/dev/null
platwhl="$(ls "$work/dist"/*.whl)"
echo "retagged -> $platwhl"

# 4) install into a CLEAN venv (no cargo on PATH) and import
venv="$work/venv"; python3 -m venv "$venv"
env -i PATH="$venv/bin:/usr/bin:/bin" "$venv/bin/python" -m pip install --quiet "$platwhl"
echo "installed into throwaway venv (no cargo)"
env -i PATH="$venv/bin:/usr/bin:/bin" "$venv/bin/python" - <<'PY'
import citenexus_core_probe as c
v = c.core_version()
print(f"[wheel] pip-installed core_version()={v!r}")
import re, sys
assert re.match(r"^\d+\.\d+\.\d+", v), f"bad version {v!r}"
print("[wheel] OK — bundled cdylib loaded via ctypes, no toolchain")
PY
echo "wheel proof: PASS  ($platwhl)"
