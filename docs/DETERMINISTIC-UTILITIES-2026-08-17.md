# Deterministic utilities — inventory, divergence audit, and a proposed shape

**Date:** 2026-08-17 · **Tree:** `main` @ `d519550`
(`feat(conflict): conflict detection is native in all three ports, byte-identical`)
**Governing rule:** [ADR-0010](adr/0010-algorithm-placement-rust-core-vs-ports.md)
**Scope:** read-only design + audit. Nothing outside this file was modified.

Every location below was checked against source with a `file:line`. Rows marked
⚡ were additionally **executed** — a Go module with a `replace` onto `golang/`,
Node against a freshly built `js/dist`, and Python driven directly — because the
question "is this actually reachable / called / identical" is settled by running
it, not by grepping it.

---

## 0. Relationship to `PARITY-AUDIT-2026-08-17.md`

`PARITY-AUDIT-2026-08-17.md` was written against `1b2c7ee` (0.11.0). Two commits have landed
since. **Read it first; it remains the better document on capability gaps.** This
document does not redo it — it answers a different question (what *shape* should
the deterministic utilities have) and corrects the rows that the newer commits
moved.

### Where I agree, having re-verified

| PARITY-AUDIT claim | Status on `d519550` |
|---|---|
| Tokenizer v2 / gate v2 / relevance v2 / BM25 / RRF / chunker are genuinely byte-identical across ports (§8.4) | ✅ Re-confirmed. I additionally ran **claim segmentation** — 10 adversarial inputs (`"A. B."`, `"Pay 500.00 now. Then leave."`, `"Dr. Smith left."`, `"J. Smith left."`, `"Yes!! No."`, embedded `\n`, `"第一句。第二句。"`) — **10/10 identical in Python, Go and JS.** |
| Python's `_STOPWORDS` is a hand-maintained `frozenset` (`answer/verify.py:16`), against ADR-0010's own consequence list (lines 125-127) | ✅ Still true, unchanged. |
| `golang/gate/stopwords.json` has no byte-pin test | ✅ Still true. Only three `conform.Data` calls exist in all of `golang/`: `answer/conflict_tables_test.go:17`, `answer/segment_test.go:44`, `gate/verify_v2_test.go:94`. **I initially suspected `golang/tokenize/scripts.json` was also unpinned — it is not**, it is pinned a different way, via the case fixture at `tokenize/tokenize_v2_test.go:51-61`. Stopwords is the only unpinned embedded table. |
| All three ports mark their native RRF `@deprecated` in favour of the Rust FFI core — ADR-0010 applied backwards | ✅ Confirmed verbatim: `golang/rrf/rrf.go:19-23`, `js/src/rrf/rrf.ts:11-17`, `python/src/citenexus/retrieve/fusion.py:27-32`. `rust/src/rrf.rs` and `citenexus_rrf` (`rust/src/ffi.rs:110`) both still exist. |
| `SplitClaims` / `splitClaims` have zero non-test callers | ✅ Confirmed on this tree. |
| `ResolveAnswerLanguage` / `resolveAnswerLanguage` have zero non-test callers | ✅ Confirmed. |
| `euid` carries a second, duplicated chunker | ✅ Confirmed (`golang/euid/euid.go:192`, `js/src/euid/euid.ts:109`). **Refinement:** ⚡ I ran both chunkers head-to-head on 6 stress inputs (600/900/1500 random tokens with `500.00`/`Dr.`/`J.`/Tamil, 300 repeated sentences, 400 blank-line paragraphs, a 20k-char single token) in **both** ports — **identical in all 12 comparisons.** The drift risk is real and untested, but it is *latent*, not realized. State it that way. |

### Where it is now wrong (superseded by `d519550`)

| PARITY-AUDIT claim | Corrected |
|---|---|
| §0 finding **#1** and §7 gap **#1**: "Go and JS answer a self-contradicting corpus confidently, `conflicts: []`" | ⚡ **CLOSED in both ports.** Same two passages, shipped path: Go `answer.Ask` and JS `ask` both return `decision: "refused"`, `"The available evidence disagrees, so I can't answer that."`, `conflicts_detected: 1`, `conflicts: ["negation: a vs b (0 vs 1 negations)"]`. `DetectConflict` is wired at `golang/answer/askwith.go:157`, `js/src/answer/answer.ts:97`. |
| §3d: conflict detection **MISSING** in the ports, "tables only" | Superseded. `golang/answer/conflict.go` (500 lines, 8 exported symbols) and `js/src/answer/conflict.ts` (450 lines) now implement the full ADR-0007 algorithm and are byte-identical to Python. |
| §3c: "the entire ADR-0007 conflict table set … zero callers" | Superseded — the tables are now consumed by the algorithm that reads them. |
| §7 gap **#2**: "near-duplicate collapse absent in Go and JS" | **Half-corrected, and the remaining half is a NEW defect — see §D1.** JS is now correct (`supporting_sources: 1, distinct_documents: 1`, matching Python). **Go is not**: it computes the collapse and then ignores it on the answered path. |
| §4: "Python has **no** all-zero-vector predicate" | Refinement: Python *has* `is_zero_vector` (`python/src/citenexus/testing/fakes.py:37`) — it is filed under `testing/` and has zero callers in production `citenexus/`. Go and JS put the same predicate in **production** `contracts` (`golang/contracts/contracts.go:178`, `js/src/contracts.ts:198`) and call it from `CheckVector`/`checkVector`. The behavioural conclusion is unchanged; the cause is *placement*, which is exactly this document's subject. |

---

## PART A — Inventory

**Reachability column** means: reachable by a consumer of the *published package*
without a private/deep-internal import.
· Go: every listed package is importable — ⚡ I compiled and ran a program outside
the module that calls all 25 of them.
· JS: `js/src/index.ts` is the barrel; `js/package.json` also exposes `./ffi`,
`./ingest`, `./storage`.
· Python: **`citenexus/__init__.py:63-96` exports none of these.** Every
deterministic utility in Python is deep-import-only.

**Tier** is ADR-0010's: 1 = structural/arithmetic (native per port) · 2 =
language-dependent *data* (one canonical table, generated per port) · 3 =
language-dependent *algorithm* (Rust over FFI).

### A1. The pinned algorithms

