# IN PROGRESS — structural sources + deep-ask + Rust boundary

Last updated: 2026-07-18 · Branch: `feat/structural-code-graph` · PR: **#13** (→ `main`)

## TL;DR
Five OpenSpec changes are **implemented, consolidated, and verified green** across
Rust/Python/Go/JS on `feat/structural-code-graph`. Reviewed by a 3-agent adversarial
team first, built by a worktree agent team, each result re-verified by hand (that
caught 4 real bugs the agents' "green" would have hidden). **Nothing is merged to
`main`, nothing is published.**

## The five changes (all DONE + green)
1. **structural-code-graph** — Rust tree-sitter code extractor (`rust/src/extract/code.rs`,
   MIT grammars) + Python parity oracle (`extract/code.py`); `rag.code.ingest_from(folder|git)`
   (`code/facade.py`, graph-required); `GraphEdge.confidence` (Py/Go/JS); deferred graph
   rebuild; injected structural distiller (`example/code_graph/`).
2. **deep-ask** — `answer/agentic.py` loop + `LoopBudget` (whole-loop `timeout_s`);
   **net-new per-claim single-EU gate**; `answer/decision.py` structured-decision (not
   tool-calling); `strategy="deep"` opt-in, strict unchanged.
3. **schema-extractors** — `rust/src/extract/schema_{sql,openapi}.rs` (EU-only) + Python
   twins; injected schema distiller (`example/schema_graph/`, FK/`$ref` = `extracted`);
   `rag.schema.ingest_from(file|doc)` (`schema/facade.py`). Live-DB/sampled OUT.
4. **rust-first-core** — `rust/src/rrf.rs` + `citenexus_rrf` FFI; Go `core.Fuse` / JS
   `core.rrf` bindings (old helpers deprecated-not-removed); multilingual conformance
   corpus (`conformance/cases/multilingual.json`) — caught + fixed a real Go `İ`
   case-folding drift in `golang/tokenize`.
5. **model-fulfiller-protocol** — `domain/model.py` + `fulfiller/` two-phase protocol;
   key never crosses FFI either direction; host signing hook. Python-only.

Boundary decision: **`docs/adr/0006-core-boundary-conformance-vectors.md`** (pure compute →
Rust core; gate/tokenizer stay per-host; drift dies by conformance vectors).

## Verified state (2026-07-18, my own runs)
Rust `cargo test` **63** · Python `pytest -m "not integration"` **694** (5 skipped
pre-existing) · Go **13 pkgs ok** · JS **125** · ruff/mypy **zero new** (15/21 baseline
in `scripts/`+`tests/wiki`) · conformance consistent.

## ⚠️ Rebuild gotchas (bit me twice — do this after ANY Rust change)
The Python loader picks the **debug** dylib first; JS koffi loads the **release** dylib.
After changing `rust/`, rebuild BOTH or FFI tests load a stale lib:
```
cd rust && cargo build && cargo build --release
```
Symptom of stale lib: `Cannot find function 'citenexus_rrf'` (JS) or code/schema parity
failures (Python).

## Resume — verify the whole thing green
```
cd rust && cargo build && cargo build --release && cargo test        # 63 passed
cd ../python && uv run pytest -q -m "not integration"                # 694 passed, 5 skipped
cd ../golang && go test ./...                                        # 13 ok
cd ../js && npx vitest run                                           # 125 passed
```

## NOT done / next steps
- [ ] **Review + merge PR #13** into `main`.
- [ ] **Decide the `cite-check-cli` inclusion** — the branch carries unrelated pre-existing
      cite-check work (`openspec/changes/2026-07-13-cite-check-cli/`, `cli/cite_check.py`,
      tests) that rode in via a worktree base. Keep in this PR or split out.
- [ ] **Archive the OpenSpec changes** (`/opsx:archive` each) — best AFTER merge, so the
      living spec under `openspec/specs/` reflects what shipped.
- [ ] **Publish** — NOT started. Per-registry (PyPI/npm/crates/Go tag), only after merge +
      green + explicit owner go. See [[citenexus-published-state]] for the release ritual.
- [ ] Pre-existing **Go FFI `TestToMarkdown`** (xlsx GFM-table format) fails — unrelated,
      untouched.
- [ ] Follow-on changes (by design): Go/JS graph seam; make `confidence` **load-bearing**
      for topology answers (navigate-not-cite protects content, not topology); per-seam
      fulfiller migrations (generator/embedder/reranker/vision); live-DB schema connectors.
- [ ] Prune agent worktrees under `.claude/worktrees/` if desired.

## Context (memory notes)
`citenexus-impl-progress-structural-code-graph`, `citenexus-review-corrections-2026-07-17`,
`citenexus-rust-first-direction`, `citenexus-intake-api-family`, `citenexus-schema-ingest-direction`,
`citenexus-breaking-change-policy`, `citenexus-deep-ask-design`, `citenexus-structural-graph-spike`.
