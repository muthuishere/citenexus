## Why

`bm25`, `rrf`/fusion, `chunker`, and the cite-or-abstain **grounding gate** are
implemented three times — `python/`, `golang/`, `js/src/` — none in the Rust core.
The one behavior that must be byte-identical everywhere is hand-maintained in three
languages, free to drift. That drift — on the cite-or-abstain decision especially —
is the highest-consequence risk in the system.

The fix is **not** "move it all to Rust." Two facts (see ADR-0006) forbid moving
the gate: SPEC-PORTS-v1 explicitly keeps cite-or-abstain per-host so *"the
guarantee logic stays hackable without a Rust toolchain"*, and the gate depends on
`tokenize()` — Rust vs Python Unicode semantics (Turkish I, ß, NFC/NFD) diverge, so
a Rust gate would **silently disagree with itself on exactly the non-Latin
languages CiteNexus targets**, invisible to an ASCII parity test.

So the problem is **drift**, and the right fix kills drift without relocating the
dangerous piece: move only genuinely pure computation to the core, and pin the rest
with a shared conformance-vector suite. (Per ADR-0006.)

## What Changes

- **Move `rrf`/fusion into the Rust core.** It is rank arithmetic over IDs and
  scores — no tokenization, no Unicode, no key. Exposed via FFI, byte-parity-tested;
  SDKs become thin bindings, old public appearance **deprecated, not removed**.
- **New: a shared, language-agnostic conformance-vector suite** for the pieces that
  STAY per-host — the grounding gate, `bm25`, and `chunker`. Golden `input →
  expected output` fixtures, checked in once, that **every** port (Python, Go, JS,
  future Rust) must pass. Python (the behavior reference) generates the vectors.
  The suite MUST include a **multilingual/Unicode-edge corpus** (Turkish, German,
  CJK, RTL, combining marks) so divergence is caught where it happens.
- **The gate and orchestration STAY per host language** (ADR-0006 upholds
  SPEC-PORTS-v1). `bm25`/`chunker` may move to the core *later* only if conformance
  vectors prove insufficient, and only with the tokenizer treated as the single
  parity-critical primitive.
- **Not here:** the two-phase model-fulfiller protocol splits into its own change,
  `model-fulfiller-protocol` (it concerns where the authenticated HTTP call
  happens, not where deterministic logic lives).

## Capabilities

### New Capabilities
- `rust-core-logic`: `rrf`/fusion implemented once in the Rust core (FFI, byte-
  parity-tested; SDKs thin bindings, old public appearance deprecated-not-removed),
  plus a shared conformance-vector suite (incl. a multilingual corpus) that pins the
  per-host grounding gate, `bm25`, and `chunker` against drift.

### Modified Capabilities
- (none change requirements — `rrf` output is byte-identical by construction;
  the conformance suite adds tests, not new behavior; the gate stays where it is.)

## Impact

- **Depends on ADR-0006** (the boundary decision). Reverses the original "move the
  gate to Rust" thesis for the gate; keeps it for pure compute.
- **Rust core:** new `rrf` module + FFI + parity test.
- **All ports:** rewire fusion to the FFI binding (deprecate, don't delete, any
  public helper — verify each helper's actual public/internal exposure first); add
  the conformance-vector runner so gate/bm25/chunker are pinned in Python, Go, JS.
- **Guarantee:** strengthened — parity becomes structural (every current and future
  port, including native-lib paths that will never be Rust), and the multilingual
  cite-or-abstain decision is protected by the Unicode corpus rather than risked by
  a Rust tokenizer.
- **0.x:** additive tests + one internal relocation; public appearance preserved via
  deprecation.
