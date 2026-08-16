# 0010 — Where a deterministic algorithm lives: Rust core vs. the ports

Status: proposed · 2026-08-11

## Context

CiteNexus ships a Rust core plus three ports: Python (the batteries-included
facade), Go and JavaScript (core at conformance parity). Every deterministic
algorithm therefore has a placement question, and the repo has never answered it
as a rule. It has answered it four different ways by accretion:

| Placement | Algorithms |
|---|---|
| **Rust only**, reached over FFI | extraction (pdf, ooxml, html, csv, xlsx, code, image), `to_markdown`, the Lance store, language detection — 15 `citenexus_*` exports in `rust/src/ffi.rs` |
| **Rust *and* all three ports** | RRF — `rust/src/rrf.rs`, `retrieve/fusion.py`, `golang/rrf/rrf.go`, `js/src/rrf/rrf.ts` |
| **Ports only**, no Rust | the faithfulness gate, BM25, the chunker, tokenize, structure |
| **Shared data, per-port code** | stopwords — canonical `conformance/stopwords.json`, then `//go:embed`ed as a copy in `golang/gate/`, hardcoded as a frozenset in `answer/verify.py` |

RRF existing in four places is the clearest symptom: nobody decided that, and
nobody can say which copy is authoritative. New work (ADR-0007's conflict
detection, ADR-0009's atomic-claim faithfulness) has to answer the placement
question immediately and has no rule to answer it with.

### What the 2026-08-11 stress test does and does not prove

`spikes/library-stress/` found the faithfulness gate accepting 9 of 9 adversarial
false answers, identically in Python, Go and JS — 27/27.

The intuitive reading is that triplication caused this and a single Rust
implementation would have prevented it. **That reading is wrong, and the
distinction is what this ADR turns on.** The three ports agreed perfectly. There
was no drift. `is_supported` is a *specification* defect — set containment is the
wrong predicate for entailment — and one shared implementation would have been
exactly as wrong, in one place instead of three. The conformance mechanism worked
as designed and faithfully pinned a bad spec.

So the stress test is strong evidence that deterministic logic is genuinely
triplicated and worth governing. It is **not** evidence for moving the gate to
Rust, and must not be cited as such.

### What consolidation actually buys, and costs

The real cost of triplication is not duplicated code — three copies of an
arithmetic formula are cheap and their divergence is caught by conformance
vectors. The real cost is **maintaining a language-dependent asset across three
different Unicode and regex stacks**: Python `re`, Go `regexp` (RE2, no
backtracking), and JS RegExp differ on word boundaries, property escapes and
normalization. That is where implementations diverge for reasons a fixture author
did not think to test.

Against that, purity in the ports is deliberate and load-bearing.
`golang/ingest/ingest.go:1` records the rationale explicitly: FFI sits behind the
`citenexus_ffi` build tag "so the pure port and CI stay clean and need no native
library." Today a plain `go get` yields a working gate and a statically
cross-compiled binary; plain ESM yields one that runs in a browser or a
Cloudflare Worker. Moving a hot-path algorithm into Rust makes the core guarantee
require a native library on every platform triple, aimed precisely at the users
who chose Go or JS for those properties.

## Decision

Placement is decided per algorithm by **what the algorithm carries**, not by
where it happens to be convenient.

**The rule — three tiers:**

1. **Structural / arithmetic → implement natively in each port.**
   Algorithms whose specification is arithmetic or set-and-span manipulation over
   already-tokenized input: RRF, BM25 scoring, fusion, containment predicates,
   ID derivation. Three implementations are cheap, divergence is mechanical, and
   conformance vectors catch it reliably. Purity is preserved.

2. **Language-dependent *data* → one canonical table in `conformance/`, code
   native.** Stopword sets, polarity markers, per-language thresholds. The table
   is the asset; the code reading it is trivial. This is the existing
   `conformance/stopwords.json` pattern, promoted from precedent to rule — with
   one amendment: per-port copies must be **generated** from the canonical file,
   never hand-maintained. Go's `//go:embed` of a copy is acceptable because the
   copy is byte-identical and checkable; Python's hardcoded frozenset is not, and
   is scheduled for conversion.

3. **Language-dependent *algorithms* → Rust core, reached over FFI.**
   Anything requiring real Unicode competence: segmentation (UAX #29 word,
   sentence and clause breaking), normalization, script detection, and all
   artifact parsing. Three hand-rolled implementations of a Unicode algorithm
   will diverge, and no practical fixture set catches it. Rust already owns this
   tier — extraction and `detect.rs` are here — so the tier exists; this ADR
   names it.

**Corollaries:**

- **No algorithm may live in both Rust and the ports.** The current RRF
  quadruplication is a defect against this rule. It resolves by classifying RRF
  as tier 1 (it is arithmetic) and **deleting `rust/src/rrf.rs`** along with the
  `citenexus_rrf` export — not by removing the port implementations. The Rust
  copy is the redundant one; the ports are the delivery surface.
- **Tier 3 placement requires evidence, not anticipation.** An algorithm moves to
  Rust when a prototype demonstrates the Unicode problem is real, not because it
  might be. Speculative FFI is how a pure port dies of a thousand conveniences.
- **Nothing on the hot answer path moves to tier 3 without an explicit
  distribution decision**, because it converts an optional native dependency into
  a mandatory one.

**Applying the rule to the open ADRs:**

| Work | Tier | Placement |
|---|---|---|
| ADR-0009 strengthened containment predicate | 1 | native, all three ports |
| ADR-0009 claim segmentation | **undecided — prototype first** | tier 1 if regex-over-punctuation suffices; tier 3 if it needs UAX #29 |
| ADR-0007 polarity marker tables | 2 | canonical `conformance/polarity.json`, generated into each port |
| ADR-0007 pairwise conflict scoring | 1 | native, all three ports |
| ADR-0008 reconciliation diff | 1 | native (Python facade first; it is set arithmetic over manifests) |

## Consequences

- ADR-0009's fix — the only finding that produces a confidently false, correctly
  cited answer — ships natively and is not blocked behind a re-architecture. That
  sequencing is the main practical win.
- The rust-first direction is neither adopted nor rejected wholesale. It is
  narrowed to tier 3, where its argument is strongest, and denied the tiers where
  its argument was really about code duplication rather than correctness.
- `rust/src/rrf.rs` and `citenexus_rrf` are removed. This is a breaking change to
  the FFI surface; per the 0.x policy the export is deprecated before removal.
  Any consumer calling it should be calling its own port's RRF.
- Python's hardcoded `_STOPWORDS` becomes generated from
  `conformance/stopwords.json`. Low risk, and it closes the one place where a
  linguistic table is hand-maintained today.
- The rule can be wrong at the margin, and the honest failure mode is tier 1
  swallowing something that belonged in tier 3 — a segmentation rule that looks
  like punctuation handling until a script without spaces arrives. Mitigation is
  the prototype requirement plus per-language conformance fixtures before any
  language is claimed as supported.
- This ADR governs *deterministic* logic only. Model calls remain injected,
  per-host, and outside the core, unchanged by anything here.
