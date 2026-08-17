# Documentation accuracy audit — `site/src/content/docs/`

Audited 2026-08-17 against `main` @ `04c0bbc`, release **0.10.0**. 36 pages, ~3,960 lines.
Every finding below was checked against source and carries `file:line` on both sides.

**Result: 34 false claims across 24 of 36 pages.** Links and slugs are clean.
Two pages should be rewritten rather than patched.

The standing rule this audit enforces: *we never want wrong at all, it's okay we
can say don't know.* A doc that overclaims is the product failing at the thing it
sells. Findings are ranked by that harm, not by page order.

---

## Summary table

| Page | Verdict |
|---|---|
| `index.mdx` | **WRONG** (8) |
| `concepts.mdx` | **WRONG** (4) |
| `scope.mdx` | **WRONG** (3) |
| `install.mdx` | **WRONG** (4) |
| `quickstart.mdx` | minor (2) |
| `signals.mdx` | minor (2) |
| `ask.mdx` | **WRONG** (5) |
| `result.mdx` | **WRONG** (6) |
| `languages.mdx` | **WRONG** (3) |
| `authority.mdx` | minor (3) |
| `reranking.mdx` | clean (1 omission) |
| `evaluate.mdx` | **WRONG** (3) |
| `benchmark-law.mdx` | **WRONG** (5) |
| `models.mdx` | **WRONG** (2) |
| `custom-endpoints.mdx` | minor (1) |
| `providers.mdx` | **WRONG** (2) |
| `ingest.mdx` | **WRONG** (3) |
| `bulk-ingest.mdx` | minor (1) |
| `vision.mdx` | minor (3) |
| `revoke.mdx` | **clean** |
| `file-based.mdx` | minor (2) |
| `s3.mdx` | clean (2 nits) |
| `access.mdx` | **clean** — most accurate page in the set |
| `graph.mdx` | minor (2) |
| `wiki.mdx` | clean (1 nuance) |
| `domain-rag.mdx` | **WRONG** (3) |
| `scenarios/index.mdx` | **clean** |
| `scenarios/contract-review.mdx` | **WRONG** (1, severe) |
| `scenarios/conflicting-sources.mdx` | minor (3) |
| `scenarios/subject-scope.mdx` | **clean** — every number verified |
| `scenarios/regulated-audit.mdx` | **WRONG** (1 non-running snippet) |
| `scenarios/right-to-erasure.mdx` | **WRONG** (1 non-running snippet) |
| `scenarios/multilingual-desk.mdx` | **WRONG** (1) |
| `scenarios/multilingual-corpus.mdx` | **WRONG** (3) |
| `scenarios/evaluate-a-corpus.mdx` | **REWRITE** (3) |
| `scenarios/support-assistant.mdx` | minor (1) |

---

## Tier 1 — false capability claims

These assert a guarantee the library does not provide. Fix first.

### 1.1 `acl` is documented as tenant isolation; it enforces nothing

- **Doc:** `scenarios/contract-review.mdx:79-89` — "**Partitions** keep matters apart, so a
  question about one client can never cite another's paper", illustrated with
  `rag.ingest("msa.pdf", acl=["matter-4471"])`.
- **Source:** `acl` is written to `EvidenceUnit.acl`
  (`python/src/citenexus/evidence/unit.py:91` via `ingest/pipeline.py:146,176-184`) and read by
  **nothing** — `grep '\.acl\b' python/src/citenexus/{retrieve,answer,access}/` returns zero hits.
  Isolation actually comes from `PartitionPath` (`client.py:121,158`) plus the
  `allowed_partitions` hard pre-filter (`access/prefilter.py:31-36`).
  `access.mdx` states this correctly ("carried, not enforced"); this page contradicts it.
- **Correction:** use one `CiteNexus(..., partition=PartitionPath.of(("matter","4471")))` per
  matter. State plainly that `acl` is carried metadata and enforces nothing. A reader who
  ships the snippet as written believes they have tenant isolation and does not.
- **Harm:** highest. This is a confidentiality claim, in the contract-review scenario,
  that the code does not honour.

### 1.2 `evaluate()`'s blank-`expected` semantics are documented backwards — on four pages

