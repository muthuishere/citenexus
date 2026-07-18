## Context

Four deterministic pieces — `bm25`, `rrf`/fusion, `chunker`, grounding gate — are
triplicated across `python/`, `golang/`, `js/src/`, none in the Rust core.
SPEC-PORTS-v1 explicitly keeps cite-or-abstain per-host ("the guarantee logic must
stay hackable without a Rust toolchain"); the gate is tokenizer-dependent and a
Rust move would diverge on non-Latin languages. ADR-0006 settles the boundary: pure
compute moves in, the gate stays per-host, drift dies by conformance vectors.

## Goals / Non-Goals

**Goals:**
- Kill drift on the deterministic RAG logic across all ports.
- Move genuinely pure computation (`rrf`) to the core, byte-parity-tested.
- Pin the per-host gate / `bm25` / `chunker` with a shared conformance suite that
  includes a multilingual/Unicode corpus.

**Non-Goals:**
- Moving the cite-or-abstain gate or the tokenizer into Rust (ADR-0006; Unicode
  risk; the "hackable" value).
- The model-fulfiller protocol (separate change `model-fulfiller-protocol`).
- Any change to orchestration or the ask flow.

## Decisions

### 1. Move only pure, text-free compute (`rrf`) to the core

`rrf` fuses ranked lists by ID/score arithmetic — no tokenization, no Unicode, no
key. It moves to the core (FFI, byte-parity vs the Python reference). Rationale:
clear parity win, zero Unicode/guarantee risk. Deterministic ordering of fused
output is the one invariant the parity test pins.

### 2. The gate, `bm25`, `chunker` stay per-host; drift dies by conformance vectors

A shared golden fixture suite (`input → expected output`) that every port must pass
replaces relocation as the anti-drift mechanism. Rationale (ADR-0006): it makes
parity structural *without* moving Unicode-sensitive logic into a toolchain-heavy
core, honors the ports-spec "hackable" value, and — unlike relocation — also pins
native-lib port paths that will never be Rust. Python generates the vectors as the
behavior reference.

**The suite MUST carry a multilingual/Unicode-edge corpus** — Turkish dotless-I,
German ß, NFC vs NFD, CJK segmentation, RTL, combining marks — because the gate's
`tokenize()` is exactly where ports diverge. An ASCII-only suite would pass while
the real decision breaks.

### 3. Deprecate, don't remove — after verifying exposure

Where a port exposed its own fusion helper publicly, keep a **deprecated** shim to
the FFI binding (0.x policy). Internal-only helpers may be replaced outright — but
each helper's actual public/internal exposure MUST be verified first, so a
user-imported helper isn't silently removed under the "internal" label.

### 4. `bm25`/`chunker` to core is deferred, conditional

They also tokenize, so moving them carries the same Unicode risk as the gate. They
move to the core only if conformance vectors prove insufficient, and only by first
making the tokenizer the single parity-critical core primitive gated on the
multilingual corpus. Out of scope here.

## Risks / Trade-offs

- **[Conformance vectors miss a case the code later hits]** → the suite is
  append-only and multilingual from day one; any drift bug found becomes a new
  vector. Cheaper and safer than a Rust tokenizer.
- **[`rrf` FFI changes fused ordering]** → byte-parity test on ordering vs the
  Python reference before any port switches.
- **[Silent public removal via misclassification]** → verify each helper's exposure
  before replacing; default to a deprecated shim when unsure.

## Migration Plan

Move `rrf` behind its parity test; switch ports to the binding; deprecate (not
delete) public fusion helpers. Land the conformance-vector runner + multilingual
corpus in Python/Go/JS for gate/bm25/chunker. No data/artifact changes. Rollback =
keep the deprecated helper until the binding is proven.

## Open Questions

- Fixture format for the conformance suite (one JSON corpus consumed by all ports
  vs. per-language golden files generated from a Python source of truth — lean: one
  shared JSON corpus).
- Whether `rrf` config (k=60) is a core constant or passed in (lean: passed in, so
  the core stays policy-free).
