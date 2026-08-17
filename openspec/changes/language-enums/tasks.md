## 1. Python: the types

- [x] 1.1 Red: `Language.TAMIL == "ta"`, hashes equal, `json.dumps` → `"ta"`,
      `f"{...}"` → `ta`; same for `Script`
- [x] 1.2 Red: `Language.AUTO == "auto"` and is absent from `SEARCH_LANGUAGES`
- [x] 1.3 Red: the member set is exactly the 41 search codes + `auto`; the
      `Script` member set covers every script in `_SCRIPT_RANGES` + `unknown`
- [x] 1.4 Implement `citenexus/lang/codes.py`: `Language`, `Script`,
      `LanguageCode` / `ScriptCode` opt-in `Literal` aliases
- [x] 1.5 Export from `citenexus.lang` and the package root

## 2. Python: express the tables in the types

- [x] 2.1 Red: `SEARCH_LANGUAGES` keys are `Language`, `scripts` are `Script`,
      and `SEARCH_LANGUAGES["ta"]` still resolves
- [x] 2.2 Red: `SUPPORTED_SCRIPTS` / `CONTINUOUS_SCRIPTS` are `Script` sets and
      still answer `"latin" in SUPPORTED_SCRIPTS`
- [x] 2.3 Rewrite `tokenize.py`'s script sets and `_SCRIPT_RANGES` over `Script`
- [x] 2.4 Rewrite `lang/search.py`'s table over `Language`/`Script`
- [x] 2.5 Keep the two `!r` error messages byte-identical (coerce to `str`)

## 3. Python: accept both at every entry point

- [x] 3.1 Red: **the no-warning pin** — a raw-string `ask`/`retrieve` under
      `warnings.catch_warnings(record=True)` emits nothing and matches the
      enum call's result exactly
- [x] 3.2 Red: mixed `search_languages=("en", Language.TAMIL)` resolves
- [x] 3.3 Red: `MultilingualConfig(default_answer_language=Language.TAMIL)`
      round-trips to `"ta"` and equals the string form
- [x] 3.4 Widen annotations: `client.ask/retrieve/stream/_extra_queries`,
      `lang.fallback.resolve_*`, `lang.search.resolve_search_languages`,
      `answer/flow.py`, `answer/agentic.py`, `ingest/pipeline.py`,
      `config/schema.MultilingualConfig`
- [x] 3.5 Red: `UnsupportedSearchLanguageError` for `"tamiil"` raises with zero
      model calls (assert on a counting fake)

## 4. Conformance vector

- [x] 4.1 Add `_language_code_cases()` to `scripts/gen_conformance.py` and
      register `cases/languages.json`
- [x] 4.2 Generate and commit the fixture
- [x] 4.3 Run `tests/test_conformance_fixtures.py` — **no previously committed
      fixture may move**; stop and report if one does

## 5. Go port

- [x] 5.1 Red: `golang/lang` test asserting the constant set == the fixture
- [x] 5.2 Implement `golang/lang/codes.go`: `type Language string`,
      `type Script string`, the constants, `SearchLanguages()`
- [x] 5.3 Red: `var l Language = "ta"` compiles (string-assignability pin)
- [x] 5.4 `go clean -testcache && go test ./...` exit 0

## 6. JS port

- [x] 6.1 Red: `js/src/lang/codes.test.ts` asserting the const object == the
      fixture, and that a plain string is assignable to `LanguageLike`
- [x] 6.2 Implement `js/src/lang/codes.ts` (`const` object + union type)
- [x] 6.3 Extend `scripts/gen-tables.mjs` to bundle the language table
- [x] 6.4 Export from `js/src/index.ts`; `npm test` + build/typecheck clean

## 7. Verify

- [x] 7.1 `cd python && task check` — 1472 + new, 5 skipped, no verdict change
- [x] 7.2 `uv run python ../spikes/library-stress/stress.py` — 4 probes PASS
- [x] 7.3 Both port flow probes exit 0
