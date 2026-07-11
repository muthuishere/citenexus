#!/usr/bin/env bash
# TS/JS CONSUME proof (host-generic): generate the platform package for THIS
# host, stage the cdylib into it, `npm pack` the platform + main packages,
# install BOTH into a throwaway project, and koffi-load the core through the
# main package's os/cpu resolver. No Rust toolchain. Mirrors what
# `npm install @scope/citenexus-core` does when the registry serves the
# os/cpu-matched optionalDependency for the host.
#
# platform-darwin-arm64/package.json is the committed canonical example; this
# script generates the equivalent for whatever platform CI runs on.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$here/../../.." && pwd)"
work="$here/.build"; rm -rf "$work"; mkdir -p "$work"
core_ver="0.7.0"

case "$(uname -s)/$(uname -m)" in
  Darwin/arm64)  suffix="darwin-arm64"; os="darwin"; cpu="arm64"; libname="libcitenexus_core.dylib"; asset="citenexus_core-darwin-arm64.dylib" ;;
  Linux/x86_64)  suffix="linux-x64";    os="linux";  cpu="x64";   libname="libcitenexus_core.so";    asset="citenexus_core-linux-amd64.so" ;;
  Linux/aarch64) suffix="linux-arm64";  os="linux";  cpu="arm64"; libname="libcitenexus_core.so";    asset="citenexus_core-linux-arm64.so" ;;
  *) echo "unsupported host"; exit 1 ;;
esac
scope="@muthuishere"; base="citenexus-core-dist-spike"
platdir="$work/platform-$suffix"; mkdir -p "$platdir"

# obtain cdylib: $CORE_LIB, else local release build, else verified Release asset
if [ -n "${CORE_LIB:-}" ] && [ -f "${CORE_LIB:-}" ]; then
  cp "$CORE_LIB" "$platdir/$libname"; echo "cdylib: from \$CORE_LIB"
elif [ -f "$repo_root/rust/target/release/$libname" ]; then
  cp "$repo_root/rust/target/release/$libname" "$platdir/$libname"; echo "cdylib: from local release build"
else
  rel="https://github.com/muthuishere/citenexus/releases/download/v$core_ver"
  curl -fsSL "$rel/$asset" -o "$platdir/$libname"
  curl -fsSL "$rel/$asset.sha256" -o "$work/a.sha256"
  ( cd "$platdir" && awk -v f="$libname" '{print $1"  "f}' "$work/a.sha256" | shasum -a 256 -c - )
  echo "cdylib: downloaded + SHA256-verified Release asset"
fi

# generate the platform package.json for this host
cat > "$platdir/package.json" <<JSON
{
  "name": "$scope/$base-$suffix",
  "version": "$core_ver",
  "description": "Prebuilt citenexus-core cdylib for $suffix.",
  "license": "Apache-2.0",
  "os": ["$os"],
  "cpu": ["$cpu"],
  "files": ["$libname"]
}
JSON

# main package needs an optionalDependency entry for THIS host's platform pkg so
# require.resolve() can find it; the committed main/package.json lists all four.
maindir="$work/main"; cp -R "$here/main" "$maindir"
node -e '
const fs=require("fs"),p=process.argv[1],name=process.argv[2],ver=process.argv[3];
const j=JSON.parse(fs.readFileSync(p));j.optionalDependencies={[name]:ver};fs.writeFileSync(p,JSON.stringify(j,null,2));
' "$maindir/package.json" "$scope/$base-$suffix" "$core_ver"

platform_tgz="$(cd "$platdir" && npm pack --pack-destination "$work" 2>/dev/null)"
main_tgz="$(cd "$maindir" && npm pack --pack-destination "$work" 2>/dev/null)"
echo "packed platform: $platform_tgz"
echo "packed main:     $main_tgz"
echo "platform tarball carries: $(tar tzf "$work/$platform_tgz" | grep -E '\.(so|dylib|dll)$')"

proj="$work/consumer"; mkdir -p "$proj"
( cd "$proj" && npm init -y >/dev/null 2>&1 \
  && npm install --no-audit --no-fund "$work/$platform_tgz" "$work/$main_tgz" >/dev/null 2>&1 )
echo "installed into throwaway consumer project (no toolchain)"

cat > "$proj/run.mjs" <<'JS'
import { coreVersion, coreLibPath } from "@muthuishere/citenexus-core-dist-spike";
const v = coreVersion();
console.log(`[node] coreVersion()=${JSON.stringify(v)}  (from ${coreLibPath()})`);
if (!/^\d+\.\d+\.\d+/.test(v)) { console.error("[node] FAIL: not a semver"); process.exit(1); }
if (!coreLibPath().includes("node_modules")) { console.error("[node] FAIL: not the installed platform pkg"); process.exit(1); }
console.log("[node] OK — os/cpu platform pkg resolved; koffi loaded bundled cdylib, no toolchain");
JS
( cd "$proj" && node run.mjs )
echo "js npm proof: PASS"
