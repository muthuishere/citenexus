# Proposal — citenexus-cli

## Why

CiteNexus is a library, but people adopt a tool. A single, installable **Go CLI**
makes every core feature usable from a shell and, crucially, **drivable headless
by an agent skill** — the primary consumption path we want. It must install with
one `npm i -g`, work per-folder with a checked-in config (no secrets in it), and
call models two ways: directly (`api` mode) or by deferring the LLM work to the
skill (`skill` mode, the generalized two-phase pattern).

## What Changes (this change = the foundation slice)

- **Rust core builds a `staticlib`** (alongside the existing `cdylib`) so the Go
  binary can **static-link** the engine into one self-contained executable per
  platform — no dylib to ship or find at runtime.
- **`cmd/citenexus` Go binary** with the first, Go-ready command set:
  `init`, `config`, `ingest`, `ask`, `retrieve` — plus `--json` output.
- **`citenexus install --skills`** — one command (the `windowctl`/`playwright-cli`
  pattern): copy the bundled `SKILL.md` (+ `references/`) into **both**
  `~/.claude/skills/citenexus/` and `~/.agents/skills/citenexus/`, idempotent. So
  `install --skills` then "the agent drives the CLI" is one step. (The skill's
  Python driver is fleshed out in the `citenexus-skill` follow-on; this change
  ships the install mechanism + a minimal bundled skill.)
- **Dual-level config**: global `~/.config/citenexus/config.yaml` ← project
  `./citenexus.yaml` ← environment. `citenexus init` scaffolds the project file;
  `citenexus config get|set` edits global. **Secrets are `${ENV}` templates only**
  (e.g. `headers: {Authorization: "Bearer ${OPENAI_API_KEY}"}`), resolved at the
  request edge — a config is always safe to commit.
- **`api` LLM mode** wired through the Go `models` clients (the `${ENV}` header
  auth already shipped).
- **npm distribution**: ONE package `@muthuishere/citenexuscli` = a `bin` launcher
  shim + a `postinstall` downloader that pulls the platform binary from **GitHub
  Releases** and caches it. Safeguards: **SHA256 checksum verify**, **lazy
  first-run download** (survives `--ignore-scripts`/offline install), cache in
  `~/.cache/citenexus/<version>/<platform>`, env overrides (`CITENEXUS_BINARY`,
  mirror base URL), `HTTPS_PROXY` respected. Its OWN custom release, tagged
  `cli-v<version>` (separate from the core's `v*` releases); npm version ↔ that
  tag, 1:1.
- **CI release matrix** (darwin arm64/x64, linux x64/arm64, win x64) → GH Release
  with `SHA256SUMS`.

## Roadmap (sequenced follow-on changes, not this one)

1. `okf` — grounded OKF emit + pull (lean `kb` layout, `# Citations` from EUs).
2. `citenexus-cli-dashboard` — a TUI `status`/`dashboard` over corpus + telemetry
   + jobs (renders the existing telemetry stream).
3. `skill` LLM mode — CLI emits model requests, the **Python skill** fulfills and
   resumes; wires the dormant `citenexus.worker` durable queue.
4. `citenexus-skill` — the Python agent skill (`SKILL.md` + driver) that drives
   the binary and does the asking in `skill` mode.
5. Go feature parity for the remaining facade capabilities (evaluate, graph, wiki,
   vision, revoke), each conformance-pinned; then the deep hierarchical wiki.

## Capabilities

- **New:** `citenexus-cli`
- **Modified:** none (the CLI consumes existing library capabilities; the only
  core touch is the Rust `staticlib` crate-type).

## Impact

Additive. The library and its ports are unchanged behaviorally. New surface area:
`cmd/citenexus` (Go), an npm package, a CI release workflow, and a `staticlib`
output from the Rust crate.
