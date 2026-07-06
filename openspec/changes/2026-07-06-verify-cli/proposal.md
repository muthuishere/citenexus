# Verify CLI

Productize the existing deterministic faithfulness gate
(`citenexus.answer.verify.is_supported` / `has_relevance_overlap`) as a
standalone, sellable verifier: `citenexus verify`. It takes an answer's claims
plus their cited passages — as inline JSON, no running CiteNexus instance, no
S3, no LLM call — and proves each claim's tokens are contained in its cited
passage, deterministically. Ships as a CLI (Python reference), a library call,
and a GitHub Action / CI gate. We dogfood it as our own output gate.

This reuses the pinned gate algorithm byte-for-byte; it does not reimplement
or weaken it. The faithfulness gate itself is untouched by this change.

## Positioning, precisely

The wedge vs LLM-judge incumbents (Ragas/TruLens/Galileo) is **deterministic,
token-level containment — no model call, same input always yields the same
verdict.** This is *not* a byte-level proof against a source document: v1
proves `tokens(claim) ⊆ tokens(passage)` for whatever passage text the caller
supplies. It does **not** prove the passage was genuinely extracted from a
named source document — that would require the caller to also supply a
checksum of the source bytes for the CLI to verify against, which v1 makes an
**optional** field (`citation.source_checksum`) rather than a hard requirement,
to keep the zero-I/O, zero-RAG-dependency contract intact. The spec below
states this scope boundary as a requirement, not just a caveat in prose, so it
can't quietly erode.

## Prerequisite cleanup folded into this change

`tokenize()` — the pinned SPEC-PORTS-v1 §4 tokenizer that four production
modules (`answer/verify.py`, `storage/bm25.py`, `retrieve/structure.py`,
`smoke/pipeline.py`) already depend on — currently lives in
`citenexus.testing.fakes`. Before exposing this gate in a customer-facing CLI,
it moves to `citenexus.tokenize` (parity with `golang/tokenize`,
`js/src/tokenize`); `testing.fakes` re-exports it so existing test imports and
`FakeEmbedding` keep working unchanged. No behavior change.

## Out of scope for this change

- **Rust**: per `docs/SPEC-PORTS-v1.md` §9 ("DECIDED"), `citenexus-core` is the
  shared *engine* (extract/store/detect), not a 4th independent port. Moving
  "token gates" into the Rust core behind FFI is an already-planned v2
  migration ("one implementation replaces cross-language conformance for
  them") — a separate, larger initiative with its own C-ABI/cgo/napi-rs work.
  Bolting a standalone `rust/src/gate.rs` onto this change would add a 4th
  duplicate implementation working against that plan. Not built here.
- **Go/TS `verify` CLI wrappers**: `golang/gate` and `js/src/gate` already
  carry the identical gate primitives; adding thin CLI binaries over them is
  straightforward follow-on work, deferred to a follow-up change so this one
  stays small and independently demoable.
- **GitHub Action PR-annotation polish and pricing/public release**: the
  Action ships as our own dogfooded CI gate; public release + pricing is
  owner-gated per the standing company-flow rule.