- **Doc:** `evaluate.mdx:32-34` ("a row with an **empty** `expected` … answering it does not
  earn expected-support"); `index.mdx:151-154` ("a model that answers when it should refuse
  **scores worse**"); `domain-rag.mdx:40-49`; `scenarios/evaluate-a-corpus.mdx:26-28,48-53`.
- **Source:** `python/src/citenexus/evaluate.py:76-77` —
  `if not expected: return result.evidence.decision is Decision.answered`.
  An empty `expected` earns expected-support **iff the row was ANSWERED**. A correct
  refusal earns nothing and *lowers* `expected_support_rate`. Recorded as a known
  limitation at `examples/law-authority/RESULTS.md:60,201-203`, which is exactly why
  that benchmark reads 45%.
- **Correction:** `evaluate()` **cannot score abstention** — blank-`expected` rows reward
  answering. To gate on must-refuse rows, drive `ask()` yourself and assert
  `result.evidence.decision is Decision.refused`.
- **Harm:** the docs tell users to build their refusal regression gate on a metric that
  scores refusal backwards. Every "prove it abstains" instruction on the site is wrong.

### 1.3 Every citation is advertised with a `bbox` that is always `None`

- **Doc:** `index.mdx:3,33` (`bbox [72,144,540,166]` shown in the hero citation card),
  `concepts.mdx:19-21,74-75`, `ask.mdx:20`, `result.mdx:74`, `evaluate.mdx:47`
  ("its bbox sources"), `scenarios/contract-review.mdx`, plus `astro.config.mjs:19,29`
  (site description and llms.txt: "the exact quote, page and bbox").
- **Source:** `SourceRef.bbox` exists on the model (`answer/result.py:101`) and is populated at
  extraction (`extract/pdf.py:276,295` → `evidence/builder.py:48`), but the ingest row schema
  persists only `page` (`ingest/pipeline.py:216`), `Candidate` has no bbox field
  (`retrieve/types.py:28-52`), and **no `bbox=` is passed at any `SourceRef(...)` or
  `ProvenanceEntry(...)` construction on the answer path** — `grep 'bbox=' python/src/citenexus/answer/`
  returns zero hits (`flow.py:361-368,454`; `agentic.py:383,500`).
- **Correction:** remove bbox from every citation example and from the site description.
  Truthful: `cited to employee-nda.pdf · page 3`. If mentioned at all: "bbox is captured at
  extraction but is not yet carried onto `Result.sources`."
- **Harm:** it is the site's single most repeated concrete proof-point, and it is inert.

### 1.4 `result.mdx` says conflict surfacing is not implemented; it is, and it changes answers

- **Doc:** `result.mdx:89-95` — "the current extractive flow does **not** populate them — today
  every result carries `conflicts = ()` and `conflicts_detected = 0`"; also `:40,63` ("reserved").
- **Source:** live since 0.10.0 — `answer/flow.py:271` `find_conflicts(...)`,
  `:394 conflicts_detected=len(conflict_pairs)`, `:410 conflicts=surfaced`, and critically
  `:344-355`: **strict mode ABSTAINS** on a conflict touching the cited passage
  (`_conflict_abstention`, `:427-478`). Deep-ask likewise (`agentic.py:408-453,517-523`).
- **Correction:** strict abstains and cites both sides; `normal` answers and lists the
  conflicts; `exploratory` records the count only. Conflicts are never resolved by rank (ADR-0007).
- **Harm:** a reader wires monitoring on `conflicts_detected`, is told it is always 0, and
  ignores the field — missing the one signal that says the corpus contradicts itself. It also
  hides a live abstention path, so an unexplained refusal looks like a bug.

### 1.5 `LanguageConfig(translate_citations=True)` — the class does not exist and the flag is dead

- **Doc:** `languages.mdx:90-106`, documented as a working knob.
- **Source:** there is no `LanguageConfig` anywhere in the repo — the field lives on
  `MultilingualConfig` (`config/schema.py:247`, flag at `:263`), so the import line raises
  `ImportError`. And `translate_citations` is **read nowhere** outside its declaration
  (`grep -rn translate_citations python/src/` → `schema.py:263` only), and nothing ever sets
  `SourceRef.translation` (`grep -rn 'translation=' python/src/citenexus/` → zero hits), so
  `SourceRef.translation` is always `None`.
- **Correction:** rename to `MultilingualConfig` and mark the knob declared-but-not-implemented,
  or delete the section. Do not document a translation feature that cannot run.

### 1.6 "The Go and JavaScript ports are Latin-script only" — false, and it understates the ports

- **Doc:** `languages.mdx:3,49-54` and the whole "Go / JS → abstains" column at `:22-35`;
  `scenarios/multilingual-desk.mdx:98-102`; `scenarios/multilingual-corpus.mdx:198-201`;
  `index.mdx:53-54` ("13 of them in Python, Latin-script in the Go and JS ports").
- **Source:** both ports ship **and use** the Unicode tokenizer v2 with the *same* 14-script
  claimed set, loaded from the shared canonical table:
  Go `TokenizeV2` (`golang/tokenize/tokenize_v2.go:282`, table `golang/tokenize/scripts.json`,
  `SupportedScripts()` `:87`) drives BM25 (`golang/bm25/bm25.go:45,53`) and the gate
  (`golang/gate/gate.go:65-75`, `golang/gate/verify_v2.go:226-227`);
  JS `tokenizeV2` (`js/src/tokenize/tokenize-v2.ts:225`) drives `js/src/bm25/bm25.ts:36,39` and
  `js/src/gate/verify-v2.ts:151-152`, `gate.ts:30-60`.
- **Correction:** "The ports' pinned tokenizer, BM25 and faithfulness-gate predicate are
  Unicode-aware at parity (the same 14 claimed scripts). Only the frozen v1 `[a-z0-9]+`
  tokenizer is ASCII, and it is no longer what those algorithms call — it survives solely in
  the ports' hermetic `ask()` demo."
- **Note:** this is an *under*claim, but still a false statement, and it wrongly tells Go/JS
  users their non-Latin corpus cannot work.

### 1.7 The 0.10.0 gate fix is claimed at cross-port parity; the ports' answer path still runs the old predicate

- **Doc:** `index.mdx:172-174` — "**every** deterministic decision is byte-for-byte identical
  across Go, JavaScript, and Python"; `install.mdx:36-38` ("byte-for-byte parity");
  `concepts.mdx:32-36`. Reinforced by `CHANGELOG.md:13-30`, which reports the defect as
  "identically in Python, Go and JavaScript" and reads as though all three were fixed.
- **Source:** Python's answer flow uses the new predicate — `answer/flow.py:28,310`
  (`is_supported_v2`). The ports do **not**: `golang/answer/askwith.go:135,153` calls the frozen
  `gate.HasRelevanceOverlap` / `gate.IsSupported`, and `js/src/answer/answer.ts:18,87,240` calls
  the frozen `isSupported`. The v2 predicate exists in both ports
  (`golang/gate/verify_v2.go:225`, `js/src/gate/verify-v2.ts:150`) but has
  **zero callers outside its own package and tests** in either language
  (`grep -rn IsSupportedV2 golang/ | grep -v _test | grep -v golang/gate` → empty; same for JS).
  The freeze is deliberate — `golang/answer/answer.go:9-11` pins `Ask` byte-for-byte to
  `conformance/cases/e2e_hermetic.json` — but the docs do not say so.
- **Correction:** "Every *pinned* algorithm is byte-for-byte identical (tokenize v1+v2, BM25,
  RRF, chunker, lang chain, euid, the frozen gate). The ADR-0009 per-claim ordered/polarity
  gate is **Python-only on the answer path today**; the ports ship the predicate but their
  `ask()` still runs the frozen one."
