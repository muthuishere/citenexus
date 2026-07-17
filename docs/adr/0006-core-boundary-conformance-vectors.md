# 0006 — The core boundary: pure compute moves in, the guarantee logic stays hackable; drift dies by conformance vectors

Status: proposed · 2026-07-17

## Context

`bm25`, `rrf`/fusion, `chunker`, and the cite-or-abstain **grounding gate** are
implemented three times — `python/`, `golang/`, `js/src/` — none in the Rust core
(core holds only extract/emit/store/detect). The one behavior that must be
byte-identical everywhere is hand-maintained in three languages, free to drift.
The `rust-first-core` proposal wanted to fix this by moving *all* of it, including
the gate, into the Rust core.

Two hard facts constrain that:

1. **SPEC-PORTS-v1 already decided the opposite, with a reason.** It states: *"The
   core is the engine, not the brain. Orchestration NEVER moves in: the ask flow,
   **cite-or-abstain**, plugin seams, hooks, config … stay in each host language
   (IO-bound — no Rust win, **and the guarantee logic must stay hackable without a
   Rust toolchain**)."* The "hackable" clause is a deliberate value: the cite-or-
   abstain decision is the product's soul; a contributor must be able to read and
   change it in the language they work in, without cross-compiling a cdylib.
2. **Moving the gate into Rust is actively dangerous for the multilingual target.**
   The gate depends on `tokenize()` (case-fold, Unicode normalization, word
   segmentation). Rust and Python Unicode semantics differ (Turkish dotless-I,
   German ß, NFC/NFD). An ASCII parity test passes while the cite-or-abstain
   decision **diverges on exactly the non-Latin languages CiteNexus exists to
   serve** — a silent, guarantee-breaking regression. (Adversarial review, 2026-07-17.)

So the real problem is **drift**, and "move it to Rust" is only one way to kill
drift — and the most dangerous one for the piece that matters most.

## Decision

Cut the boundary by **what the code is**, and kill drift by **conformance**, not
relocation:

1. **Pure, text-free computation → the Rust core.** `rrf`/fusion is rank
   arithmetic over IDs and scores — no tokenization, no Unicode, no key. It moves
   into the core, exposed via FFI, byte-parity-tested. Clear win, no risk.

2. **The cite-or-abstain gate and orchestration STAY per host language.** Per
   SPEC-PORTS-v1 and the multilingual-tokenizer risk, the gate is **not** relocated.
   It remains hackable in each language.

3. **Drift dies by a shared, language-agnostic CONFORMANCE VECTOR SUITE.** The
   gate, `bm25`, and `chunker` each get a golden fixture set — inputs → expected
   outputs, checked into one place — that **every** port (Python, Go, JS, and any
   future Rust impl) must pass. This makes parity *structural* without moving
   Unicode-sensitive logic into a toolchain-heavy core. The suite MUST include a
   **multilingual/Unicode-edge corpus** (Turkish, German, CJK, RTL, combining
   marks) so divergence is caught where it actually happens. Python stays the
   behavior reference that generates the vectors.

4. **`bm25`/`chunker` (tokenizer-dependent) may move to the core LATER — only if
   conformance vectors prove insufficient — and if so the tokenizer becomes the
   single parity-critical primitive, gated by the multilingual corpus.** Not now.

5. **The two-phase model-fulfiller protocol is independent of the above and
   stands.** It concerns *where the authenticated model HTTP call happens* (host,
   key never in Rust), not where deterministic logic lives. It ships as its own
   change with request- **and response-**direction key sanitization.

## Consequences

- `rust-first-core` is **rescoped and split**: (a) move `rrf` to core + conformance
  vectors for gate/bm25/chunker; (b) the model-fulfiller protocol as a separate
  change. Moving the gate/tokenizer into Rust is explicitly **out** unless (4)
  triggers.
- The user's goal — "all languages at parity, stop triplicating" — is met by the
  conformance suite, which is *stronger* than relocation (it pins behavior for
  every current and future port, including native-lib paths that will never be
  Rust). This partially walks back "all deterministic logic to Rust" for the
  gate; the walk-back buys the ports-spec "hackable" value and removes the Unicode
  regression.
- `structural-code-graph` and `schema-extractors` keep their per-language graph
  work premised on "graph-build stays per-host" — which this ADR upholds.

## Alternatives considered

- **Move the gate to Rust (original `rust-first-core`).** Rejected: reverses an
  explicit reasoned decision, and the tokenizer Unicode-parity risk makes it a
  silent multilingual regression. A single source of truth isn't worth a gate that
  quietly disagrees with itself across languages.
- **Do nothing (keep three hand-written copies).** Rejected: drift on the cite-or-
  abstain logic is the highest-consequence drift in the system.
- **Conformance vectors + move the tokenizer only.** Deferred to (4): reasonable,
  but the tokenizer move still carries the Unicode risk and the "hackable" cost;
  try conformance-only first.
