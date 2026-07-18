## 1. Code extractor — Rust core (once, via FFI)

- [ ] 1.1 Add tree-sitter + grammar crates (Python + Go at minimum) to
      `rust/Cargo.toml`; confirm MIT licensing before pinning.
- [ ] 1.2 Implement `rust/src/extract/code.rs`: one verbatim `code` block per
      top-level symbol, byte-range → line range carried, `structure_path` =
      enclosing symbol names, preamble preserved as a leading block,
      `structure_type = code_ast`. Single `code` source type + detected-language
      tag (design decision 3).
- [ ] 1.3 Wire the `code` source type into `citenexus_extract` dispatch (Rust) and
      recognise code extensions (`.py`, `.go`); unknown extensions still fall back
      to plain.
- [ ] 1.4 Add the Python **reference** implementation (`extract/code.py`) — used
      only as the parity oracle, not the shipped path.
- [ ] 1.5 Red→green parity test `tests/core/test_rust_code_parity.py`: core output
      is byte-identical to the Python reference (function→citable symbol EU with
      `file:Lx-Ly`; method records enclosing class; preamble not dropped).
- [ ] 1.6 Unsupported-language source falls back to plain without raising.

## 2. `rag.code.ingest_from(folder | git)` intake verb (per-language facade)

- [ ] 2.1 Add the `rag.code` namespace + `ingest_from(source)` verb in Python
      (and mirror in Go/JS): accept a folder path or git URL, acquire (git clone /
      folder walk), filter to code files (skip vendored/build dirs), drive the core
      extractor per file, then build the graph.
- [ ] 2.2 Fail-loud precondition: raise immediately if the instance has no
      `graph`/`community` signal — name the missing signal, ingest nothing. Test it.
- [ ] 2.3 Red→green: folder ingest produces symbol EUs skipping vendored dirs; a
      git URL is cloned and ingested; missing-graph-signal raises.
- [ ] 2.4 SDK wiring: Go/JS route each code file through `extract_ffi.go` / koffi to
      the core extractor — no reimplementation; Python keeps the reference impl for
      parity only.

## 3. GraphEdge.confidence

- [ ] 3.1 Add the `confidence` enum (`extracted`/`inferred`/`ambiguous`) + optional
      field (default absent/`None`, pinned **absent when None** — never `null`) to
      `GraphEdge`/`Edge` in `python/.../graph/store.py`, `golang/graph/graph.go`,
      `js/src/graph/graph.ts`. Python's graph layer uses it; Go/JS get the field
      (their graph seam is unwired — see group 6).
- [ ] 3.2 Red→green (Python): an old `graph.json` (no key) loads with every edge
      `confidence=None`; co-mention build leaves it `None`; a producer-emitted index
      round-trips `confidence`.
- [ ] 3.3 Cross-language byte-parity: all three serialize an unset `confidence` to
      the SAME on-disk form (key absent), a set one identically.

## 4. Deferred single-`ingest()` rebuild — Python

- [ ] 4.1 Change `_refresh_incremental` so a single `ingest()` marks the leaf graph
      dirty instead of full-rebuilding (design decision 5a). Python only (the wired
      layer); batch already amortizes via `refresh_slow_path()`.
- [ ] 4.2 Rebuild lazily before any graph-reading `ask()`; keep the explicit full
      rebuild in `refresh_slow_path()`; persist the dirty marker so a fresh process
      still rebuilds.
- [ ] 4.3 Red→green: a sequence of single `ingest()` calls does not full-rebuild each
      time; a graph-using `ask()` after ingests observes a graph consistent with all
      committed ingests.

## 5. Integration & guardrails

- [ ] 5.1 Fold the spike's `StructuralDistiller` into example/spike code (injected
      via `graph_distiller=`), NOT core; confirm it now grounds ~100% of in-corpus
      symbols (external/stdlib targets still have no EU — expected).
- [ ] 5.2 End-to-end (Python): ingest a small code corpus, inject the distiller,
      assert "who calls X" resolves to cited symbol EUs. **Add a topology-safety
      test**: a name-collision (two `Tokenize`s) with a wrong `inferred` edge must
      NOT silently yield a misattributed answer — it surfaces `confidence=inferred`
      (the load-bearing answer-path behavior is a follow-on; here assert the signal
      is present, not swallowed).
- [ ] 5.3 Green: `cargo test` (core + parity), Python `task lint`/`typecheck`/`test`,
      Go `go test ./...`, JS suite.
- [ ] 5.4 Update `docs/SPEC-v6.md` / `docs/SPEC-PORTS-v1.md` / ADR-0006 to record:
      extractor in core; call-graph producer injected; graph-build stays per-host;
      navigate-not-cite protects content not topology → `confidence` must go
      load-bearing in the answer path (follow-on change).

## 6. Follow-on (NOT in this change — recorded so scope is explicit)

- [ ] 6.1 Build the Go/JS graph SEAM (distiller injection, `GraphRetriever` wiring,
      ingest→rebuild) — today they are unwired stubs. Separate change.
- [ ] 6.2 Make `confidence` load-bearing in the answer path for topology questions
      (down-weight / attribute / abstain on `inferred`). Separate change.