- **Harm:** this is the release's headline safety fix — the predicate that accepted **9 of 9**
  false answers. Claiming parity tells a Go or JS user they have a fix they do not have.

### 1.8 `signals.mdx` promises signals "never reject a call"; two paths raise

- **Doc:** `signals.mdx:3,32-38` — "Gating builds and queries — it never rejects a call";
  "Declaring `signals` does not raise or block a call."
- **Source:** (a) `config/signals.py:42-50` — `resolve_signals` raises `ValueError` on an
  unknown signal name; (b) `code/facade.py:132-137` — `rag.code.ingest_from(...)` **raises** if
  neither `graph` nor `community` is declared, and `rag.schema` enforces the same
  (`client.py:499-504`).
- **Correction:** "An absent signal skips its build and its retriever — `ingest()` and `ask()`
  never raise over it. Two exceptions: an unknown signal name raises `ValueError` at
  construction, and `rag.code` / `rag.schema` raise if `graph` (or `community`) is not declared."

### 1.9 `scope.mdx` says code ingestion lives elsewhere; `rag.code` ships

- **Doc:** `scope.mdx:23-24` — "**Not a code-comprehension tool** — guessed call-graph edges
  would betray cite-or-abstain, so code graphs live elsewhere."
- **Source:** `client.py:481-491` exposes a public `code` property →
  `code/facade.py:1-17` (`rag.code.ingest_from(folder | git)`, `_CODE_EXTENSIONS = {".py",".go"}`
  at `:36`), with a structural extractor (`rust/src/extract/code.rs`,
  `python/src/citenexus/extract/code.py`) and **explicit per-edge confidence**
  (`graph/store.py:66`). Same for `rag.schema` (`client.py:494-506`).
- **Correction:** keep the boundary but state it accurately — CiteNexus ingests source and
  schema as citable Evidence Units and labels edge confidence rather than asserting guesses;
  what lives elsewhere is the *product* (repo chat, call-graph analytics, IDE surfaces).
  Also add the typed intake verbs to the "It is" list at `:10-18`, which currently describes a
  narrower library than ships.

