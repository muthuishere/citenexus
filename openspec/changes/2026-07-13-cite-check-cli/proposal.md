# Cite-Check CLI — retrieval-grounded cite-or-abstain gate over an evidence dir

Add `citenexus cite-check "<claim>" <evidence-dir>` — a deterministic gate that
reads a **real directory of evidence files itself**, retrieves the best-matching
passages for a free-text claim, and returns **CITED** (with source spans:
`file:block` + page) or **ABSTAIN** — no LLM call, no S3, no running CiteNexus
instance.

## Why this, and why now (the hole it closes)

The shipped `citenexus verify` (change `2026-07-06-verify-cli`) is a
faithfulness gate over **caller-supplied** passages. Its own proposal states the
boundary: *"v1 proves `tokens(claim) ⊆ tokens(passage)` for whatever passage
text the caller supplies. It does not prove the passage was genuinely extracted
from a named source document."* A claimant who fabricates a "This is real"
report can supply their own passage and `verify` returns PASS.

`cite-check` closes that trust boundary: the **caller supplies only the claim
string and a directory**; the tool — not the claimant — chooses which passages
(if any) support the claim, by extracting and retrieving over the directory's
files. You cannot fabricate the evidence directory into agreeing with an
ungrounded claim. This is the exact gate that catches a fabricated "done"
report before it ships.

## Passes both CiteNexus core gates (CLAUDE.md "where a new feature goes")

1. **Artifact-or-grounding gate** — it ingests artifacts (reuses the L3
   extractor dispatch over a directory) and improves grounded *evaluation* of a
   claim against that evidence. ✅
2. **Cite-or-abstain gate** — its entire output IS cite-or-abstain; it asserts
   no ungrounded claim, it abstains. ✅

It is a thin **facade** CLI (Python reference, per "Python is the facade, Go/JS
are core-only") over already-shipped primitives: `extract.dispatch`,
`answer.verify.is_supported` / `content_tokens`, `tokenize`. It reimplements no
gate and weakens none.

## Research grounding (thresholds)

- **AIS** (Rashkin et al., arXiv:2112.12870, CL 2023): output must be verified
  against an independent *provided source*; binary full-support. `cite-check`'s
  default is an AIS full-support proxy: CITE only when every content token of
  the claim appears in one retrieved passage.
- **RAGAS faithfulness** (arXiv:2309.15217): supported-claims / total-claims
  ratio — the model for the optional `--min-coverage <ratio>` relaxation.
- **FActScore** (arXiv:2305.14251): atomic-facts-supported / total ratio —
  same family; per-passage support as precision.
- **Abstention survey** (arXiv:2407.18418, TACL): abstain when evidential
  support is insufficient. `cite-check` fails safe — default AIS-strict, so a
  weakly-supported claim ABSTAINS rather than passing.

Lexical containment is a conservative lower bound on true support (misses
paraphrase), so CITED is high-precision / low-recall — the correct bias for a
"done"-gate where a false CITED is far costlier than a false ABSTAIN.

## Complementarity with the other organs

- **brain** — every `cite-check` verdict is recordable as a brain episode
  (`brain record` glue), so the fleet's memory accrues *audited* evidence of
  what was and wasn't grounded. Reward: CITED → positive, ABSTAIN → zero/neg.
- **huddle verifier** — the JSON verdict is a stable evidence artifact the
  huddle consumes when reviewing a "done" claim.
- **CEO loop** — the CEO calls `cite-check` (exit code 0=CITED / 3=ABSTAIN)
  before accepting ANY "done" report.

## Out of scope (kept small on purpose)

- No embedding/vector retrieval — the directory gate uses the deterministic
  lexical retriever (content-token overlap) so it stays hermetic and offline.
  A vector-backed variant is a follow-up that consumes the same seam.
- No Go/JS/Rust `cite-check` binary — the gate primitives already have port
  parity (`golang/gate`, `js/src/gate`); a thin binary over them is deferred,
  exactly as the `verify-cli` change deferred its port wrappers.
- No mutation of the pinned gate (`is_supported`) or the tokenizer.
