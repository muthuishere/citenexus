## 1. Move `rrf`/fusion to the Rust core (parity-gated)

- [ ] 1.1 Implement `rrf` in `rust/src/` + FFI (config like k=60 passed in, core
      stays policy-free).
- [ ] 1.2 Byte-parity test vs the Python reference on fused ordering; assert
      deterministic ordering.
- [ ] 1.3 Switch Go/JS/Python fusion to the FFI binding; verify each public fusion
      helper's exposure, then deprecate (not delete) any public one.

## 2. Conformance-vector suite for the per-host logic

- [ ] 2.1 Define the shared fixture format (lean: one JSON corpus, Python-generated)
      for the grounding gate, `bm25`, and `chunker`.
- [ ] 2.2 Generate vectors from the Python reference; include a multilingual/Unicode
      corpus (Turkish dotless-I, German ß, NFC vs NFD, CJK, combining marks).
- [ ] 2.3 Add a conformance runner in Python, Go, and JS that runs every vector
      against that port's gate/bm25/chunker.
- [ ] 2.4 Red→green: every port passes all vectors; a Unicode-edge vector fails a
      deliberately-divergent tokenizer (proving the corpus bites).

## 3. Guardrails & follow-ons

- [ ] 3.1 `cargo test` (core + rrf parity), Python `task lint`/`typecheck`/`test`,
      Go `go test ./...`, JS suite — all green, all ports pass conformance.
- [ ] 3.2 Update `rust/README.md` + `docs/SPEC-PORTS-v1.md` to reflect ADR-0006:
      `rrf` in core; gate/tokenizer stay per-host; conformance vectors are the
      anti-drift mechanism.
- [ ] 3.3 Note the deferred/conditional follow-on: `bm25`/`chunker` (and the
      tokenizer) move to core ONLY if conformance proves insufficient, tokenizer as
      the single parity-critical primitive.
- [ ] 3.4 The two-phase model-fulfiller protocol ships as the separate change
      `model-fulfiller-protocol` — not here.