### 1.10 `domain-rag.mdx` and `benchmark-law.mdx` say authority weighting does not exist

- **Doc:** `domain-rag.mdx:61-69` — "no jurisdiction / precedence / source-credibility
  weighting… This is architectural, not a tuning knob"; `benchmark-law.mdx:71,92-97` —
  "**tracked as future work, not a knob you can turn today**".
- **Source:** ADR-0004 shipped. `ingest(..., authority={"authority_tier": …})`
  (`client.py:432-444`), `select_by_authority` applied after grounding and before generation
  (`answer/flow.py:236-262`), signals `authority_tier` / `authority_floor_applied`
  (`answer/result.py:84-85`), config at `config/schema.py:222-244`. It is merely *unranked by
  default* (`AuthorityPolicy.unranked()`, `client.py:207-209`).
  `benchmark-law.mdx:92-97` also gets the architecture backwards: the floor is deliberately
  **not** fed into fusion/rerank — applying it after grounding is the whole point of ADR-0004.
- **Correction:** past tense, and: "unranked unless you attach `authority=` at ingest and set a
  floor." Fix the fusion/rerank sentence.

### 1.11 Trust modes documented with behaviour that is not implemented

- **Doc:** `ask.mdx:43-45` — `strict` "minimum-sources enforced", `exploratory` "weak evidence
  may be summarized, with any speculation labeled".
- **Source:** the only mode branches in `answer/flow.py` are conflict abstention (`:344`,
  strict only) and conflict surfacing (`:402`, normal only), plus authority
  (`answer/authority.py:80-110`). `min_sources_strict` is declared at `config/schema.py:218`
  and **read nowhere in `python/src/`**. Nothing labels speculation.
- **Correction:** all three modes run the same extractive, per-claim-gated flow; they differ
  only in the authority floor/tie-break and conflict handling. Drop minimum-sources and
  labelled speculation, or mark them unimplemented.

### 1.12 `providers.mdx`: "no generator → the fake generator fills in" — Python raises

- **Doc:** `providers.mdx:134-138` — "pass an embedder and no generator and the deterministic
  fake generator fills in. The test suite pins both cases."
- **Source:** `client.py:934-942` `_require_answer()` raises
  `ValueError("ask()/stream()/evaluate() need an answering model … retrieve() works without one.")`.
  The fake-generator fallback is **port** behaviour (`golang/answer/askwith.go:63-68`,
  `js/src/answer/answer.ts:189`). Only the no-embedder case is pinned
  (`python/tests/test_third_party_provider.py:269-274`); there is no no-generator `ask()` test.
- **Correction:** "Generator, no embedder → lexical-retrieval answer (pinned). No generator →
  the Python facade is search-only: `retrieve()` works, `ask()` raises. The ports fall back to
  their deterministic fake."

### 1.13 `ingest.mdx`: "extraction runs in the shared Rust core" — not in Python

- **Doc:** `ingest.mdx:70-71` — "Extraction runs in the shared Rust core, so a PDF or XLSX
  extracts byte-identically whether you call from Go, JavaScript, or Python."
- **Source:** the Python reference never touches the core — `extract/pdf.py:8` imports
  **pdfplumber**, `extract/xlsx.py:15` imports **openpyxl**, and there is **no `ctypes` anywhere
  in `python/src/citenexus/`** (`grep -rn ctypes python/src/citenexus/` → empty; it appears only
  in `python/tests/core/test_rust_*_parity.py`). Only Go/JS call `citenexus_extract`
  (`rust/src/ffi.rs:38`; `golang/core/core.go:77`, `js/src/core/core.ts:173`). XLSX byte-identity
  is test-pinned (`python/tests/core/test_rust_parity.py:176-184`); **PDF has no parity test and
  no conformance case**.
- **Correction:** "Go and JS extract through the shared Rust core; the Python reference uses
  pdfplumber/openpyxl and is held to the Rust twin by parity tests (xlsx today; pdf not yet pinned)."

### 1.14 `support-assistant.mdx`: conversation memory is not ACL-scoped

- **Doc:** `scenarios/support-assistant.mdx:63-64` — "partition- **and ACL-scoped**".
- **Source:** partition-scoped ✓ (`MemoryStore(self._backend, self.partition, …)`,
  `client.py:168`) and keyed by `conversation_id` (`client.py:944-950`), but there is no ACL
  scoping anywhere — `acl` is only carried on `EvidenceUnit` (`evidence/unit.py:91`).
- **Correction:** drop "and ACL-".

### 1.15 `conflicting-sources.mdx`: conflict detection claimed as pinned across ports

