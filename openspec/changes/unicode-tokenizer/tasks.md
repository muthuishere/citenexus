## 0. Collapse the third faithfulness gate (prerequisite)

- [x] 0.1 Red: smoke-pipeline tests for per-claim drop-not-fail and for a
      reordered claim (the private `_supported` accepted both)
- [x] 0.2 Point `smoke/pipeline.py` at `split_claims` + `is_supported_v2` and
      delete the private `_supported`
- [x] 0.3 Drop the duplicated `_STOPWORDS` / `_content_tokens` copy in favour of
      `verify.content_tokens` (identical 44-word table)
- [x] 0.4 Mirror the change in `scripts/gen_conformance.py::_hermetic_ask` so the
      generator and the pipeline cannot diverge
- [x] 0.5 Regenerate and confirm `conformance/cases/e2e_hermetic.json` is
      byte-identical (it is — the extractive FakeLLM emits one claim)

## 1. Correct the claim, ahead of the code

- [x] 1.1 README: "Multilingual RAG" → "Latin-script multilingual", plus a
      section naming the scripts that abstain and why
- [x] 1.2 `docs/SPEC-v6.md`: qualify the header and add a §11a script-support
      matrix with every non-Latin script marked "not supported — abstains"
- [x] 1.3 Docs site: `languages.mdx`, `index.mdx`, `domain-rag.mdx`
- [x] 1.4 `CLAUDE.md` scope paragraph
- [x] 1.5 Deliberately NOT corrected: CHANGELOG (a historical release record),
      and descriptions of the example corpus (which really is Latin-script)

## 2. The versioned tokenizer

- [x] 2.1 Red: per-script tests asserting v1 yields zero tokens and the gate
      rejects a verbatim quote of its own source
- [x] 2.2 Add `TOKENIZER_VERSION`, the sorted script range table, `script_of`
      (binary search, no regex) and the word-character category test
- [x] 2.3 Implement `tokenize_v2` — NFKC, casefold, maximal same-script runs
- [x] 2.4 Assert `tokenize_v2 == tokenize` on every ASCII vector
- [x] 2.5 Verify `tokenize` is untouched and byte-identical
- [x] 2.6 Add the sorted-table import assertion (a mis-sorted range would
      silently mis-classify through the binary search)

## 3. Segmentation for spaceless scripts

- [x] 3.1 Red: whitespace splitting yields one token per CJK sentence
- [x] 3.2 Implement character-bigram emission for `CONTINUOUS_SCRIPTS`
- [x] 3.3 Bigrams form within a script run only (Lucene CJKBigramFilter
      semantics); Hangul is excluded because Korean writes spaces
- [x] 3.4 Assert CJK sub-span containment holds and CJK reordering is still
      rejected — bigrams must not weaken the ordered-containment guarantee

## 4. Move the consumers onto v2

- [x] 4.1 `is_supported_v2` tokenizes with v2
- [x] 4.2 Add `content_tokens_v2` / `has_relevance_overlap_v2`; the strict flow
      uses them. `is_supported` / `has_relevance_overlap` stay frozen
- [x] 4.3 `storage/bm25.py` → v2 (this is half the over-determined abstention)
- [x] 4.4 `retrieve/structure.py` → v2
- [x] 4.5 Confirm every ASCII conformance vector is unchanged

## 5. `unsupported_script` as a real signal

- [x] 5.1 Add `EvidenceSignals.unsupported_scripts`, defaulted empty
- [x] 5.2 Red: a question in an unclaimed script must not return the
      evidence-absent refusal
- [x] 5.3 Refuse with `unsupported script: <name>` when the question carries an
      unclaimed script
- [x] 5.4 Never cite a passage in an unclaimed script; report it instead
- [x] 5.5 Report the signal on answered Results too
- [x] 5.6 Assert the evidence-absent refusal is still distinguishable

## 6. Tokenizer version per index

- [x] 6.1 `TokenizerManifest` with `is_stale`, defaulting to version 1
- [x] 6.2 `record_tokenizer_version` / `tokenizer_manifest` helpers
- [x] 6.3 Stamp on ingest in `IngestPipeline` and `SmokePipeline`
- [x] 6.4 Test that an unstamped partition reads as stale, not fresh

## 7. Per-script conformance vectors

- [x] 7.1 `conformance/cases/tokenize_v2.json`: one golden fixture per claimed
      script, each pinning tokens, v1 tokens (the defect), self-support,
      unrelated-rejection and the empty capability gap
- [x] 7.2 Generation FAILS when `SUPPORTED_SCRIPTS` and the fixture set disagree
      in either direction — the golden-fixture-per-script rule, mechanized
- [x] 7.3 An `unclaimed` half of the matrix pinning the reported capability gap
- [x] 7.4 `tests/test_conformance_tokenize_v2.py` runs the committed fixture
      against the real runtime, as the ports must
- [x] 7.5 Update the stale `multilingual.json` case NAMES, which described v1
      behavior ("query 'Straße' -> tokens stra + e")

## 8. Follow-up (NOT in this change)

- [ ] 8.1 Go and JS ports reproduce the two moved vectors natively
- [ ] 8.2 Rust core takes authorship per ADR-0011 §3
- [ ] 8.3 Khmer / Lao / Myanmar claims, or dictionary segmentation
- [ ] 8.4 Diacritic folding for Arabic and Hebrew
