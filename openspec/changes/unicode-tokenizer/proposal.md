## Why

The library says it is multilingual. Measured 2026-08-11:

```
English   tokens=  7  is_supported(verbatim quote of its own source) = True
Dutch     tokens=  8  is_supported(verbatim quote of its own source) = True
Japanese  tokens=  0  is_supported(verbatim quote of its own source) = False
Chinese   tokens=  0  is_supported(verbatim quote of its own source) = False
Arabic    tokens=  0  is_supported(verbatim quote of its own source) = False
Tamil     tokens=  0  is_supported(verbatim quote of its own source) = False
```

The cause is one line. `python/src/citenexus/tokenize.py` is `[a-z0-9]+` over
`.lower()` — the pinned SPEC-PORTS-v1 §4 contract, ASCII only. Any text without
Latin letters or digits produces an empty token list, `verify.py` short-circuits
on `bool(answer_tokens)` and returns `False`, and **the gate rejects a verbatim
quote of its own source**. The same tokenizer feeds BM25 and the structure
retriever, so lexical retrieval in those scripts also returns nothing: the
abstention is over-determined, and every answer in those scripts abstains.

This is not ADR-0009's failure. There the gate returns a confident wrong answer;
here it returns the pinned refusal — the safe direction, and "no ungrounded
claim" technically holds. But a library that abstains on 100% of Japanese,
Chinese, Arabic, Tamil, Thai, Hebrew, Greek, Korean and Cyrillic input while
advertising multilingual support is making a false claim about its capability,
and abstention is only honest when it means "the evidence isn't there", not "I
cannot read this script".

**Why it shipped.** The gate's multilingual test coverage is German. Every
language exercised anywhere in the gate suite is Latin-script. The tests are
correct and they pass; they never asked the question. "Multilingual" was
implemented and verified as *Latin-script multilingual*, and the distinction was
never written down.

Decisions: ADR-0011 (this change), ADR-0010 (placement, amended by ADR-0011 §3).

## What Changes

- **The claim is corrected first, ahead of any code.** README, `docs/SPEC-v6.md`
  §11a and the docs site say **Latin-script multilingual** and name the scripts
  that abstain. Documentation accuracy is not gated on the fix.
- Add `tokenize_v2` **alongside** the frozen `tokenize`. Unicode letter/number/
  mark classes rather than ASCII ranges; `str.casefold()` rather than `.lower()`.
  No regex — a character scan over a Unicode category lookup and an explicit
  script range table, because Python `re` has no `\p{L}` and Go RE2 and JS
  RegExp disagree on property escapes.
- **Segmentation, not classification, for scripts written without spaces.**
  Whitespace-splitting Chinese, Japanese or Thai yields one token per sentence,
  which makes BM25 and any containment predicate degenerate. Han, Hiragana,
  Katakana, Thai, Lao, Khmer and Myanmar are **character-bigram indexed** —
  standard, deterministic, no dictionary. Dictionary word-breaking is deferred.
- `is_supported_v2`, the relevance gate (`has_relevance_overlap_v2`), BM25 and
  the structure retriever move onto v2. `tokenize`, `is_supported` and
  `has_relevance_overlap` stay byte-identical.
- **`unsupported_script` becomes a real signal.** `EvidenceSignals.unsupported_scripts`
  plus a distinct `missing_evidence` reason, so a capability gap can never again
  be served as the evidence-absent refusal.
- **A script is CLAIMED, not detected-and-hoped.** `SUPPORTED_SCRIPTS` is an
  explicit allowlist; `conformance/cases/tokenize_v2.json` carries a golden
  fixture per claimed script; the generator raises if the two disagree.
- The tokenizer version is recorded per partition (`TokenizerManifest`), so an
  index built by an older tokenizer is detectable rather than silent.

## Capabilities

### New Capabilities
- `unicode-tokenizer`: the versioned Unicode tokenizer, bigram segmentation for
  spaceless scripts, the script range table and support allowlist, the
  per-script golden fixtures, and the per-index tokenizer stamp.

### Modified Capabilities
- `answer-flow-strict`: abstains with an explicit `unsupported script` reason
  instead of the evidence-absent refusal; reports `unsupported_scripts` on every
  Result; never cites a passage in an unclaimed script.

## Impact

- **Code:** `tokenize.py` (additive), `answer/verify.py` (additive `*_v2`),
  `answer/flow.py`, `answer/result.py` (one new defaulted field),
  `storage/bm25.py`, `retrieve/structure.py`, `storage/manifest.py`,
  `ingest/pipeline.py`, `smoke/pipeline.py`.
- **Fixtures (the port blast radius):** `conformance/cases/multilingual.json`
  (3 BM25 scores move, because BM25 now tokenizes with v2) and
  `conformance/cases/result_roundtrip.json` (one new empty field). New:
  `conformance/cases/tokenize_v2.json`. Every ASCII-only vector —
  `tokenize.json`, `bm25.json`, `faithful.json`, `structure.json`,
  `e2e_hermetic.json` — is unchanged, because v2 is identical to v1 on
  pure-ASCII input.
- **Ports:** Go and JS must follow for the two moved fixtures. Per ADR-0011 §3
  this is tier 3 for *authorship* and tier 1 for *delivery*: the ports keep a
  native implementation pinned by these vectors and do **not** gain a mandatory
  native dependency.
- **Re-indexing:** a corpus in an affected script must be re-tokenized to
  benefit. ADR-0008's hashing and rebuild machinery makes this surgical.
- **Not touched:** dictionary word segmentation, stemming or lemmatization in any
  language, script-specific stopword tables, RTL rendering, the judge, conflict
  surfacing, and the Go/JS/Rust trees.