- **Doc:** `scenarios/conflicting-sources.mdx:53-58` — "reproducible and **pinned by the
  cross-language conformance suite**"; `:55-57` lists "negation asymmetry, mismatched numeric
  and **date** literals".
- **Source:** vectors exist (`conformance/cases/conflict.json`) but **no port implements
  detection** — Go and JS only declare the fields (`golang/result/result.go:49,130`;
  `js/src/result/result.ts:39,107`). And there is no date rule: the rules are antonym pairs
  (`conflict.py:246-249`, omitted from the doc), negation parity, and numeric divergence
  (`:99-111,254-262`) — dates only when they read as digit-leading numbers.
- **Correction:** "Python today; the vectors are published so the ports can be held to them."
  Rewrite the rule list as "antonym pairs, negation parity, and numeric-value divergence
  (dates only when they read as numbers)."

---

## Tier 2 — stale claims the 0.10.0 release invalidated

### 2.1 Three pages tell users the release is not published and to build from source

- **Doc:** `authority.mdx:8-11`, `providers.mdx:8-11`, `scenarios/multilingual-corpus.mdx:8-11` —
  "the published packages are still **0.9.0**. Install from source until 0.10.0 ships."
- **Source:** queried live — PyPI `citenexus` `info.version` = **0.10.0**; npm
  `@muthuishere/citenexus` `dist-tags.latest` = **0.10.0**. Repo agrees
  (`python/pyproject.toml:5`, `js/package.json:3`, `rust/Cargo.toml:3`,
  `python/src/citenexus/__init__.py:53`), tags `v0.10.0` / `golang/v0.10.0` exist,
  `CHANGELOG.md:13`.
- **Correction:** delete all three asides (or reduce to "requires ≥ 0.10.0").
- **Harm:** actively costs every reader a from-source build for no reason.

### 2.2 "13 scripts" — it is 14

- **Doc:** `index.mdx:53-54`; also `README.md:50` (outside `site/`, same error).
- **Source:** `SUPPORTED_SCRIPTS` = 14 — arabic, bengali, cyrillic, devanagari, greek, han,
  hangul, hebrew, hiragana, katakana, latin, tamil, telugu, thai
  (`python/src/citenexus/tokenize.py:214-231`; `conformance/cases/tokenize_v2.json`
  `supported_scripts`). `languages.mdx:8` and `multilingual-desk.mdx:72` already say 14.
- **Correction:** 14, and per §1.6 the same 14 in Go and JS.

### 2.3 `ask()` signature is missing two shipped parameters

- **Doc:** `ask.mdx:27` — `ask(question, *, mode, k, answer_language, conversation_id)`.
- **Source:** `client.py:659-668` adds `strategy: str = "strict"` and
  `search_languages: Sequence[str] = DEFAULT_SEARCH_LANGUAGES` (`client.py:107` = `("en",)`).
- **Correction:** add both. Note `strategy="deep"` runs the agentic loop (`client.py:697-710`)
  and **raises `UnsupportedSearchLanguageError`** if `search_languages` differs from the default
  (`:698-702`); any other `strategy` raises `ValueError` (`:709`).

### 2.4 `result.mdx`: `answer_language` described wrongly, four `EvidenceSignals` fields missing

- **Doc:** `result.mdx:34` — "the query's language — guaranteed, independent of evidence
  language". `:53-64` omits fields.
- **Source:** it is the **caller-stated** language via a four-rung chain — explicit code →
  `"auto"` detection *of the question* → conversation language → `default_answer_language`
  (`"en"`, `client.py:129`; `lang/fallback.py:44-70`). Unset is a fixed default, not the query's
  language. Missing signals: `unsupported_scripts` (`answer/result.py:75`),
  `authority_tier` (`:84`), `authority_floor_applied` (`:85`), `loop` (`:88`, deep only).
  Also `:38` says "the cited passages" (plural) — strict returns exactly one
  (`flow.py:361-367,406` `sources=(source,)`).
- **Correction:** state the four-rung chain, add the four fields, and say strict cites one source.

### 2.5 `install.mdx`: wrong Go version and a cgo claim that does not apply to `ask`

- **Doc:** `install.mdx:15` — "the deterministic core + `ask` over a corpus, **via cgo over the
  shared Rust engine**", "**Go 1.23**".
- **Source:** `golang/go.mod:3` says **go 1.26**. `golang/answer/answer.go:46` and
  `askwith.go:61` are **pure Go**, importing only `golang/result` — no cgo. The cgo binding
  (`golang/core/core.go`) covers only extract / to_markdown / rrf / lid.176 / Lance store, sits
  behind `//go:build citenexus_ffi` (`:1`) and needs `cd rust && cargo build --release` first (`:7-9`).