| # | Algorithm | Python | Go | JS | Tier | Conformance vector | Reachable? |
|---|---|---|---|---|---|---|---|
| 1 | Tokenize **v1** (frozen, ASCII-only) | `tokenize.py:76` `tokenize` | `tokenize/tokenize.go:28` `Tokenize` | `tokenize/tokenize.ts:11` `tokenize` | 1 | `cases/tokenize.json` | Go ✅ JS ✅ Py deep-only |
| 2 | Tokenize **v2** (NFKC + full case-fold, 14 claimed scripts) | `tokenize.py:299` `tokenize_v2` | `tokenize/tokenize_v2.go:282` `TokenizeV2` | `tokenize/tokenize-v2.ts:225` `tokenizeV2` | **3** (correctly placed native — the prototype requirement was met) | `cases/tokenize_v2.json` | Go ✅ JS ✅ Py deep-only |
| 3 | Script detection (range table + binary search) | `tokenize.py:246` `script_of` → `Script` | `tokenize/tokenize_v2.go:217` `ScriptOf` → `string` | `tokenize/tokenize-v2.ts:153` `scriptOf` → `string` | 3 | `cases/tokenize_v2.json` | Go ✅ JS ✅ Py deep-only |
| 3b | Scripts present / unsupported | `tokenize.py:334` `scripts_in`, `:341` `unsupported_scripts` | `tokenize_v2.go:314` `ScriptsIn`, `:331` `UnsupportedScripts` | `tokenize-v2.ts:258` `scriptsIn`, `:274` `unsupportedScripts` | 3 | `cases/tokenize_v2.json` | Go ✅ JS ✅ Py deep-only |
| 4 | BM25 (k1=1.5, b=0.75, round6) | `storage/bm25.py:37` **class `Bm25TextSearch`** | `bm25/bm25.go:41` `Rank` | `bm25/bm25.ts:34` `bm25` | 1 | `cases/bm25.json` | Go ✅ JS ✅ Py deep-only |
| 5 | RRF (k=60) | `retrieve/fusion.py:18` `rrf_fuse` (over `Candidate`) | `rrf/rrf.go:24` `Fuse` (over `[][]string`) | `rrf/rrf.ts:19` `rrfFuse` (over `string[][]`) | 1 | `cases/rrf.json` — **and `rust/tests/rrf_test.rs:19`**, the only 4-language vector | Go ✅ JS ✅ Py deep-only |
| 6 | Chunker (450/60, recursive) | `evidence/chunker.py:45` `chunk_text` | `chunker/chunker.go:160` `ChunkText` | `chunker/chunker.ts:127` `chunkText` | 1 | `cases/chunker.json` | Go ✅ JS ✅ Py deep-only |
| 6b | Chunker — **duplicate copy inside euid** | — | `euid/euid.go:192` `ChunkText` | `euid/euid.ts:109` `chunkText` | 1 | *none of its own* | Go ✅ JS ⚠️ (not in the barrel; renamed away at `index.ts:23`) |
| 7 | Faithfulness gate **v1** (set containment, frozen) | `answer/verify.py:101` `is_supported` | `gate/gate.go:123` `IsSupported` | `gate/gate.ts:67` `isSupported` | 1 | `cases/faithful.json` | Go ✅ JS ✅ Py deep-only |
| 8 | Faithfulness gate **v2** (ordered containment + polarity, ADR-0009) | `answer/verify.py:221` `is_supported_v2` | `gate/verify_v2.go:225` `IsSupportedV2` | `gate/verify-v2.ts:150` `isSupportedV2` | 1 | `cases/faithful_v2.json` | Go ✅ JS ✅ Py deep-only |
| 8b | Alignment DP + gap budget (4 / 8) | `verify.py:149` `align`, consts `:135-136` | `gate/verify_v2.go:106` `Align`, `:113` `AlignWithBudget`, consts `:42-45` | `gate/verify-v2.ts:65` `align`, consts `:36-37` | 1 | (inside `faithful_v2.json`) | Go ✅ JS ✅ Py deep-only |
| 9 | Claim segmentation | `answer/segment.py:57` `split_claims` | `answer/segment.go:144` `SplitClaims` | `answer/segment.ts:107` `splitClaims` | 1 (the ADR's "undecided — prototype first" resolved to tier 1) | `cases/segmentation.json` | Go ✅ JS ✅ Py deep-only |
| 10 | Relevance overlap v1 / v2 | `verify.py:71` `has_relevance_overlap`, `:90` `has_relevance_overlap_v2` | `gate/gate.go:92` `HasRelevanceOverlap`, `:110` `HasRelevanceOverlapV2` | `gate/gate.ts:42` / `:58` | 1 | (inside `faithful*.json`) | Go ✅ JS ✅ Py deep-only |
| 10b | Content tokens (tokenize − stopwords) | `verify.py:66` `content_tokens`, `:80` `content_tokens_v2` | `gate/gate.go:58` `ContentTokens`, `:75` `ContentTokensV2` | `gate/gate.ts:15` / `:30` | 1 (code) + 2 (table) | — | Go ✅ JS ✅ Py deep-only |
| 11 | Conflict detection — pairwise (ADR-0007) | `answer/conflict.py:224` `detect_conflict` → `ConflictFinding \| None` | `answer/conflict.go:257` `DetectConflict` → `(ConflictFinding, bool)` | `answer/conflict.ts:310` `detectConflict` → `ConflictFinding \| null` | 1 | `cases/conflict.json` (Go ✅ `conflict_test.go:52`; JS ✅; **Python replays it** at `tests/answer/test_conflict_conformance.py:28`) | Go ✅ JS ✅ Py deep-only |
| 11b | Conflict — corpus sweep | `conflict.py:310` `find_conflicts(passages, *, top_k=…)` | `conflict.go:387` `FindConflicts` **+ `:393` `FindConflictsTopK`** | `conflict.ts:427` `findConflicts(passages, topK?)` | 1 | `cases/conflict.json` | Go ✅ JS ✅ Py deep-only |
| 11c | Conflict — rendering | `conflict.py:305` `describe_conflicts` | `conflict.go:377` `DescribeConflicts` | `conflict.ts:417` `describeConflicts` | 1 | — | Go ✅ JS ✅ Py deep-only |
| 12 | Near-duplicate — pairwise | `conflict.py:267` `is_near_duplicate` → `str \| None` | `conflict.go:345` `IsNearDuplicate` → `(string, bool)` | `conflict.ts:382` `isNearDuplicate` → `string \| null` | 1 | `cases/conflict.json` | Go ✅ JS ✅ Py deep-only |
| 12b | Near-duplicate collapse | `conflict.py:324` `collapse_near_duplicates` → `tuple[int, ...]` | `conflict.go:411` `CollapseNearDuplicates` → `[]int` | `conflict.ts:443` `collapseNearDuplicates` → `number[]` | 1 | `cases/conflict.json` | Go ✅ JS ✅ Py deep-only |
| 13 | EU-id derivation | **no named function** — inline f-strings at `evidence/builder.py:42` and `evidence/chunked_builder.py:70` | `euid/euid.go:28` `BlockBuilderEUIDs`, `:41` `ChunkedBuilderEUIDs` | `euid/euid.ts:130` `blockBuilderEuIds`, `:137` `chunkedBuilderEuIds` | 1 | `cases/eu_ids.json` | Go ✅ JS ✅ **Py: not a callable utility at all** |
| 13b | SHA-256 checksum | **no named function** — inline at `ingest/pipeline.py:152` | `euid/euid.go:56` `Checksum` | `euid/euid.ts:157` `sha256Hex` | 1 | `cases/eu_ids.json` (`checksum_example`) | Go ✅ JS ✅ Py ❌ |
| 14 | Structure index (§7b) | `evidence/structure.py:97` `build_structure` | `structure/structure.go:133` `BuildStructure` | `structure/structure.ts:86` `buildStructure` | 1 | `cases/structure.json` | Go ✅ JS ✅ Py deep-only |
| 15 | Co-mention graph (§10b) | `graph/store.py:148` `build_comention_graph` | `graph/graph.go:75` `BuildComentionGraph` | `graph/graph.ts:57` `buildComentionGraph` | 1 | `cases/graph_comention.json` | Go ✅ JS ✅ Py deep-only |
| 16 | Answer-language fallback chain (§11a) | `lang/fallback.py:44` `resolve_answer_language` | `lang/lang.go:35` `ResolveAnswerLanguage` | `lang/lang.ts:42` `resolveAnswerLanguage` | 1 | `cases/language.json` | Go ✅ JS ✅ Py deep-only |
| 17 | Result JSON wire shape | `answer/result.py` | `result/result.go` | `result/result.ts` | 1 | `cases/result_roundtrip.json` | Go ✅ JS ✅ Py deep-only |
| 18 | Hermetic hash embedder (sha1 mod 64, L2-normalized) | `testing/fakes.py:49` `FakeEmbedding` | `fakes/fakes.go:22` `FakeEmbedding` | `fakes/fakes.ts:19` `FakeEmbedding` | 1 | `cases/e2e_hermetic.json` | Go ✅ JS ✅ Py deep-only. **All three tokenize with v1** (`fakes.go:30`) — non-Latin text embeds to the zero vector. |
| 19 | Model wire shaping | `http.py`, `embed/client.py`, `answer/generator.py` | `models/openai.go`, `models/anthropic.go` | `models/openai.ts`, `models/anthropic.ts` | 1 | `cases/model_wire.json` (**Go ✅ JS ✅ Python ❌ — the one vector the reference does not check itself against**) | all ✅ |

### A2. Tier-2 tables — the generated linguistic assets

| Table | Canonical | Python | Go | JS | Byte-pin test |
|---|---|---|---|---|---|
| Stopwords (44) | `conformance/stopwords.json` | `answer/verify.py:16` `_STOPWORDS` — **hand-maintained `frozenset`, private** | `golang/gate/stopwords.json` (`//go:embed` at `gate/gate.go:21`) | `js/src/gen/tables.ts:9` `STOPWORDS_TABLE` (generated) | Py ❌ · **Go ❌** · JS ✅ `gen/tables.test.ts:23`. All three ⚡ verified byte-identical today. |
| Polarity markers (20) | `conformance/polarity.json` | `answer/tables.py:59` `POLARITY_MARKERS` — Python is the *reference*, generator emits the JSON | `golang/gate/polarity.json` (`verify_v2.go:34`) | `gen/tables.ts:56` `POLARITY_TABLE` | Py ✅ · Go ✅ `verify_v2_test.go:94` · JS ✅ `gen/tables.test.ts:27` |
| Segmentation (terminators + abbreviations) | `conformance/segmentation.json` | `answer/tables.py:88,91` `TERMINATORS`, `ABBREVIATIONS` — reference | `golang/answer/segmentation.json` (`segment.go:38`) | `gen/tables.ts:87` `SEGMENTATION_TABLE` | Py ✅ · Go ✅ `segment_test.go:44` · JS ✅ |
| Conflict tables (negations, antonyms, report bigrams, scope markers, measurement units, 7 thresholds) | `conformance/conflict.json` | `answer/gen/conflict_tables.py` — **GENERATED**, re-exported through `answer/tables.py:24-32` | `golang/answer/conflict_tables.json` (`conflict_tables.go:19`) | `gen/conflict_tables.ts` | Py ✅ · Go ✅ `conflict_tables_test.go:17` · JS ✅ |
| Script claim (supported / continuous) | `conformance/cases/tokenize_v2.json` | `tokenize.py:204,226` `CONTINUOUS_SCRIPTS`, `SUPPORTED_SCRIPTS` | `golang/tokenize/scripts.json` (`tokenize_v2.go:54`) | `gen/tables.ts:142,159` | Go ✅ `tokenize_v2_test.go:51-61` (via the case fixture, not `conform.Data`) · JS ✅ |
| Language / script code sets | `conformance/cases/languages.json` | `lang/codes.py:56` `Language`, `:117` `Script` | `lang/codes.go:20,23` `Language`, `Script` | `lang/codes.ts:26,89` | Go ✅ `codes_test.go:31` · JS ✅ |
| Search-language table (41) | `conformance/cases/languages.json` | `lang/search.py:47,149` | `lang/codes.go:122,168` `SearchLanguages` | `lang/codes.ts:139` `SEARCH_LANGUAGES` | ✅ |
| **Grounded-answer system prompt** | `conformance/prompts.json` | — | `models/openai.go:18` hardcoded `SYSTEM_PROMPT` | `models/openai.ts:26` hardcoded | ❌ **zero consumers in any language** (agreeing with PARITY-AUDIT §5) |

### A3. Python-only deterministic algorithms (no port counterpart)

These are still deterministic utilities and still have a placement question; all
are ADR-0010 tier 1 and all live inside facade packages rather than anywhere
recognisable as a core.

| Algorithm | Location | Vector |
|---|---|---|
| Authority tier + selection (ADR-0004) | `answer/authority.py:75` `tier_of`, `:80` `select_by_authority` | — |
| Corpus reconciliation diff (ADR-0008) | `reconcile/engine.py:39` `enumerate_index`, `:67` `reconcile`, `:127` `remediate` | — |
| Rebuild planner (§4c matrix) | `provenance/rebuild_planner.py:89` `plan`, `:98` `plan_all` | — |
| Vision 3-way decision (§9) | `vision/prefilter.py:62` `decide` | `cases/vision_orchestration.json` — **zero consumers, any language** |
| Scope → partition resolution | `access/scope.py:20` `resolve_scope` | — |
| Partition pre-filter | `access/prefilter.py:31,39,46` | — |
| `search_languages` resolution | `lang/search.py:149` `resolve_search_languages` | `cases/languages.json` |
| Zero-vector predicate | `testing/fakes.py:37` `is_zero_vector` | — |
| Vector validation | **absent** (Go `contracts/contracts.go:203` `CheckVector`; JS `contracts.ts:218` `checkVector`) | — |

### A4. The Rust core

`rust/src/ffi.rs` exports 16 `citenexus_*` symbols. Of the algorithms above,
**exactly one is duplicated into Rust: RRF** (`rust/src/rrf.rs`, exported at
`ffi.rs:110`). That is the ADR-0010 corollary violation, and it has since been
made *worse* — all three ports now carry a deprecation notice pointing *at* the
Rust copy the ADR ordered deleted.

---

## PART B — Name and shape divergence

The distinction that matters: **a divergence is necessary when the target
language's own idiom demands it, and accidental when a different choice was made
for no reason.** A "consistency" pass that erases the first category makes all
three ports worse. Below, each lead from the brief is judged, then the ones the
brief did not name.

### B1. NECESSARY — leave these alone

| # | Divergence | Verdict |
|---|---|---|
| N1 | `detect_conflict` → `ConflictFinding \| None` · `DetectConflict` → `(ConflictFinding, bool)` · `detectConflict` → `ConflictFinding \| null` | **Necessary.** `(T, ok)` is *the* Go idiom for a maybe-result and Go has no sum type; forcing a `*ConflictFinding` on Go to "match" Python would hand every caller a nil-pointer dereference where they currently get a compile-checked boolean. `null` vs `None` is the same concept spelled in each language's own vocabulary. Identical treatment applies to `is_near_duplicate` / `IsNearDuplicate` / `isNearDuplicate` and to `SearchLanguageByCode` (`codes.go:178`) vs `searchLanguageByCode` returning `undefined` (`codes.ts:148`). **Not a defect.** |
| N2 | `is_supported_v2` · `gate.IsSupportedV2` · `isSupportedV2` | **Necessary and already correct.** Same concept name, mechanically transformed by each language's casing convention. This is the target state, not a divergence. |
| N3 | `split_claims` · `SplitClaims` · `splitClaims` | **Necessary and already correct** — same as N2. (Its *wiring* is a defect; see Part D. Its *name* is not.) |
| N4 | `resolve_answer_language` argument style: Python keyword-only (`fallback.py:44`), Go positional 5-arity (`lang.go:35-41`), JS single options object (`lang.ts:42`) | **Necessary — and this is the best-executed convention in the repo.** All three carry the *same five parameter names in the same order*, including `languages_in_evidence`, which every port accepts and explicitly discards (`fallback.py:62`, `lang.go:42`, `lang.ts:49`) purely so the signature stays comparable. Go's doc comment states the reason: "the port diff is a verdict diff, not an API diff." **This is the model for Part C.** |
| N5 | Python returns `tuple[int, ...]` where Go returns `[]int` and JS `number[]` (`collapse_near_duplicates`) | **Necessary.** Immutability-by-default is a Python house style; Go and JS have no cheap frozen slice. |
| N6 | Python `script_of` returns the `Script` StrEnum; Go/JS return `string` | **Borderline, judged NOT a defect to force.** Go *has* `lang.Script` (`codes.go:23`, 27 constants at `:79-107`) and JS has `Script` (`codes.ts:89`), and `tokenize` in both returns a bare `string` instead. Typing it would be an improvement, but `golang/tokenize` currently imports nothing from `golang/lang`, and adding that dependency to make a *name* match is exactly the de-idiomatizing trade the brief warns about. **Recommend: type it only if `lang` is already a dependency; otherwise leave, and document the correspondence.** |

### B2. ACCIDENTAL — these are defects

| # | Divergence | Evidence | Why it is accidental, not idiomatic |
|---|---|---|---|
| **A1** | **BM25 is a *class bound to a store* in Python and a *pure function* in the ports.** `Bm25TextSearch(store).search_text(query, limit)` (`storage/bm25.py:37,46`) vs `bm25.Rank(rows []Row, query string) []Result` (`bm25.go:41`) vs `bm25(rows, query)` (`bm25.ts:34`) | ⚡ Go/JS scores agree to 1e-6; Python's arithmetic is only reachable by constructing a `VectorStore` | Nothing about Python requires an I/O-bound class here. The **scoring arithmetic — the ADR-0010 tier-1 asset — is not separately callable or testable in the reference port.** It is fused with a store scan (`bm25.py:49`), so `conformance/cases/bm25.json` is generated *around* it rather than *against* it. This is the single sharpest shape defect in the inventory. |
| **A2** | **RRF operates on different types.** Python `rrf_fuse(Sequence[list[Candidate]]) -> list[Candidate]` (`fusion.py:18`) vs Go `Fuse([][]string) []string` (`rrf.go:24`) vs JS `rrfFuse(string[][]) string[]` (`rrf.ts:19`) | `fusion.py:20-24` documents a *payload-merge policy* ("keep the best contributing payload… first occurrence breaks ties") the ports do not implement at all | The ports are pinned to the **eu_id ordering only**. Python's function additionally owns a candidate-selection rule that has no vector and no port. So "RRF is at parity" is true of the arithmetic and false of the function. Fixing this is separating one concept into two: `rrf_fuse_ids` (tier 1, pinned) and a payload merge that is Python facade policy. |
| **A3** | **Verb mismatch on the same concept.** `rrf_fuse` / `Fuse` / `rrfFuse`; `Bm25TextSearch.search_text` / `Rank` / `bm25` | `rrf.go:24`, `rrf.ts:19`, `fusion.py:18`; `bm25.go:41`, `bm25.ts:34` | A reader who knows `rrfFuse` cannot derive `Fuse`, and one who knows `bm25(...)` cannot derive `Rank`. The Go names read correctly *within their package* (`rrf.Fuse`, `bm25.Rank`) — which is why this needs a stated convention rather than a blind rename; see C3. |
| **A4** | **EU-id derivation and checksum are not utilities in Python at all.** Go `euid.BlockBuilderEUIDs` / `euid.Checksum`; JS `blockBuilderEuIds` / `sha256Hex`; Python: inline `f"{doc.document_id}::{block.order}"` at `builder.py:42` and `hashlib.sha256(raw).hexdigest()` at `ingest/pipeline.py:152` | grep for a named derivation function in `python/src/citenexus/evidence/` returns nothing | The ports named a function after the Python **class** that inlines the format string. `cases/eu_ids.json` therefore pins a rule that exists as a *literal inside two builders* in the reference. And the same one-liner has three names: `Checksum`, `sha256Hex`, none. |
| **A5** | **Module placement: Python files its deterministic core inside facade domains.** The gate is `answer/verify.py` where the ports have a top-level `gate` package; BM25 is `storage/bm25.py`; RRF is `retrieve/fusion.py`; the chunker is `evidence/chunker.py`; structure is `evidence/structure.py`; the co-mention graph is `graph/store.py`; the language chain is `lang/fallback.py` | Compare the directory listings: Go has 12 flat algorithm packages, `js/src/` mirrors them 1:1 | Go and JS **already agree with each other completely.** The divergence is Python-vs-both. A reader who knows `golang/gate/` or `js/src/gate/` has no way to guess `citenexus.answer.verify`, and `verify.py`'s own module docstring still describes the v0.1 extractive gate two ADRs out of date. |
| **A6** | **Tier-2 tables have three homes inside Python, generated in two opposite directions.** `answer/tables.py` (Python is the *source*, generator emits `conformance/*.json` from it) · `answer/gen/conflict_tables.py` (conformance is the source, generated *into* Python) · `answer/verify.py:16` `_STOPWORDS` (neither — hand-maintained, private) · `tokenize.py:204,226` (hand-maintained script claim) | `tables.py:5-9` vs `gen/conflict_tables.py:1-4` state the two opposite directions explicitly | ADR-0010 tier 2 says "one canonical table, generated per port, never hand-maintained." Python honours that for one of four tables. **Two of four are hand-written**, and the reader must know which is which to know whether editing it is safe. |
| **A7** | **Go's tier-2 tables are five loose JSON files scattered across four packages.** `gate/stopwords.json`, `gate/polarity.json`, `answer/segmentation.json`, `answer/conflict_tables.json`, `tokenize/scripts.json` | `grep 'go:embed' golang` — 5 hits, **`grep 'go:generate' golang` — 0 hits** | JS consolidated its tables into one generated `js/src/gen/` directory with a generator script (`js/scripts/gen-tables.mjs`) and a drift test. Go copies each file by hand into whichever package needs it and pins 3 of 5. There is no reason for the asymmetry — `//go:embed` needs same-directory files, which a single `golang/tables` package satisfies. |
| **A8** | **JS's one options object uses snake_case keys, unlike the rest of the port.** `resolveAnswerLanguage({ answer_language, conversation_language, languages_in_evidence, default_answer_language })` (`lang.ts:33-37`) vs `Bm25Row.euId` (`bm25.ts:19`), `sourceRef({ passageLanguage })` (`result.ts`) | — | Well-intentioned (it makes the cross-port signature literally diffable) but it makes `lang.ts` the only camelCase-violating module in the port. **Judged accidental**: the parity it buys is already carried by the parameter *order* and the shared doc; the cost is a JS user hitting one module that types differently from all the others. |
| **A9** | **`FindConflicts` has an extra Go-only function to emulate a Python keyword argument.** Python `find_conflicts(passages, *, top_k=CONFLICT_TOP_K)` (`conflict.py:310`) · JS `findConflicts(passages, topK = CONFLICT_TOP_K)` (`conflict.ts:427`) · Go **two functions**, `FindConflicts` + `FindConflictsTopK` (`conflict.go:387,393`) | `conflict.go:391` names the reason: "FindConflictsTopK is FindConflicts with an explicit window (Python's keyword…)" | **Judged NECESSARY-adjacent but worth flagging.** Go has no default arguments, so a second function is the correct Go answer. The accidental part is the *name*: `FindConflictsTopK` reads as "find the top-K conflicts", not "find conflicts within a K-wide window". A Go-idiomatic `FindConflictsInWindow` costs nothing and removes the misread. |
| **A10** | **Python's zero-vector predicate is filed under `testing/`.** `testing/fakes.py:37` `is_zero_vector` (zero production callers) vs `golang/contracts/contracts.go:178` `IsZeroVector` and `js/src/contracts.ts:198` `isZeroVector`, both called from the production `CheckVector` | grep confirms no non-`testing/` caller in `python/src/citenexus/` | Same name, same behaviour, filed under a package whose name tells a reader it is not for production. That placement is why PARITY-AUDIT reasonably concluded the predicate was absent. |

### B3. Summary judgement

Six of the ten "same algorithm, different spelling" leads are **necessary
language idiom and must be left alone** (B1). The real defects (B2) are almost
entirely about **placement and concept-splitting, not casing**:

- Python has no deterministic-core namespace at all (A5), which is upstream of
  A1, A2 and A4.
- Tier-2 tables have no single home in Python (A6) or Go (A7); only JS got it
  right.
- Two algorithms (BM25, RRF) are **fused with facade concerns in Python**, which
  is why the pure form only exists in the ports.

Notably, the cases the brief suspected — `detect_conflict`'s three return shapes,
`is_supported_v2`, `split_claims` — are all correct as they stand.

---

## PART C — The proposed shape

### C0. The finding that determines the answer

**Go and JS already have the shape.** `golang/` is 12 flat algorithm packages
(`tokenize`, `gate`, `bm25`, `rrf`, `chunker`, `euid`, `structure`, `graph`,
`lang`, `answer`, `result`, `fakes`) and `js/src/` mirrors them directory-for-
directory. Neither needs reorganising. Python is the outlier, and it is the
outlier because its deterministic algorithms were each filed next to the *facade
concern that first needed them* rather than under a core.

So the proposal is not a three-way redesign. It is: **name the thing Go and JS
already have, give Python the same thing, and give tier-2 tables one home per
port.**

### C1. Module granularity — per algorithm, inside one namespace

**Answer: both, and the distinction is real.** Keep one module per algorithm
family — that granularity is already load-bearing, because each family owns its
own conformance vector, its own generated table and its own test file, and
merging them would break the 1:1 vector↔module mapping that makes drift
detectable. But give the *set* a name, so:

- a reader can see at a glance which code is deterministic, pinned, and governed
  by ADR-0010 — versus facade code that may change freely;
- the tier boundary is visible in the directory tree rather than only in an ADR;
- a new algorithm has an obvious place to go, which is the whole point (ADR-0010
  §Context: "New work … has to answer the placement question immediately and has
  no rule to answer it with").

```
kernel/                     ← ADR-0010 tier 1 + the natively-placed tier 3
  tokenize/                 ← 2, 3, 3b
  gate/                     ← 7, 8, 8b, 10, 10b
  segment/                  ← 9
  conflict/                 ← 11, 11b, 11c, 12, 12b
  bm25/                     ← 4
  rrf/                      ← 5
  chunker/                  ← 6
  euid/                     ← 13, 13b
  structure/                ← 14
  graph/                    ← 15
  lang/                     ← 16
  tables/                   ← ALL tier-2 generated tables. Generated only.
```

Per port:

| Port | Namespace | How |
|---|---|---|
| **Go** | the existing top-level packages **are** the kernel | Do **not** move them to `golang/kernel/...` — the import path is the published API and a move breaks every consumer for zero behavioural gain. Instead add `golang/doc.go` naming the set, and move only the tier-2 JSON (C2). |
| **JS** | `js/src/` directories, unchanged | Already 1:1 with Go. `js/src/gen/` is already the tables home. |
| **Python** | **new** `citenexus/kernel/` | The one real move. Implemented as re-export modules first (C4), so no import churn and no behaviour risk. |

### C2. Where tier-2 tables live

**One generated directory per port, adjacent to the kernel, never inside the
algorithm package.** ADR-0010 tier 2 says the table is the asset and the code
reading it is trivial; that only holds if the tables are findable as a set and
regenerated as a set.

| Port | Today | Proposed |
|---|---|---|
| JS | ✅ `js/src/gen/tables.ts` + `gen/conflict_tables.ts`, one generator (`js/scripts/gen-tables.mjs`), drift-tested | Keep. This is the reference implementation of the pattern. |
| Go | ❌ 5 loose JSONs in 4 packages, 0 `go:generate`, 3 of 5 pinned | New `golang/tables/` package: all 5 JSONs `//go:embed`ed there, exported as accessors (`tables.Stopwords()`, `tables.PolarityMarkers()`, …), one `go:generate` that copies from `conformance/`, **one** drift test covering all 5. `gate`, `answer`, `tokenize` import `tables`. |
| Python | ❌ 3 homes, 2 generation directions, 2 hand-maintained | `citenexus/kernel/tables/` — one generated module per canonical file, all with the `gen/conflict_tables.py` header ("GENERATED … DO NOT EDIT"). `answer/tables.py` becomes a re-export shim. |

**And settle the generation direction.** Today Python is the source for polarity
and segmentation but the sink for the conflict tables. Pick one — **conformance
is always the source, every port is always generated** — because that is the only
direction under which "hand-maintained" is a detectable state rather than a
judgement call. That closes A6 and ADR-0010's own outstanding consequence
(lines 125-127).

### C3. The naming convention

State it once, in the ADR, as a mechanical transform so it is checkable:

> **Every kernel algorithm has one `concept_name`, declared in
> `conformance/ALGORITHMS.md`. Each port spells it in its own casing and nothing
> else:**
> - Python: `concept_name` (snake_case, verbatim)
> - Go: `ConceptName` (PascalCase), inside package = the concept *family*
> - JS: `conceptName` (camelCase)
>
> **The module/package/directory name is the family name, byte-identical in all
> three ports** (`tokenize`, `gate`, `segment`, `conflict`, `bm25`, `rrf`,
> `chunker`, `euid`, `structure`, `graph`, `lang`).
>
> **Parameter names and order are identical across ports**, including parameters
> a port ignores. Argument *style* is the port's own (Python keyword-only, Go
> positional, JS options object) — this is the `resolve_answer_language`
> precedent (B1/N4) promoted to rule.
>
> **Return *shape* is the port's own idiom** — `T | None`, `(T, ok)`, `T | null`
> are the same contract. **Return *type* is not**: if Python returns an enum, the
> ports return their enum.
>
> A Go package name may absorb a redundant prefix (`rrf.Fuse`, not
> `rrf.RrfFuse`) — but then the *concept* name is `fuse`, and Python and JS must
> use `fuse` too, not `rrf_fuse`/`rrfFuse`.

That last clause is what makes the convention derivable in both directions. It is
also what makes A3 a defect rather than taste.

### C4. Before / after — four concrete algorithms

**1. BM25 (defect A1 — the pure algorithm is not extractable in the reference)**

```
BEFORE
  concept: (undeclared)
  Python  storage/bm25.py:37   class Bm25TextSearch(store).search_text(query, limit)
  Go      bm25/bm25.go:41      func Rank(rows []Row, query string) []Result
  JS      bm25/bm25.ts:34      function bm25(rows, query): Bm25Result[]

AFTER
  concept: bm25_rank(rows, query) -> [(eu_id, score)]
  Python  kernel/bm25/bm25.py      def bm25_rank(rows, query) -> list[Bm25Result]   # pure
          storage/bm25.py:37       class Bm25TextSearch  -> keeps the store scan,
                                   delegates the arithmetic to kernel.bm25.bm25_rank
  Go      bm25/bm25.go             func Rank(rows []Row, query string) []Result     # unchanged
  JS      bm25/bm25.ts             function bm25Rank(rows, query): Bm25Result[]
                                   export { bm25Rank as bm25 }   // @deprecated alias
```
*Buys:* `conformance/cases/bm25.json` becomes replayable against Python, not just
generated by it — closing one instance of the structural asymmetry PARITY-AUDIT
§5 identified. **Non-breaking in Go. Additive in Python. One deprecated alias in JS.**

**2. RRF (defects A2, A3 — and the ADR-0010 corollary)**

```
BEFORE
  Python  retrieve/fusion.py:18  rrf_fuse(Sequence[list[Candidate]], k) -> list[Candidate]
                                 ...and a payload-merge policy no port implements
  Go      rrf/rrf.go:24          Fuse([][]string, k) []string        // @deprecated -> Rust
  JS      rrf/rrf.ts:19          rrfFuse(string[][], k) string[]     // @deprecated -> Rust
  Rust    rust/src/rrf.rs        citenexus_rrf  (ffi.rs:110)

AFTER
  concept: fuse(lists_of_eu_ids, k) -> eu_ids          [ADR-0010 tier 1]
  Python  kernel/rrf/rrf.py      def fuse(lists: Sequence[Sequence[str]], k=60) -> list[str]
          retrieve/fusion.py:18  rrf_fuse(...)  -> facade policy: calls kernel.rrf.fuse for
                                 the ORDER, then applies the payload-merge rule. Its
                                 deprecation notice is REMOVED — it is not deprecated,
                                 it is a different (facade) function.
  Go      rrf/rrf.go             Fuse(...)  — @deprecated notice REMOVED
  JS      rrf/rrf.ts             fuse(...); export { fuse as rrfFuse }  // @deprecated alias
  Rust    rust/src/rrf.rs        DELETED; citenexus_rrf deprecated then removed
```
*Buys:* the ADR-0010 corollary is executed in the direction the ADR specified
instead of the direction the code drifted. **Breaking on the FFI surface only** —
`citenexus_rrf` is deprecated first (ADR-0010 Consequences line 123 already
requires exactly this).

**3. The faithfulness gate (defect A5 — placement)**

```
BEFORE
  Python  answer/verify.py:101  is_supported          (module docstring 2 ADRs stale)
          answer/verify.py:221  is_supported_v2
          answer/verify.py:66   content_tokens        answer/verify.py:16 _STOPWORDS
  Go      gate/gate.go:123      IsSupported           gate/verify_v2.go:225  IsSupportedV2
  JS      gate/gate.ts:67       isSupported           gate/verify-v2.ts:150  isSupportedV2

AFTER
  Python  kernel/gate/gate.py    is_supported, content_tokens, has_relevance_overlap
          kernel/gate/verify_v2.py  is_supported_v2, align, MAX_SINGLE_GAP, MAX_TOTAL_GAP
          kernel/tables/stopwords.py  STOPWORDS      # GENERATED from conformance/
          answer/verify.py       re-export shim, unchanged import path, forever
  Go      unchanged (already correct)
  JS      unchanged (already correct)
```
*Buys:* the file split matches Go and JS exactly (`gate` + `verify_v2`), the
stopword table stops being hand-maintained, and CLAUDE.md's own `file:line`
citations for the gate start pointing at a path whose name says what it is.
**Non-breaking** — `answer/verify.py` keeps re-exporting.

**4. EU-id derivation (defect A4 — no utility in the reference)**

```
BEFORE
  Python  evidence/builder.py:42          eu_id=f"{doc.document_id}::{block.order}"
          evidence/chunked_builder.py:70  eu_id=f"{doc.document_id}::{block.order}::{index}"
          ingest/pipeline.py:152          hashlib.sha256(raw).hexdigest()
  Go      euid/euid.go:28,41,56           BlockBuilderEUIDs, ChunkedBuilderEUIDs, Checksum
  JS      euid/euid.ts:130,137,157        blockBuilderEuIds, chunkedBuilderEuIds, sha256Hex

AFTER
  concepts: block_eu_id(document_id, order) · chunk_eu_id(document_id, order, index)
            checksum(raw) -> lowercase sha256 hex
  Python  kernel/euid/euid.py   block_eu_id, chunk_eu_id, checksum
                                (builders and pipeline call them)
  Go      euid/euid.go          BlockEUID, ChunkEUID, Checksum
                                BlockBuilderEUIDs/ChunkedBuilderEUIDs kept as
                                // Deprecated: batch wrappers
  JS      euid/euid.ts          blockEuId, chunkEuId, checksum
                                export { sha256Hex } // @deprecated alias for checksum
```
*Buys:* `cases/eu_ids.json` stops pinning a format string that only exists inline
in the reference, and the ports stop naming a function after another port's
class. **Additive everywhere; three deprecated aliases.**

### C5. What it costs — and the alias plan

This is public API in three published packages (PyPI `citenexus`, npm
`@muthuishere/citenexus`, Go module `github.com/muthuishere/citenexus/golang`)
plus a `crates.io` crate and an FFI ABI. The repo's 0.x policy is **breaking is
acceptable when it buys value, but a public API *appearance* is deprecated, not
removed.** So:

| Port | Alias mechanism | Cost | Removal |
|---|---|---|---|
| **Python** | Old module keeps `from citenexus.kernel.gate import *` and its `__all__`. No `DeprecationWarning` at first — the old path is *supported*, not dying. | ~11 shim modules, ~5 lines each. **Zero** import churn for consumers. | Not before 1.0; and per policy, possibly never. |
| **Go** | New name added; old name kept as a one-line wrapper with a `// Deprecated:` doc comment (the convention `rrf.go:19` already uses). **No package moves** — the import path is the API. | ~4 wrapper funcs. `staticcheck SA1019` gives consumers a migration signal. | Not before 1.0. |
| **JS** | `export { newName as oldName }` with `/** @deprecated */`. `js/src/index.ts` re-exports both. | ~4 aliases. Note `index.ts:23` already handles a name collision this way for `euid`'s chunker — precedent exists. | Not before 1.0. |
| **Rust / FFI** | `citenexus_rrf` marked deprecated in `ffi.rs`, kept exported for one minor, then removed. This is the **only genuinely breaking** item, and ADR-0010 line 123 already authorises it. | ABI consumers: JS (`./ffi`, koffi) and Go (`citenexus_ffi` build tag). ⚡ Neither has a non-test caller (`core.Fuse` `golang/core/core.go:56` — zero non-test callers). | One minor after deprecation. |

**Costs that are not aliases:**

- **Documentation debt.** CLAUDE.md cites Python gate/conflict/chunker paths by
  `file:line` in at least six places. Every kernel move invalidates those. The
  repo has already shipped a release with off-by-one line citations
  (PARITY-AUDIT §1b), so this must be a checklist item on the move commit, not
  a follow-up.
- **Conformance regeneration.** `python/scripts/gen_conformance.py` imports the
  reference by path; the shims keep it working, but the generator should be
  repointed at `kernel.*` in the same commit so the shim is never load-bearing.
- **Merge conflict risk.** Another agent is adding tests across
  `python/tests/`, `golang/`, `js/src/` concurrently. **Sequence the Python
  package move after that lands** — it touches the most files with the least
  behavioural content, so it is the cheapest step to defer.

### C6. What this proposal deliberately does *not* do

- **No Go package moves.** Import paths are the published API and the current
  layout is already correct.
- **No forcing `(T, ok)` into a nil pointer,** or `None` into `null`-shaped
  Python (B1/N1).
- **No merging algorithm modules** into one file per port — the 1:1
  module↔conformance-vector mapping is what makes drift detectable.
- **No new tier-3 promotions.** ADR-0010 requires evidence, not anticipation, and
  ⚡ the 10-input segmentation and 12-input tokenizer comparisons produced zero
  divergences — the ports do not currently need Rust's Unicode competence for
  anything they already ship.

---

## PART D — Dead and wire-only surface

Caller counts are `grep` over each port excluding `*_test.go` / `*.test.ts`, with
the declaration and its own doc comment excluded — then, for every row that
mattered, confirmed by ⚡ compiling and running a consumer outside the module.
(PARITY-AUDIT's warning applies and was honoured: `js/src/graph/graph.ts` has a
literal NUL byte at line 76, so `grep -a` is mandatory in that port.)

### D1. ⚡ NEW DEFECT — a computed value discarded (Go only, on the answer path)

**This is the most important finding in this document and it is not in
`PARITY-AUDIT-2026-08-17.md`, because it was introduced by the commit that closed
PARITY-AUDIT's #1 gap.**

`golang/answer/askwith.go:163-166` computes near-duplicate collapse:

```go
independent := make([]row, 0, len(grounded))
for _, i := range CollapseNearDuplicates(textsOf(grounded)) {
    independent = append(independent, grounded[i])
}
```

`independent` is then used **only** on the conflict-abstention branch
(`:212` → `:295-296`). The **answered** branch ignores it:

```go
// askwith.go:226-227
SupportingSources:   len(grounded),   // ← pre-collapse
DistinctDocuments:   len(distinct),   // ← pre-collapse
```

JS does it correctly — `js/src/answer/answer.ts:214-216` uses
`ctx.independent.length` and derives `distinctDocuments` from `ctx.independent`.

⚡ **Measured**, three byte-identical documents ingested under ids `1`, `2`, `3`,
same question, shipped path:

| | `supporting_sources` | `distinct_documents` | `sources[]` length |
|---|---|---|---|
| Python | 1 | 1 | 1 |
| JS | **1** | **1** | 1 |
| **Go** | **3** | **3** | 1 |

Go's own `CollapseNearDuplicates` ⚡ returns `[0 2]` for `["a b c","a b c","z"]` —
the algorithm is correct; only the call site is wrong. The result is
self-inconsistent on its face: it reports three supporting sources and then lists
one. **Recommendation: WIRE IT — change two lines to `len(independent)` and
derive `distinct` from `independent`.** This is the poisoned-corpus corroboration
inflation (the project's 5th failure class): inject N clones and Go reports the
answer N-times corroborated. Non-breaking, two lines, and it should ship first.

### D2. Implemented, conformance-pinned, zero non-test callers

| Utility | Go | JS | ⚡ Called by hand? | Recommendation |
|---|---|---|---|---|
| **Claim segmentation** | `answer/segment.go:144` `SplitClaims` — grep returns **only the doc comment at `:130`** | `answer/segment.ts:107` `splitClaims` — grep returns **only the declaration** | ✅ Both work perfectly — 10/10 identical to Python on adversarial input | **WIRE IT.** The algorithm, the table (`segmentation.json`), the byte-pin test and the conformance vector all ship. The gate runs on the whole answer string (`askwith.go:189`, `answer.ts:201`) and `Claims` is always length ≤ 1 (`askwith.go:232-234`, `answer.ts:219`). Wiring it is call-site work, not algorithm work, and it converts "refuse whole" into Python's drop-not-fail. Lossy-not-wrong, so it ranks below D1. |
| **Answer-language resolution** | `lang/lang.go:35` `ResolveAnswerLanguage` — only the doc comment at `:25` | `lang/lang.ts:42` `resolveAnswerLanguage` — only the declaration | ✅ ⚡ Go returns `"ta"` for a reliable Tamil detection | **WIRE IT — but honestly.** `askwith.go:48` hardcodes `const answerLanguage = "en"` and its comment (`:44-47`) gives a defensible reason: the port has no config layer. The defect is not the constant; it is that `"en"` is then **stamped onto `PassageLanguage` and `LanguagesInEvidence`** (`askwith.go:228,235`) — a false assertion about the evidence, not a default about the output. Minimum fix: stop asserting evidence language the port did not detect (see D4). |
| **`unsupported_scripts` producer** | `tokenize_v2.go:331` `UnsupportedScripts` — zero callers (all 9 grep hits are the field, comments, or the declaration) | `tokenize-v2.ts:274` `unsupportedScripts` — zero callers | ✅ ⚡ Go returns `["myanmar"]` for `"ကabc"` | **WIRE IT.** Cheapest wrongness fix in the inventory: one call at the top of `AskWith`/`ask`. Without it, the ADR-0011 abstain-on-unclaimed-script guarantee is structurally unreachable in both ports while the field asserts `[]`. |
| **BM25** | `bm25/bm25.go:41` `Rank` | `bm25/bm25.ts:34` `bm25` | ✅ ⚡ `[{a 0.287682}]`; Go/JS agree to 1e-6 | **KEEP, unwired.** These are the delivery surface for a consumer building retrieval on the port — the ports have no retrieval pipeline of their own (PARITY-AUDIT §0), so "no internal caller" is expected, not dead. |
| **RRF (native copies)** | `rrf/rrf.go:24` `Fuse` | `rrf/rrf.ts:19` `rrfFuse` | ✅ ⚡ `["a","b"]` | **KEEP and un-deprecate** (C4-2). Same reasoning, plus ADR-0010 explicitly names the ports as "the delivery surface" and the Rust copy as "the redundant one". |
| **Structure index** | `structure/structure.go:133` `BuildStructure` | `structure/structure.ts:86` `buildStructure` | ✅ ⚡ | **KEEP, unwired** — same reasoning. |
| **Co-mention graph** | `graph/graph.go:75` `BuildComentionGraph` | `graph/graph.ts:57` `buildComentionGraph` | ✅ ⚡ | **KEEP, but fix the tokenizer.** `graph/graph.go:53` calls `gate.ContentTokens` — **v1**, ASCII-only — so the graph is silently empty for any non-Latin corpus. Switching to `ContentTokensV2` is a one-word change *and a conformance-vector change* (`cases/graph_comention.json`), so it must be a deliberate, vectored commit. |
| **EU-id builders** | `euid/euid.go:28,41` | `euid/euid.ts:130,137` | ✅ ⚡ `["doc::0"]` | **KEEP** (C4-4 renames them). |
| **Search-language table** | `lang/codes.go:168` `SearchLanguages` — zero callers | `lang/codes.ts:139` `SEARCH_LANGUAGES` | ✅ ⚡ 41 entries | **KEEP.** It is reference data for a consumer, and the fan-out that would consume it (ADR-0013) is Python-only by design. |
| **v1 gate + v1 relevance** | `gate/gate.go:92,123` | `gate/gate.ts:42,67` | ✅ | **KEEP frozen.** Zero non-test callers is the *correct* state — both are deliberately frozen for `cases/faithful.json` and both files say so. Confirms CLAUDE.md. |
| **`PolarityMarkers()` accessor** | `gate/verify_v2.go:74` — zero callers | (JS exports `POLARITY_MARKERS` from `verify-v2.ts:29`, used at `:2` sites) | — | **KEEP.** Public introspection of a tier-2 table is a legitimate surface; it just has no internal user. |
| **`TOKENIZER_VERSION`** | `tokenize_v2.go:45` — **zero callers anywhere** | `tokenize-v2.ts:34` — one (`gen/tables.ts` drift test) | — | **WIRE IT.** Nothing stamps a tokenizer version onto an index in either port, so a v1-built index is indistinguishable from a v2 one and is silently queried with the wrong tokenizer. Python stamps it (`ingest/pipeline.py:245`) and then **never reads it back** — `storage/manifest.py:156` `is_stale` has zero callers. So the stale-index guard is dead in all three ports, in two different ways. |
| **`euid`'s duplicate chunker** | `euid/euid.go:192` `ChunkText` | `euid/euid.ts:109` `chunkText` | ✅ ⚡ **identical to `chunker.ChunkText` on 6 stress inputs, in both ports** | **DELETE the copy; call `chunker.ChunkText`.** PARITY-AUDIT called this a live drift risk; measurement says it is latent, not realized — which makes it *cheap* to fix now and expensive later. Nothing tests the two against each other, and JS's copy uses a lookbehind regex that `chunker.ts` deliberately avoids, so the two are one regex edit from silently disagreeing about EU boundaries. |
| **`PostgresTextSearch`** | `storage/postgres_store.go:347` — zero callers, **zero tests** | — | — | **DELETE or test.** Untested, uncalled, in the storage layer. Not a deterministic utility, listed because it is in the same dead-surface class. |
| **`PluginVersion` ×3** | `storage.go:49`, `storage.go:352`, `lance_adapter.go:28` — zero callers, zero tests | — | — | **DELETE.** Nothing stamps a plugin version in Go; three declarations of a field nobody writes or reads. |
| **FFI core entry points** | `core/core.go:46,56,96,114` `Version/Fuse/ToMarkdown/Detect` — zero non-test callers, and ⚡ never compiled in CI (`grep citenexus_ffi .github/` is empty) | — | — | **KEEP** (it is the port's FFI surface) **but get it into CI.** Largest untested surface in the repo; PARITY-AUDIT §6 is right. |

### D3. Hardcoded where another port computes

| Field | Go | JS | Python | Verdict |
|---|---|---|---|---|
| `all_claims_verified` | `askwith.go:227` hardcoded `true` | `answer.ts:215` hardcoded `true` | `flow.py:392` = `removed == 0` | **Asserts a fact it did not check.** Both ports gate the whole answer string as one claim, so "all claims verified" is vacuously true — but a consumer cannot tell that from the JSON. Fixed for free by D2's segmentation wiring. |
| `languages_in_evidence` / `passage_language` | `askwith.go:228,235` = `["en"]` / `"en"` | `answer.ts:217` = `["en"]` | `flow.py` computes | **False statement in a populated field.** See D2 row 2. |
| `unsupported_scripts` | `askwith.go:230` = `[]string{}` | `result.ts:133` = `[]` | `flow.py:189,202` computes | Wire-only over a dead producer. |
| `authority_tier` / `authority_floor_applied` | `result.go:72-73` never assigned | `result.ts:134-135` never assigned | `flow.py:252,397` | Wire-only (both ports' comments admit it). |
| `retrieval_score_spread`, `unsupported_claims_removed`, `provenance`, `loop`, `bbox`, `Decision.partial`, `GraphEdge.confidence` | never assigned | never assigned | Python computes all but `bbox` and `GraphEdge.confidence` | Wire-only. |

PARITY-AUDIT §7's structural recommendation stands and I endorse it without
qualification: **until a port computes a field, it should be absent or explicitly
`null` — never `[]`/`""`/`false`/`true`.** A consumer cannot distinguish
"checked, none found" from "never checked", and `all_claims_verified: true` from
a port with no claim decomposition is the sharpest case.

### D4. Python-side dead deterministic surface

| Utility | Location | Callers | Recommendation |
|---|---|---|---|
| `is_zero_vector` | `testing/fakes.py:37` | zero outside `testing/` | **MOVE to `kernel/` or `contracts.py` and use it**, matching `golang/contracts/contracts.go:178` and `js/src/contracts.ts:198`. Python still has no vector validation at all on the ingest path (PARITY-AUDIT §4, and I confirm), and the predicate it needs is already written and filed under the wrong package. |
| `allowed_partition` / `filter_partitions` / `apply_acl_predicate` | `access/prefilter.py:31,39,46` | zero | **Decide and document.** `allowed_partitions` exists as a config field (`config/schema.py:282`) that nothing reads, so a multi-tenant caller who sets it believes they are isolated and is not. Either wire it or remove the config field — a config knob with no reader is worse than an absent feature. |
| `TokenizerManifest.is_stale` | `storage/manifest.py:156` | zero | **WIRE IT** — pairs with the `TOKENIZER_VERSION` row in D2. The write half is called (`ingest/pipeline.py:245`); only the read half is dead. |
| `plan` / `plan_all` (§4c rebuild matrix) | `provenance/rebuild_planner.py:89,98` | zero from the facade | **Decide.** A fully-specified, spec-table-derived algorithm with no entry point. |

---

## PART E — Sequenced plan

Ordered by value, each step independently shippable and green on its own.
The ordering rule is the repo's: *a port emitting a confident, correctly-cited,
wrong or unflagged answer* outranks *silent index corruption* outranks *a
structural cleanup*. Steps 1-4 are correctness; 5-9 are shape.

| # | Step | Ports | Breaking? | Alias needed | Why here |
|---|---|---|---|---|---|
| **1** | **Fix `askwith.go:226-227` to use `independent`.** | Go | No | — | **Two lines.** ⚡ Proven live: Go reports `supporting_sources: 3` for three clones where Python and JS report `1`, and lists one source while claiming three. It is a wrong confidence signal on the shipped answer path, and the poisoned-corpus class is *rewarded* by it. The computed value is already sitting in a local variable. Add a conformance case for the clone corpus so it cannot regress. |
| **2** | **Wire `unsupportedScripts` into both ports' ask paths.** | Go, JS | No | — | One call site each; the producer, the vector and the byte-pin all ship. Converts `unsupported_scripts: []` from a false assertion into a computed fact and makes the ADR-0011 abstain guarantee reachable. |
| **3** | **Stop asserting evidence language the port did not detect.** | Go, JS | Wire-shape only | — | Either wire `ResolveAnswerLanguage` + a detector, or emit `passage_language`/`languages_in_evidence` as **absent/null** rather than `"en"`. Keeping the `"en"` *output* default is defensible (`askwith.go:44-47` argues it well); stamping `"en"` onto a Tamil passage is not. |
| **4** | **Generate Python's `_STOPWORDS` from `conformance/stopwords.json`; add the missing byte-pin test for `golang/gate/stopwords.json`.** | Python, Go | No | — | ADR-0010's own Consequences (lines 125-127) ordered the Python half and it was never done. The stopword set feeds `ContentTokens` → the relevance gate on the answer path, and two of three ports have no guard against drift. ⚡ All three are byte-identical today — fix it while that is still true. |
| **5** | **Execute the ADR-0010 RRF corollary in the direction the ADR specified.** Remove the three `@deprecated`-in-favour-of-Rust notices; mark `citenexus_rrf` deprecated in `rust/src/ffi.rs`. | all + Rust | **Yes, FFI only** | ✅ `citenexus_rrf` deprecated one minor before removal | Today the code says the opposite of the governing ADR in three places, so any new algorithm reading the codebase for precedent learns the wrong rule. ⚡ Neither FFI consumer has a non-test caller. Ship the deprecation now, delete `rust/src/rrf.rs` in the next minor. |
| **6** | **Wire `SplitClaims` / `splitClaims`; make `all_claims_verified` computed.** | Go, JS | No | — | ⚡ Both split identically to Python on 10 adversarial inputs. Converts refuse-whole into drop-not-fail and turns a hardcoded `true` into a checked fact. Lossy-not-wrong today, which is why it sits below 1-4 despite being CLAUDE.md's most-cited parity gap. |
| **7** | **Tier-2 tables get one home per port.** New `golang/tables` package (all 5 JSONs, one `go:generate`, one drift test); Python `kernel/tables/`; JS `gen/` confirmed as canonical. Settle the direction: **conformance is always the source.** | all | No | — | Closes A6 and A7. Must land before step 8 so the Python move has somewhere to put the tables. Pure mechanics, no behaviour. |
| **8** | **Introduce `citenexus/kernel/` with re-export shims at every old path.** Repoint `python/scripts/gen_conformance.py` at `kernel.*` in the same commit. | Python | No (additive) | ✅ ~11 shim modules, permanent | The big shape change, and deliberately late: it touches the most files with the least behavioural content, so it is the cheapest step to defer around the concurrent test work. **Sequence it after the in-flight test additions land.** Update every CLAUDE.md `file:line` in the same commit — this repo has shipped stale citations before. |
| **9** | **Naming convergence + alias plan.** `bm25_rank` extracted pure in Python; `fuse` concept unified; `block_eu_id`/`chunk_eu_id`/`checksum`; `FindConflictsInWindow`; JS `lang.ts` options object to camelCase. Record the convention in ADR-0010 (or a successor). | all | Yes, by *appearance* | ✅ ~4 Go wrappers, ~4 JS `@deprecated` re-exports, Python shims | Last because it is the only step that changes names a consumer already types. Each rename is individually cheap; batching them into one release note is cheaper than dribbling them out. |
| **10** | **Cleanup, once the above is green.** Delete `euid`'s duplicate chunker (call `chunker.ChunkText`); delete `PostgresTextSearch` and the three `PluginVersion`s; wire `TOKENIZER_VERSION` + `TokenizerManifest.is_stale`; move `is_zero_vector` out of `testing/`; get `citenexus_ffi` into CI. | all | No | — | ⚡ The euid chunkers agree today on 12 comparisons — delete the copy while that is still cheap. The rest is dead weight that makes the surface harder to reason about than it is. |

**Breaking-change summary.** Exactly one step is genuinely breaking (5, and only
on the FFI ABI, which ADR-0010 already authorised). Step 9 is breaking by
*appearance* only and is fully covered by aliases. Steps 1-4, 6-8 and 10 are
non-breaking. That is the point of sequencing correctness first: **everything
that fixes a wrong answer ships without a deprecation cycle.**

---

## Method note

- Structural inventory: exported-symbol extraction across all 33 non-test `.go`
  files and all 33 non-test `.ts` files under `js/src`, plus targeted reads of
  the Python reference.
- Caller counts: `grep -a` per port excluding tests, declarations and doc
  comments — then confirmed by execution for every row that carried a
  recommendation.
- ⚡ Execution: a Go module with `replace github.com/muthuishere/citenexus/golang
  => ./golang`, Node against a freshly rebuilt `js/dist`, and Python driven
  directly — fed identical inputs, outputs diffed. Probes were written to the
  session scratchpad, not the repo.
- Nothing in the working tree was modified except this file.
