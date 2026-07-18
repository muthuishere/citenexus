## 1. Move `rrf`/fusion to the Rust core (parity-gated)

- [x] 1.1 Implement `rrf` in `rust/src/` + FFI (config like k=60 passed in, core
      stays policy-free). `rust/src/rrf.rs` + `citenexus_rrf(lists_json, k)`.
- [x] 1.2 Byte-parity test vs the Python reference on fused ordering; assert
      deterministic ordering. `rust/tests/rrf_test.rs` (loads `cases/rrf.json`,
      + pure-fn/FFI/determinism) and `python/tests/core/test_rust_rrf_parity.py`
      (ctypes through the real C ABI vs live `rrf_fuse`).
- [x] 1.3 Switch Go/JS/Python fusion to the FFI binding; verify each public fusion
      helper's exposure, then deprecate (not delete) any public one. Go `core.Fuse`
      + JS `core.rrf` are the canonical bindings; the public `golang/rrf.Fuse`,
      `rrfFuse`, and `rrf_fuse` are deprecated-not-removed (still conformance-pinned).

## 2. Conformance-vector suite for the per-host logic

- [x] 2.1 Define the shared fixture format (lean: one JSON corpus, Python-generated)
      for the grounding gate, `bm25`, and `chunker`. `conformance/cases/multilingual.json`
      with `tokenize`/`bm25`/`chunker`/`gate` sections.
- [x] 2.2 Generate vectors from the Python reference; include a multilingual/Unicode
      corpus (Turkish dotless-I, German ß, NFC vs NFD, CJK, combining marks).
      `scripts/gen_conformance.py::_multilingual_cases`.
- [x] 2.3 Add a conformance runner in Python, Go, and JS that runs every vector
      against that port's gate/bm25/chunker. `python/tests/test_conformance_multilingual.py`,
      `golang/{tokenize,bm25,chunker,gate}/multilingual_test.go`,
      `js/src/conform/multilingual.test.ts`.
- [x] 2.4 Red→green: every port passes all vectors; a Unicode-edge vector fails a
      deliberately-divergent tokenizer (proving the corpus bites). The corpus caught
      a REAL Go drift (İ → simple-lower "istanbul" vs reference "i"+"stanbul") across
      tokenize/bm25/gate; fixed `golang/tokenize` to full-case-map İ. Permanent proof:
      `golang/tokenize::TestMultilingualCorpusBites`.

## 3. Guardrails & follow-ons

- [x] 3.1 `cargo test` (core + rrf parity), Python `task lint`/`typecheck`/`test`,
      Go `go test ./...`, JS suite — all green, all ports pass conformance.
- [x] 3.2 Update `rust/README.md` + `docs/SPEC-PORTS-v1.md` to reflect ADR-0006:
      `rrf` in core; gate/tokenizer stay per-host; conformance vectors are the
      anti-drift mechanism.
- [x] 3.3 Note the deferred/conditional follow-on: `bm25`/`chunker` (and the
      tokenizer) move to core ONLY if conformance proves insufficient, tokenizer as
      the single parity-critical primitive. (Recorded in ADR-0006 §4 and the specs.)
- [x] 3.4 The two-phase model-fulfiller protocol ships as the separate change
      `model-fulfiller-protocol` — not here.