- **Correction:** Go 1.26; "pure-Go core + `ask`/`AskWith`. Binary extraction, lid.176 detection
  and the Lance store are opt-in via cgo (`-tags citenexus_ffi`, after building the Rust cdylib)."
- **Related:** `install.mdx:36-38` and `index.mdx:106-116` list "extraction, language detection"
  as pure-port features. Both require the opt-in native binding, and `js/package.json`
  `files: ["dist"]` ships **no** binary — an npm consumer must build the cdylib themselves or
  set `CITENEXUS_CORE_LIB` (`js/src/core/core.ts:25-37`; `koffi` is an optionalDependency).

### 2.6 `models.mdx`: the "reference example" it describes does not exist

- **Doc:** `models.mdx:35-36` — "The reference example runs entirely on local Ollama
  (`bge-m3` + `qwen2.5` + `bge-reranker-v2-m3`)."
- **Source:** there is no `example/` directory. The two shipped examples are
  `examples/multilingual` and `examples/law-authority`, both on **hosted Jina + Gemini**
  (`examples/law-authority/run.py:10`, `examples/multilingual/run.py:132-145`).
  `python/Taskfile.local.yml:3-4`: "The DEFAULT example stack is cheap + hosted". The Ollama
  reranker is `xitao/bge-reranker-v2-m3` (`python/Taskfile.local.yml:86-91`).
- **Correction:** "The examples run on hosted Jina + Gemini; `task local:ollama:up` pulls an
  all-local variant (bge-m3, qwen2.5, xitao/bge-reranker-v2-m3)."
- **Adjacent repo bug (not a doc fix):** `python/Taskfile.local.yml:19` has `dir: example`,
  pointing at a directory that does not exist.

### 2.7 `benchmark-law.mdx` headline numbers are the pre-floor run, contradicting the committed results

- **Doc:** `benchmark-law.mdx:33-38` — "answered/refused **5 / 6**", "answer-when-grounded 50%
  (4/8)", "abstain-when-no-evidence 67% (2/3)".
- **Source:** those are the **v0.9.0 pre-floor** column of `examples/law-authority/RESULTS.md:37-41`.
  The committed `examples/law-authority/results.json` is post-floor: `answered 6, refused 5,
  answer_when_grounded 0.75, abstain_when_no_evidence 1.0`. A reader following the "Reproduce it"
  block at `:101-107` gets numbers unlike the table.
  Separately, `authority.mdx:198-203` quotes the *v0.10.0 pre-floor* column (33%) as "before"
  while `benchmark-law.mdx:37` quotes the *v0.9.0* column (67%) as "before" — **the two pages
  contradict each other on the same word.**
- **Correction:** label each table with its exact baseline version, and align the two pages.

### 2.8 `graph.mdx` / `signals.mdx`: build timing and queue wiring

- `graph.mdx:14-15` "The graph is built during ingest" — ingest only marks it dirty
  (`client.py:475-476`); rebuild is lazy on the read path (`graph/retrieve.py:31-33`).
- `graph.mdx:38-46` "`max_hops` is unused" — it **is** read, as the deep-ask loop's hop cap
  (`config/schema.py:183` → `client.py:394-397`). The substantive claim (no edge walking) is
  TRUE: `GraphRetriever.retrieve` matches `node.label` and returns `node.eu_refs`, never
  touching `index.edges` (`graph/retrieve.py:36-49`).
- `signals.mdx:42-45` "enqueued on a durable queue if one is configured" — `CiteNexus.__init__`
  has **no `queue=` parameter** (`client.py:117-152`), so the branch at `ingest/pipeline.py:231-237`
  is unreachable from the facade. `bulk-ingest.mdx:45-52` reaches the right conclusion but calls
  the subsystem "standalone"; precise wording is "already wired into `IngestPipeline`, but not
  reachable from the `CiteNexus` constructor".

---

## Tier 3 — code samples that do not run

