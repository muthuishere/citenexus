## 1. Spike (done before any code)

- [x] 1.1 `spikes/multilingual-search/spike.py` — offline, deterministic, library's
      own tokenizer/BM25/fusion; M1 cross-lingual recall, M2 script claims, M3 cost,
      M4 fusion balance, M5 dead endpoint, M6 recall lift
- [x] 1.2 `spikes/multilingual-search/NOTES.md` with the numbers and an explicit
      "what would make this wrong"
- [x] 1.3 `docs/adr/0013-multilingual-search-fanout.md` (proposed)

## 2. The language / script capability table

- [x] 2.1 Red: `resolve_search_languages(("en",))` returns English, unchanged default
- [x] 2.2 Red: an unsupported script (Telugu) raises, naming language AND script
- [x] 2.3 Red: an unknown code raises rather than being guessed
- [x] 2.4 Red: the table's script names come from ADR-0011's vocabulary, and every
      claimed language's script is in `SUPPORTED_SCRIPTS`
- [x] 2.5 Implement `lang/search.py`: `SearchLanguage`, `SEARCH_LANGUAGES`,
      `UnsupportedSearchLanguageError`, `resolve_search_languages`

## 3. Generalise the reformulator

- [x] 3.1 Red: the `"en"` prompt string is byte-identical to today's
- [x] 3.2 Red: the cache is keyed by `(query, language)` — one call per pair
- [x] 3.3 Red: a failure is cached under the same key (one attempt per pair)
- [x] 3.4 Implement the `language` parameter, the display-name-driven prompt, and
      the pair-keyed cache in `retrieve/reformulate.py`
- [x] 3.5 Update the `Reformulator` protocol and the in-repo fake

## 4. Fan out from the client

- [x] 4.1 Red: `search_languages=("en",)` issues exactly today's queries
- [x] 4.2 Red: fan-out ordering is original-first then `search_languages` order,
      de-duplicated, deterministic across repeats
- [x] 4.3 Red: fan-out is additive — no candidate lost versus the single-language path
- [x] 4.4 Red: a dead reformulation endpoint degrades to single-query, no error
- [x] 4.5 Red: N>1 with no reformulator raises; `("en",)` with no reformulator works
- [x] 4.6 Red: the refusal happens before any model call
- [x] 4.7 Implement `search_languages` on `ask()` and `retrieve()` and the
      per-language `_extra_queries`

## 5. `answer_language="auto"`

- [x] 5.1 Red: `"auto"` and `None` produce the same answer language
- [x] 5.2 Red: `None` still follows the §11a fallback chain unchanged
- [x] 5.3 Red: an explicit code still forces the answer language
- [x] 5.4 Normalize `"auto"` to `None` at the `ask` / `_deep_ask` boundary

## 6. Guarantee tests

- [x] 6.1 Red: a citation reached via fan-out is verbatim in its source language
- [x] 6.2 Red: a reformulation never appears in the answer or the citation
- [x] 6.3 Red: unsupported content still abstains with fan-out on

## 7. Gates

- [x] 7.1 `task check` green — only added tests, no existing verdict changed
- [x] 7.2 `spikes/library-stress/stress.py` — all four probes PASS
- [x] 7.3 No conformance fixture regenerated (no pinned algorithm changed)
