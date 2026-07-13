# Design — citenexus-cli

## Distribution: one npm package, binaries from GitHub Releases

The binary static-links the Rust engine, so it is large and platform-specific —
wrong for npm tarballs, right for GH Releases. So:

- **Rust:** add `staticlib` to `crate-type` (keep `cdylib` for the existing FFI
  ports). Go builds `cmd/citenexus` with cgo `-lcitenexus_core` against the
  `.a`, producing ONE self-contained binary per platform.
- **CI:** a release matrix builds `citenexus-<os>-<arch>` for darwin arm64/x64,
  linux x64/arm64, win x64, and publishes them to a GH Release with a
  `SHA256SUMS` file. The npm package version equals the release tag.
- **npm `@muthuishere/citenexus`:** contains only
  - `bin/citenexus.mjs` — a launcher shim: resolve the cached binary for this
    `{version, platform}`; if absent, download+verify, then `exec` it.
  - `scripts/postinstall.mjs` — pre-fetch the binary (best-effort; a failure is
    NOT fatal — the launcher's lazy path covers `--ignore-scripts`, offline, CI).
- **Download + cache:** `GET <base>/<tag>/citenexus-<os>-<arch>(.exe)`, verify
  against the release SHA256, write to
  `~/.cache/citenexus/<version>/<platform>/citenexus`, `chmod +x`. Never exec an
  unverified file.
- **Overrides:** `CITENEXUS_BINARY` (explicit path → skip download, for
  air-gapped/dev), `CITENEXUS_DOWNLOAD_BASE` (mirror), and standard `HTTPS_PROXY`.

## Config: dual-level, secrets by reference

Resolution precedence (highest wins): **environment → project
`./citenexus.yaml` → global `~/.config/citenexus/config.yaml` → built-in
defaults**. Discovery walks up from the CWD to find the nearest `citenexus.yaml`
(git-style), so any subdirectory of a project is "inside" it.

- `citenexus init [dir]` writes a starter `citenexus.yaml` (storage, signals,
  models with `${ENV}` header templates, `mode: api`).
- `citenexus config get|set <key> [value]` edits the **global** file.
- **No literal secrets.** Auth lives only as `${ENV}` header templates, resolved
  by the Go HTTP client at the request edge (the pattern already shipped). A
  `citenexus.yaml` is always safe to commit.

Example project `citenexus.yaml`:
```yaml
storage: { backend: local, path: ./.citenexus }
signals: [embedding, text]
mode: api                      # or: skill
models:
  embedding:
    base_url: https://api.jina.ai/v1
    model: jina-embeddings-v3
    headers: { Authorization: "Bearer ${JINA_API_KEY}" }
  llm:
    base_url: https://api.openai.com/v1
    model: gpt-4o-mini
    headers: { Authorization: "Bearer ${OPENAI_API_KEY}" }
```

## Command surface (this slice)

| Command | Does | Backing |
|---|---|---|
| `citenexus init [dir]` | scaffold `citenexus.yaml` | — |
| `citenexus config get\|set` | read/write global config | — |
| `citenexus ingest <path\|url>` | extract → store (Rust core) | `golang/ingest` + `core` |
| `citenexus ask "<q>"` | retrieve + grounded answer | `golang/answer` + `models` (api mode) |
| `citenexus retrieve "<q>"` | fused candidates, cite-only | `golang/retrieve`/rrf/bm25 |
| `citenexus install --skills` | copy bundled `SKILL.md`+`references/` into `~/.claude/skills/citenexus/` **and** `~/.agents/skills/citenexus/` | embedded skill assets |

The skill install follows the `windowctl`/`playwright-cli` pattern: the `SKILL.md`
(+ a `references/` dir) is embedded in the Go binary (`embed.FS`) and written,
idempotently, into **both** `~/.claude/skills/citenexus/` and
`~/.agents/skills/citenexus/`. So `npm i -g @muthuishere/citenexus &&
citenexus install --skills` and the agent can immediately drive the CLI.

All commands take `--config`, `--json`, `--partition`. `ask` needs an `llm` model
configured; `retrieve`/`ingest` (lexical) work with none.

## LLM modes (config `mode:`)

- **`api`** (this slice): the CLI calls the model through the Go `models` clients
  with `${ENV}` header auth. Self-contained.
- **`skill`** (follow-on): the CLI writes durable request files under the folder
  and exits with a "needs fulfillment" status; the Python skill asks its model,
  writes answers back, and re-invokes the CLI to resume. This is the two-phase
  vision pattern generalized to every model call, backed by `citenexus.worker`.

## Gate note

The CLI is a **surface** consuming the library (`CLAUDE.md`: CLI is out of core).
The only core change here is the Rust `staticlib` crate-type; no new RAG behavior.
`okf`, `skill` mode, and the dashboard are their own follow-on changes.

## Verification

Because a CLI is a surface, not a pinned algorithm, it is covered by an
**integration test** (a hermetic ingest→retrieve→ask over fakes through the built
binary) rather than a conformance fixture. The download/launcher shim gets unit
tests for checksum-mismatch, cache-hit, and the lazy fallback path.