| # | Doc | Defect | Fix |
|---|---|---|---|
| 3.1 | `scenarios/evaluate-a-corpus.mdx:18-28` | Golden CSV header `question,expected_support`. `Evaluator` reads `question`/`query` and **`expected`** (`evaluate.py:63,69`; `examples/law-authority/golden.csv:1`). The column is silently ignored and `expected_support_rate` collapses into "answer rate". | Header must be `question,expected`. |
| 3.2 | `scenarios/regulated-audit.mdx:97-101` | `read_audit(rag)` → `TypeError`. Signature is `read_audit(backend: StorageBackend, partition: PartitionPath)` (`reconcile/audit.py:36`). | `read_audit(rag._backend, rag.partition)`, or expose a supported accessor. |
| 3.3 | `scenarios/right-to-erasure.mdx:36-40` | `{o.document_id for o in report.orphans}` → `AttributeError`. `orphans` is `tuple[str, ...]` (`reconcile/report.py:52`). | `assert "employee-nda" not in report.orphans` |
| 3.4 | `custom-endpoints.mdx:132` | `import { OpenAIEmbedder } from "@muthuishere/citenexus"` — not exported. `js/src/index.ts:9-38` exports no `models/`; `js/package.json:17-34` publishes `.`, `./ffi`, `./ingest`, `./storage`. The class exists (`js/src/models/embed.ts:22`) but is unreachable. | Export it from `js/src/index.ts`, or drop the import from the sample. |
| 3.5 | `index.mdx:86-88`, `ask.mdx:88-93` | `const r = ask(...)` then `response.answer` — `response` is undefined. | Rename `r` → `response`. |
| 3.6 | `quickstart.mdx:61` | `response.sources[0]` raises `IndexError` on a refusal (`flow.py:307-329` returns no sources) — on the page whose headline feature is abstention. | Guard on `response.evidence.decision`. |
| 3.7 | `scenarios/multilingual-corpus.mdx:191-195` | "Three languages is **two** extra small-model calls" — `_extra_queries` issues **one call per requested language**, i.e. three (`client.py:812-816`); only the resulting extra *queries* may be fewer. | "Three calls, up to three extra queries." |

---

## Tier 4 — known limitations not stated where a reader meets them

1. **The gate's tuning constants appear nowhere on the site.** `MAX_SINGLE_GAP = 4`,
   `MAX_TOTAL_GAP = 8` are pinned and non-configurable (`answer/verify.py:132-137`), the swept
   knee was `(3, 6)`, and they were fitted on **synthetic English fixtures**
   (`spikes/library-stress/`). Likewise conflict's `MAX_RESIDUAL = 1` with
   `SUBJECT_OVERLAP = 0.60`, `MAX_SYMDIFF = 3`, `MIN_CONTENT = 3`, `DUPLICATE_JACCARD = 0.80`,
   `CONFLICT_TOP_K = 6` (`answer/conflict.py:62,66,83,86,90,96`), swept on synthetic English
   sentences (`:77-82`, `conformance/cases/conflict.json`). `grep -rn "MAX_TOTAL_GAP\|gap budget\|synthetic\|fitted"`
   across `site/src/content/docs/` returns **zero hits**. Belongs on `concepts.mdx`,
   `result.mdx` and `conflicting-sources.mdx` — a user tuning for a non-English corpus has no
   way to learn the thresholds were never fitted for one.
   Note `conflicting-sources.mdx:64-71`'s "**0 false positives** across 27 hard negatives" is
   TRUE (`spikes/adr-0007-conflict/NOTES.md:17,21,24-26`) but omits that the fixtures are
   synthetic English.
2. **`evaluate()` does not fan out over `search_languages`.** `client.py:883-885` calls
   `Evaluator(self.ask)` and `evaluate.py:72` calls `self._ask(question)` bare — no `mode`,
   `k`, `answer_language` or `search_languages`. This is why the multilingual example's
   `library_evaluate` reads 9 answered / 13 refused against the harness's 16 / 6. Stated
   correctly on `multilingual-corpus.mdx:186` **only**; missing from `evaluate.mdx`,
   `evaluate-a-corpus.mdx`, `languages.mdx` and `index.mdx`.
3. **Subject-scope applicability** (`docs/adr/0012`, status *proposed*): a controlling statute
   can be quoted verbatim, cited correctly, clear both the faithfulness gate and the authority
   floor, and still govern a different kind of tenancy; 8 of 11 operative EUs are citable in
   isolation from their governing precondition (73% severance, ADR-0012:39-40).
   `scenarios/subject-scope.mdx` covers this excellently and `authority.mdx:210-229` links it —
   but `concepts.mdx`, `benchmark-law.mdx` and `domain-rag.mdx` do not, and
   `benchmark-law.mdx:84-90` ("This gap is now closed") reads as if authority closed the
   corpus's failure modes.
4. **Live-benchmark non-determinism.** Every rate on the site comes from a single live Gemini
   run. `examples/law-authority/RESULTS.md:62-72` records an identical re-run giving 5/6 and 62%
   instead of 6/5 and 75%; only the safety metrics (0 out-of-jurisdiction citations, 100%
   groundedness/citation, 100% abstain-when-no-evidence) reproduce. The caveat is present and
   well-written on `index.mdx:76,296` and `multilingual-corpus.mdx:175-177`; **absent** from
   `benchmark-law.mdx`, `languages.mdx:125-128`, `domain-rag.mdx:53-59` and `authority.mdx:198-203`.
