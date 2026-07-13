## 1. Rust staticlib + static-linked Go build

- [x] 1.1 Add `staticlib` to the Rust crate `crate-type` (keep `cdylib`); `cargo build --release` emits `libcitenexus_core.a`
- [x] 1.2 A `citenexus_ffi`-tagged Go build that static-links the `.a` (cgo LDFLAGS) produces a self-contained binary; smoke-run it

## 2. Go CLI skeleton (`cmd/citenexus`)

- [x] 2.1 Failing test: `citenexus --version` and `--help` list the command set
- [x] 2.2 Add `cmd/citenexus/main.go` with a command router (`init`, `config`, `ingest`, `ask`, `retrieve`), global flags `--config/--json/--partition`

## 3. Dual-level config (red → green)

- [x] 3.1 Failing test: resolution precedence env → project `./citenexus.yaml` → global `~/.config/citenexus/config.yaml` → defaults; nearest-ancestor project discovery
- [x] 3.2 Failing test: `${ENV}` header templates are stored verbatim (no literal secret) and resolved only at the request edge
- [x] 3.3 Implement the layered loader + `citenexus init` (scaffold project yaml) + `citenexus config get|set` (global)

## 4. Commands in `api` mode (red → green)

- [x] 4.1 Failing integration test (hermetic, fakes): `init` → `ingest` → `retrieve` returns the doc; `ask` returns a grounded answer / refuses
- [x] 4.2 Wire `ingest` (`golang/ingest`+core), `retrieve` (rrf/bm25/vector), `ask` (`golang/answer`+`models`, `${ENV}` auth); `--json` output shapes

## 5. Skill self-install (`windowctl` pattern) (red → green)

- [x] 5.1 Failing test: `citenexus install --skills` writes the bundled `SKILL.md` (+`references/`) into BOTH `~/.claude/skills/citenexus/` and `~/.agents/skills/citenexus/`, idempotently (re-run is a no-op)
- [x] 5.2 Embed the skill assets via `embed.FS`; implement the single `install --skills` command (windowctl/playwright pattern); ship a minimal `SKILL.md` (the full Python driver lands in `citenexus-skill`)

## 6. npm package + GitHub-Releases installer (red → green)

- [x] 6.1 Failing test: the downloader verifies SHA256 and REFUSES a mismatched binary
- [x] 6.2 Failing test: launcher lazy-downloads on first run when postinstall was skipped; cache-hit path re-execs without network; `CITENEXUS_BINARY` override bypasses download
- [x] 6.3 Implement `@muthuishere/citenexuscli`: `bin/citenexus.mjs` launcher + `scripts/postinstall.mjs` (best-effort, non-fatal); cache `~/.cache/citenexus/<version>/<platform>`; `CITENEXUS_DOWNLOAD_BASE` + `HTTPS_PROXY`

## 7. CI release matrix

- [x] 7.1 GH Actions workflow (SHA-pinned actions) builds `citenexus-<os>-<arch>` for darwin arm64/x64, linux x64/arm64, win x64 (static-linked) and publishes a Release with `SHA256SUMS`
- [x] 7.2 npm publish job (`needs: build`) tags version == release tag

## 8. Docs

- [x] 8.1 A `cli` docs page: install (`npm i -g @muthuishere/citenexuscli`), `citenexus install --skills`, `init`, dual config, `${ENV}` secrets, the command table, `api` vs `skill` mode
- [x] 8.2 Note the follow-on roadmap (okf, dashboard, skill mode, parity) so the page doesn't overclaim
