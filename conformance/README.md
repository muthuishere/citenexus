# Conformance fixtures

The shared, cross-language contract from
[`docs/SPEC-PORTS-v1.md`](../docs/SPEC-PORTS-v1.md) §10. The **Python
implementation is the reference** (§0): every file here is generated from its
internals by [`scripts/gen_conformance.py`](../scripts/gen_conformance.py) and
committed. Ports (Go, TypeScript, the Rust core) load these same files in
their test suites and must reproduce every expected output **exactly** —
identical tokens, identical fused order, identical scores to 1e-6, identical
eu_ids, byte-identical prompts.

## Files

| File | Contract (spec section) |
|---|---|
| `stopwords.json` | the fixed 44-word English stopword list (§4) — content-token gates only, never BM25 |
| `prompts.json` | the four pinned prompts, verbatim (§5): `grounded_answer`, `vision_describe`, `contextualize`, `reformulate` |
| `cases/tokenize.json` | lowercase `[a-z0-9]+` tokenizer (§4), incl. unicode/accent/number edges |
| `cases/bm25.json` | BM25-lite k1=1.5 b=0.75, zero-score rows dropped, input-order ties; scores rounded to 6 decimals (§4) |
| `cases/rrf.json` | RRF `1/(k+rank+1)`, k=60, zero-based rank, (−score, eu_id) order (§4) |
| `cases/faithful.json` | faithfulness gate (ALL answer tokens ⊆ passage tokens) + relevance gate (content-token overlap) (§4) |
| `cases/chunker.json` | recursive paragraph→line→sentence→word chunker with overlap tail (§4) |
| `cases/language.json` | the §11a answer-language fallback chain, one case per rung |
| `cases/eu_ids.json` | eu_id formats for the block builder (`doc::{order}`) and chunked builder (`doc::{order}::{i}`), plus a SHA-256 raw-checksum example (§3, §4) |
| `cases/vision_orchestration.json` | the two-phase vision seam (ADR-0005, §9): the ordered `emit` list of `PendingVisionRequest`s (data-URI + prompt + source_ref; the payload MIME is sniffed from the bytes — PNG vs JPEG pinned), the `fulfilled` records, the `assembled` figure EUs, and a `degrade` join where an unfulfilled request yields no EU — only the raw model call between emit and fulfill may differ per port |

Not yet generated (spec §10 lists them; they land with the port work):
`cases/result_roundtrip.json` and `cases/e2e_hermetic.json`.

## Regenerating

Fixtures are drift-guarded by `tests/test_conformance_fixtures.py`, which runs
in the default unit gate: if a pinned algorithm or prompt changes, the suite
fails until you consciously regenerate and review the diff:

```bash
uv run python scripts/gen_conformance.py
git diff conformance/
```

A deliberate change to any expected output is a **conformance-breaking change**
and requires a ports-spec version bump (§11).
