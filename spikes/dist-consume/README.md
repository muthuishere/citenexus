# Spike: prebuilt-core CONSUME side ("easy like mochallama")

`native-libs.yml` (Tier-1) already cross-builds `citenexus-core` and uploads
per-platform libs + `.sha256` to a durable GitHub Release. This spike proves the
CONSUME half: **install-and-it-just-works, no Rust toolchain**, for Python, TS,
and Go — each pulling the prebuilt core, never rebuilding it.

| lang | mechanism | proof | result (darwin-arm64) |
|------|-----------|-------|--------|
| Python | Tier-2 **platform wheel** bundling `libcitenexus_core.*` in `citenexus/_lib/`, loaded by the `citenexus._native` ctypes seam | `python/repackage_and_prove.sh` | PASS |
| TS/JS | npm **`optionalDependencies` + `os`/`cpu`** platform packages, koffi-loaded via the main pkg's resolver | `js/pack_and_prove.sh` | PASS |
| Go | **runtime fetch** of the Release asset + SHA256 verify + cache + purego-dlopen (cgo `citenexus_ffi` stays the opt-in static alt) | `go/` (`go run .`) | PASS |
| model | shared **SHA256-verified fetch-cache** for lid.176 (pinned digest) | `model/model_fetch.py`; shipping copy in `citenexus.lang.detect` | PASS |

## Run locally (darwin-arm64)

```bash
export CORE_LIB="$PWD/../../rust/target/release/libcitenexus_core.dylib"  # or omit to fetch from Release
( cd go && go run . )                        # fetch+verify+load (uses real v0.7.0 Release)
bash python/repackage_and_prove.sh           # platform wheel -> fresh venv -> ctypes load
bash js/pack_and_prove.sh                     # npm pack -> temp project -> koffi load
python3 model/model_fetch.py                  # checksum gate self-test
```

Each script obtains the cdylib in this order: `$CORE_LIB` → local
`rust/target/release` build → **SHA256-verified download of the native-libs
Release asset** (the true Tier-2 path CI uses).

## Honest findings

- **Windows + Go/purego is a real blocker.** In the D1 real-core run, Windows
  built the core ✅ and the Python (ctypes) ✅ and Node (koffi) ✅ loaders loaded
  it — but the Go loader **failed to compile**: `undefined: purego.Dlopen`,
  `purego.RTLD_NOW`, `purego.RTLD_GLOBAL`. Those symbols are **Unix-only**
  (`//go:build !windows`); on Windows purego loads via `golang.org/x/sys/windows`
  `LoadLibrary` + `RegisterLibFunc(&fn, uintptr(handle), ...)`. Fix = a
  build-tagged `dlopen_windows.go`. The consume CI here targets the three Unix
  platforms; Windows-Go is a documented follow-up (Python/TS work on Windows).
- The v0.7.0 Release cdylib reports core version **`0.6.0`** — native-libs
  artifacts are keyed by the **git tag** (`v0.7.0`) but the cdylib embeds the
  **Rust crate version** (`rust/Cargo.toml`, then 0.6.0). Distribution should key
  the fetch on the **release tag** (as `corefetch.CoreVersion` does) and treat the
  returned version as informational; **SHA256 is the integrity check**, not the
  version string. Consider bumping `rust/Cargo.toml` in lockstep with releases.
- The cdylib is ~150 MB (lancedb/arrow) — hence Go **fetches** rather than
  `go:embed`ing all four (that would bloat every `go get`).

## Distribution architecture (Tier-1 / Tier-2)

- **Tier-1 — `native-libs.yml`** (rare, on core release): protoc + `cargo build
  --release` across `{linux-x64, linux-arm64, darwin-arm64, windows-x64}` →
  per-platform lib + `.sha256` → durable GitHub Release. Already green.
- **Tier-2 — `dist-tier2-publish.yml`** (cheap, per version tag): download the
  Tier-1 assets (SHA256-verified) and repackage per language:
  - **Python** → platform wheels (`macosx_11_0_arm64`, `manylinux2014_{x86_64,
    aarch64}`, `win_amd64`) bundling the cdylib; publish via **PyPI OIDC**.
  - **TS** → per-platform npm packages (`-darwin-arm64`, `-linux-x64`,
    `-linux-arm64`, `-win32-x64`) each with `os`/`cpu`, plus a main package whose
    `optionalDependencies` list them; publish via **npm OIDC/provenance**.
  - **Go** → nothing to publish (a module version is a tag); the runtime fetch
    pulls the Release lib, SHA256-verified.
- **Model (lid.176)** → the one runtime download in every language, always
  SHA256-verified against the pinned digest.

**Merge-time steps:** SHA-pin all `uses:`; flip `dist-tier2-publish.yml` to
`on: push: tags: ['v*']` with `dry_run` default false and the OIDC publish steps
un-commented; add a manylinux/glibc-floor build for portable Linux wheels; wire
the platform packages' names/scope to the real published package names.
