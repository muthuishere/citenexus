# Spike: prebuilt real-core distribution

Proves CiteNexus can ship **one** prebuilt Rust core (`citenexus-core`, with
lancedb + arrow + tokio + fasttext) that Python / TS / Go auto-load with **no
toolchain**, across `{linux-x64, linux-arm64, darwin-arm64, windows-x64}`.

The toy spike (`../prebuilt-ffi`) proved the *load seam* with a zero-dep cdylib.
`native-libs.yml` already proves the real core *builds* on all four platforms on
a `v*` tag (green on v0.6.0 / v0.7.0). This spike closes the gap: build the real
core **and actually dlopen it** from all three bindings, calling the real symbol
`citenexus_core_version()`.

## Layout

- `python/check_core.py` — ctypes (stdlib, zero deps) loader.
- `node/check_core.mjs` — koffi loader.
- `go/check_core.go` — purego loader (pure Go, no cgo).
- `wheel/` — pip-installable wheel that **bundles** the platform cdylib and
  loads it via ctypes; `wheel/build.sh` proves `pip install` + `import` with no
  cargo on PATH.
- `model_fetch.py` — SHA256-verified fetch-cache for lid.176 (adds the checksum
  the reference `mochallama` omits).
- CI: `../../.github/workflows/spike-dist-real-core.yml`.

All three loaders read `CORE_LIB` (abs path to the built cdylib) and assert the
returned version equals `EXPECT_CORE_VERSION` (read from `rust/Cargo.toml`),
proving they loaded exactly the lib the workflow just built.

## Run locally (darwin-arm64)

```bash
(cd ../../rust && cargo build --release)          # needs protoc on PATH
export CORE_LIB="$PWD/../../rust/target/release/libcitenexus_core.dylib"
export EXPECT_CORE_VERSION="$(grep -m1 '^version' ../../rust/Cargo.toml | sed -E 's/.*"([^"]+)".*/\1/')"
python3 python/check_core.py
( cd node && npm install && node check_core.mjs )
( cd go && go mod tidy && go run check_core.go )
bash wheel/build.sh                                # pip-install-and-load, no toolchain
python3 model_fetch.py                             # checksum-gate self-test
```

## Recommended distribution architecture (Tier-1 / Tier-2)

**Tier-1 — cross-compile (rare; on release of the core):** the matrix above
installs protoc, builds `rust/` as a release cdylib (`pdf` OFF), and publishes
each per-platform lib + a `SHA256SUMS` file to a **durable GH (pre)release**
keyed by the core version. This is the expensive ~40-min job; it runs only when
the Rust core changes, not on every language release. (native-libs.yml is the
existing seed of this tier.)

**Tier-2 — repackage (cheap; per language version tag):** downloads the pinned
prebuilt for each target platform from the Tier-1 release (verifying against
`SHA256SUMS`), drops it into the language package, and publishes:

- **Python** — one platform wheel per target (`macosx_11_0_arm64`,
  `manylinux2014_{x86_64,aarch64}`, `win_amd64`), each bundling its cdylib under
  the package; ctypes loads it from the package dir. Publish via **PyPI OIDC
  trusted publishing**. (`wheel/` proves the bundle+load; a matrix generalizes
  the tag.)
- **TS/npm** — a thin main package with per-platform packages in
  `optionalDependencies`, each gated by `os`/`cpu` so npm installs only the
  matching one; koffi loads the bundled lib. Publish via npm OIDC provenance.
- **Go** — `go:embed` the platform lib into per-GOOS/GOARCH build-tagged files
  (or fetch-on-first-use into a cache), extract to a temp path, purego dlopens
  it. No cgo, so `go get` stays toolchain-free.

**Model assets** (lid.176, ~126 MB) never ship in the packages — fetched on
first use via `model_fetch.py` with a **pinned SHA256** and atomic cache.

**Merge-time hardening:** SHA-pin all `uses:` (currently float for the spike),
promote the Tier-1 workflow to run on a core-version tag, and add a
manylinux/glibc-floor build for the Linux wheels (the runners' native `.so`
links the runner's glibc; a manylinux container gives a portable floor).