5. **Python-only seams are undeclared** on the pages that document them: the reranker
   (`reranking.mdx` — Go/JS ship no rerank symbol; `golang/answer/askwith.go:32` says so) and
   the authority policy (`authority.mdx` — the ports carry `authority_tier` /
   `authority_floor_applied` for wire parity only, `golang/result/result.go:69-73`,
   `js/src/result/result.ts:62-67`, with no selection logic).
6. **Answer-language vs. verbatim tension** — an English question with `answer_language="en"`
   can return a Telugu citation, because citations stay verbatim in their source language
   (`flow.py:361-367`). Stated well on `languages.mdx` and `multilingual-desk.mdx:47`;
   **missing** from `ask.mdx`, `result.mdx` and `index.mdx:131-134` (which says the answer is
   "quoted verbatim **in the question's own language**" — the opposite of what the code does).

---

## Clean bills of health

- **Internal links and slugs: clean.** All 31 distinct `/citenexus/...` targets across all 36
  pages resolve to real pages under the `base: '/citenexus'` in `site/astro.config.mjs:11`.
  No broken anchors, no orphaned slugs, no stale scenario paths. Both GitHub links resolve to
  tracked files on `muthuishere/citenexus`.
- **`access.mdx` — clean, and the most accurate page on the site.** It correctly documents that
  there is no `allowed_partitions` constructor kwarg and no `scope` argument on `ask()`, and its
  "carried, not enforced" caution on `acl` is exactly the code's contract
  (`access/prefilter.py:31-56`, `access/scope.py:20-32`). It is the model the other pages should
  follow — and it makes `contract-review.mdx` §1.1 a direct self-contradiction.
- **`scenarios/subject-scope.mdx` — clean.** Every number verified against ADR-0012: 8/11 and
  73% (`:39-40`), "fixes 2, breaks 3" (`:25`), coverage 0.31/0.83 vs 0.29–0.80 (`:46-47`), 1/1
  caught, 0/8 regressions, 0/6 under paraphrase (`:124-126`). Correctly framed as proposed work
  with the failure presented as open.
- **`revoke.mdx` — clean.** The removal-order table matches `client.py:541-566` row for row,
  including the manifest `forget` as commit point and the shared-blob refcount. All port
  surfaces exist as spelled (`rust/src/store.rs:43,175`, `golang/storage/storage.go:36-48`,
  `js/src/storage/protocols.ts:59`).
- **`scenarios/right-to-erasure.mdx`** — apart from the one snippet (§3.3), the most accurate
  scenario; its limitation section matches `CHANGELOG.md` 0.10.0 exactly, including that blobs
  stranded by pre-0.10.0 re-ingests are unrecoverable.
- **`s3.mdx`, `wiki.mdx`, `scenarios/index.mdx`** — clean. `wiki.mdx`'s "flat, one-hop, no
  hierarchy" framing matches the code and does **not** overclaim the distillation depth.
- **Secret handling: clean.** No example anywhere passes an API key value into a constructor;
  `custom-endpoints.mdx` correctly confines `${ENV}` expansion to the HTTP boundary
  (`python/src/citenexus/http.py:70-74`, `js/src/http.ts:45`).
- **`ingest_async` is not claimed on any docs page.** (It is still wrongly claimed at
  `CLAUDE.md:188` and `CHANGELOG.md:182`; `CiteNexus` exposes only `ingest`, `client.py:432`.
  Fix those before they seed a rewrite.)

---

## Recommended order of work

1. **§1.1** `acl`-as-isolation (confidentiality claim), **§1.2** inverted `evaluate()` semantics
   (4 pages), **§1.3** bbox (6 pages + site description).
2. **§1.4** conflict "not implemented", **§1.7** cross-port gate parity, **§2.1** the "still
   0.9.0" banners (3 pages, trivial deletion, immediate user cost).
3. Remaining Tier 1, then Tier 2, then the seven broken snippets in Tier 3.
4. Tier 4 additions — especially the gap-budget/`MAX_RESIDUAL` provenance, which appears
   nowhere on the site at all.

**Rewrite rather than patch:**
- `scenarios/evaluate-a-corpus.mdx` — its worked example uses a column name the library ignores
  (§3.1) *and* its thesis section ("Why abstention rows are the ones that matter") rests on
  semantics the library inverts (§1.2). Both the example and the argument have to go.
- `benchmark-law.mdx` — headline table is a superseded baseline (§2.7), two capability claims are
  stale (§1.10), the non-determinism caveat is absent (§4.4), and it contradicts `authority.mdx`
  on which run is "before". Easier to regenerate from `examples/law-authority/results.json` and
  `RESULTS.md` than to reconcile line by line.
