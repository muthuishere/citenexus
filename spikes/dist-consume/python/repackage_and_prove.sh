#!/usr/bin/env bash
# Tier-2 REPACKAGE + proof for Python (darwin-arm64), the mochallama pattern:
# take the pure `citenexus` wheel, inject the prebuilt platform cdylib into
# citenexus/_lib/, retag to a platform wheel, then pip-install into a FRESH venv
# with NO Rust toolchain and load the core through the shipping ctypes seam
# (citenexus._native). No rebuild of the core.
#
# The cdylib source is, in order: $CORE_LIB, else the on-disk release build, else
# a SHA256-verified download of the native-libs Release asset (true Tier-2).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$here/../../.." && pwd)"
pkg_dir="$repo_root/python"
work="$here/.build"; rm -rf "$work"; mkdir -p "$work"

# platform facts (this proof targets the host = darwin-arm64)
case "$(uname -s)/$(uname -m)" in
  Darwin/arm64) libname="libcitenexus_core.dylib"; plat="macosx_11_0_arm64"; asset="citenexus_core-darwin-arm64.dylib" ;;
  Linux/x86_64) libname="libcitenexus_core.so";    plat="manylinux2014_x86_64"; asset="citenexus_core-linux-amd64.so" ;;
  Linux/aarch64)libname="libcitenexus_core.so";    plat="manylinux2014_aarch64"; asset="citenexus_core-linux-arm64.so" ;;
  *) echo "unsupported host"; exit 1 ;;
esac
core_ver="0.7.0"  # native-libs release tag to pull from

# 0) obtain the cdylib
src_lib="$work/$libname"
if [ -n "${CORE_LIB:-}" ] && [ -f "${CORE_LIB:-}" ]; then
  cp "$CORE_LIB" "$src_lib"; echo "cdylib: from \$CORE_LIB"
elif [ -f "$repo_root/rust/target/release/$libname" ]; then
  cp "$repo_root/rust/target/release/$libname" "$src_lib"; echo "cdylib: from local release build"
else
  echo "cdylib: downloading + SHA256-verifying Release asset $asset (v$core_ver)"
  base="https://github.com/muthuishere/citenexus/releases/download/v$core_ver"
  curl -fsSL "$base/$asset" -o "$src_lib"
  curl -fsSL "$base/$asset.sha256" -o "$work/asset.sha256"
  want="$(awk '{print $1; exit}' "$work/asset.sha256")"
  got="$(shasum -a 256 "$src_lib" | awk '{print $1}')"
  [ "$got" = "$want" ] || { echo "SHA256 mismatch: got $got want $want"; exit 1; }
  echo "SHA256 OK ($got)"
fi

# 1) build the pure wheel with a dedicated builder venv (PEP 668 safe)
builder="$work/builder"; python3 -m venv "$builder"
"$builder/bin/pip" install --quiet --upgrade build wheel
"$builder/bin/python" -m build --wheel --outdir "$work/dist" "$pkg_dir" >/dev/null
purewhl="$(ls "$work/dist"/*.whl)"; echo "built pure wheel: $(basename "$purewhl")"

# 2) unpack, inject the cdylib, mark as platlib, retag
unpk="$work/unpacked"; mkdir -p "$unpk"
"$builder/bin/python" -m wheel unpack "$purewhl" -d "$unpk" >/dev/null
whldir="$(ls -d "$unpk"/*/)"
mkdir -p "$whldir/citenexus/_lib"
cp "$src_lib" "$whldir/citenexus/_lib/$libname"
whlmeta="$(ls "$whldir"/*.dist-info/WHEEL)"
# platform wheel: not pure, correct tag
python3 - "$whlmeta" "$plat" <<'PY'
import sys
meta, plat = sys.argv[1], sys.argv[2]
lines=[]
for ln in open(meta):
    if ln.startswith("Root-Is-Purelib:"): ln=f"Root-Is-Purelib: false\n"
    elif ln.startswith("Tag:"): ln=f"Tag: py3-none-{plat}\n"
    lines.append(ln)
open(meta,"w").writelines(lines)
print("patched WHEEL ->", "".join(l for l in lines if l.startswith(("Tag","Root"))).strip())
PY
mkdir -p "$work/dist_plat"
"$builder/bin/python" -m wheel pack "$whldir" -d "$work/dist_plat" >/dev/null
platwhl="$(ls "$work/dist_plat"/*.whl)"; echo "repackaged platform wheel: $(basename "$platwhl")"
echo "  bundles: $(unzip -l "$platwhl" | grep -o 'citenexus/_lib/[^ ]*')"

# 3) PROVE: fresh venv, NO cargo on PATH, install --no-deps, load via _native
venv="$work/venv"; python3 -m venv "$venv"
env -i PATH="$venv/bin:/usr/bin:/bin" "$venv/bin/pip" install --quiet --no-deps "$platwhl"
echo "pip install --no-deps OK (no rust toolchain, no C compiler used)"
env -i PATH="$venv/bin:/usr/bin:/bin" CITENEXUS_CORE_LIB="" "$venv/bin/python" - <<'PY'
import importlib.util, sysconfig, pathlib, re
# load citenexus._native WITHOUT importing the heavy citenexus package (its
# runtime deps are intentionally not installed here — the native seam is
# independent). This is exactly what the shipping module does at runtime.
site = pathlib.Path(sysconfig.get_paths()["purelib"])
spec = importlib.util.spec_from_file_location("citenexus._native", site/"citenexus"/"_native.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
v = m.core_version()
print(f"[python] citenexus._native.core_version()={v!r}  (loaded from {m.core_lib_path()})")
assert re.match(r"^\d+\.\d+\.\d+", v), f"bad version {v!r}"
assert "site-packages" in m.core_lib_path(), "did not load the BUNDLED lib"
print("[python] OK — platform wheel bundled the cdylib; ctypes loaded it from the package dir, no toolchain")
PY
echo "python wheel proof: PASS  ($(basename "$platwhl"))"
