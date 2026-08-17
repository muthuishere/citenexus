# AUDIT: three-port coverage across `site/src/content/docs/`

Read-only audit, `main`, 2026-08-17. Nothing was edited.

**The ask.** The owner wants per-language tabs (Python / Go / JavaScript) across
the docs, the way the reference screenshot shows the *same task* in each language.

**The constraint that shapes the answer.** Python is the batteries-included
**facade**; Go and JavaScript are the **deterministic core only**. There is no
`CiteNexus` class, no `ask()`/`ingest()`/`evaluate()` front door, no config layer,
no authority policy, no vision path, no reranker seam and no deep-ask in Go or JS.
So the work is not "add three tabs everywhere". Per page and per sample the verdict
is one of:

- **(a)** exists in all three → write the three-tab example
- **(b)** Python only → the page must **say so**, not silently show one language
- **(c)** Python + one port, or all three with a caveat → show what exists, name what doesn't
- **(d)** an existing Go/JS sample is wrong / stale → a bug

Headline: **9 pages can honestly become three-tab** (5 of them are new wins), **21
are Python-only by nature** and need an explicit note, and there are **6 concrete
bugs**, one of which is a false capability claim in the opposite direction — the
docs *under*-claim the ports' multilingual support.

---

## 1. Ground truth — the actual public surface

### Python (`python/src/citenexus/__init__.py` `__all__` + `client.py`)

`CiteNexus` facade methods: `ingest`, `code`, `schema`, `revoke`, `delete`,
`crawl`, `refresh_slow_path`, `retrieve`, `ask`, `stream`, `tools`, `evaluate`,
`reconcile`, `remediate`, `recall`, `from_config`.

Top-level exports: `CiteNexus`, `S3`, `Hooks`, `DeleteResult`, five contracts
(`EmbeddingProvider`, `GeneratorProvider`, `CompletionProvider`, `VisionProvider`,
`RerankerProvider`) + `SingleTextEmbedder`, `SequenceEmbedder`, `Vector`; four
model clients (`OpenAICompatibleEmbedding/Generator/Reranker/Vision`); six
`HttpEndpoint` types; five reconcile types.

Deep modules used by docs: `citenexus.tokenize` (`tokenize`, `tokenize_v2`,
`scripts_in`, `unsupported_scripts`, `SUPPORTED_SCRIPTS`, `TOKENIZER_VERSION`),
`citenexus.answer.verify` (`content_tokens[_v2]`, `has_relevance_overlap[_v2]`,
`is_supported`, `is_supported_v2`, `align`, `MAX_SINGLE_GAP`, `MAX_TOTAL_GAP`),
`citenexus.answer.segment.split_claims`, `citenexus.evidence.chunker.chunk_text`,
`citenexus.evidence.structure.build_structure`,
`citenexus.graph.store.build_comention_graph`, `citenexus.retrieve.rrf_fuse`,
`citenexus.lang.resolve_answer_language` / `AUTO_ANSWER_LANGUAGE`,
`citenexus.storage.bm25.Bm25TextSearch`, `citenexus.answer.result.*`.

### Go (`golang/`, module `github.com/muthuishere/citenexus/golang`, `go 1.26`)

| pkg | exported | build tag |
|---|---|---|
| `answer` | `Doc`, `DefaultTopK`, `Ask`, `AskWith`, `Providers`, `SplitClaims` | — |
| `gate` | `ContentTokens`, `ContentTokensV2`, `HasRelevanceOverlap[V2]`, `IsSupported`, `IsSupportedV2`, `Align`, `AlignWithBudget`, `Alignment`, `PolarityMarkers` | — |
| `tokenize` | `Tokenize`, `TokenizeV2`, `TokenizerVersion`, `SupportedScripts`, `ContinuousScripts`, `ScriptOf`, `ScriptsIn`, `UnsupportedScripts` | — |
| `bm25` | `Row`, `Result`, `Rank` | — |
| `rrf` | `DefaultK`, `Fuse` | — |
| `chunker` | `ChunkText` | — |
| `lang` | `AutoAnswerLanguage`, `Detection`, `ResolveAnswerLanguage` | — |
| `result` | `Result`, `EvidenceSignals`, `SourceRef`, `Claim`, `ProvenanceEntry`, `BBox`, `Decision`, `TrustMode`, `TrustModeStrict`, `RefusalAnswer`, `Refused`, `LoopSignals` | — |
| `contracts` | `EmbeddingProvider`, `GeneratorProvider`, `SingleTextEmbedder`, `Vector`, `EmbedTexts`, `EmbedOne`, `SingleFrom`, `IsZeroVector`, `CheckVector`, `ErrNotAnEmbedder` | — |
| `models` | `NewHTTPClient`, `HTTPClient`, `ExpandEnv`, `Transport`, `Option`, `WithHeaders`, `NewOpenAIEmbedding`, `NewOpenAIChatGenerator`, `NewAnthropicGenerator`, `SystemPrompt` | — |
| `structure` | `Block`, `Doc`, `Node`, `Index`, `BuildStructure` | — |
| `graph` | `Row`, `Node`, `Edge`, `Index`, `BuildComentionGraph` | — |
| `euid` | `Block`, `BlockBuilderEUIDs`, `ChunkedBuilderEUIDs`, `Checksum`, `ChunkText` | — |
| `fakes` | `Dim`, `FakeEmbedding`, `FakeLLM`, `Cosine` | — |
| `storage` | `Row`, `VectorStore`, `TextSearch`, `TableNameFor`, `PostgresVectorStore`, `PostgresTextSearch` | — |
| `storage` | `LanceVectorStore`, `NewLanceVectorStore`, `OpenLanceVectorStore` (`lance_adapter.go`) | **`citenexus_ffi`** |
| `core` | `Version`, `Fuse`, `Extract`, `ToMarkdown`, `Detect`, `Store` (+ `Open`/`Upsert`/`Search`/`Scan`/`DeleteDocument`/`Drop`/`Close`) | **`citenexus_ffi`** |
| `ingest` | `Ingest`, `Row`, `Embedder`, `EmbedderFunc` | **`citenexus_ffi`** |

The build tag matters for docs: **a reader who runs plain `go get` cannot call
`core.Extract`, `core.Detect` or `ingest.Ingest`** without `-tags citenexus_ffi`
and the native library present.

### JavaScript (`js/src/index.ts`, package `@muthuishere/citenexus` 0.10.0)

Root entry (dependency-free): `contracts`, `tokenize`, `tokenize-v2`, `bm25`,
`rrf`, `gate`, `verify-v2`, `chunker`, `euid` (`blockBuilderEuIds`,
`chunkedBuilderEuIds`, `sha256Hex`), `lang`, `result`, `answer` (`ask`, `askWith`,
`CorpusDoc`, `REFUSAL_ANSWER`), `segment` (`splitClaims`), `graph`, `structure`,
`fakes`, `storage` (`VectorStore`, `TextSearch`, `PostgresVectorStore`,
`PostgresTextSearch`, `tableNameFor`), `http` (`HttpClient`, `expandEnv`,
`wireHeaders`). `models/*` (`OpenAIEmbedder`, `OpenAIChatGenerator`,
`AnthropicGenerator`) is reachable but **not re-exported from the root** — see bug
B5.

Subpath entries: `@muthuishere/citenexus/ffi` (`version`, `extract`, `toMarkdown`,
`rrf`, `detect`, `Store`), `/ingest` (`ingest`), `/storage`.

---

## 2. Capability matrix

`✅` = exists · `⛔` = absent · `🔒` = behind `citenexus_ffi` (Go) / a subpath import (JS) · `≈` = exists but a different shape

| Operation | Python | Go | JavaScript | Verdict |
|---|---|---|---|---|
| **Facade `ask()`** | ✅ `CiteNexus.ask` | ⛔ | ⛔ | b |
| **Hermetic `ask` over a corpus** | ≈ `SmokePipeline` (not public) | ✅ `answer.Ask` | ✅ `ask` | c |
| **`ask` with injected models** | ✅ `CiteNexus(embedder=, generator=)` | ✅ `answer.AskWith` | ✅ `askWith` | **a** |
| **Facade `ingest()`** | ✅ `CiteNexus.ingest` | ⛔ | ⛔ | b |
| Row-level ingest | ≈ `IngestPipeline` (internal) | 🔒 `ingest.Ingest` | 🔒 `/ingest` `ingest` | c |
| `crawl()` | ✅ | ⛔ | ⛔ | b |
| **`retrieve()`** | ✅ | ⛔ | ⛔ | b |
| **`evaluate()`** | ✅ + `EvaluationReport` | ⛔ | ⛔ | b |
| **`reconcile` / `remediate`** | ✅ | ⛔ | ⛔ | b |
| **`delete` / `revoke` (orchestrated)** | ✅ | ⛔ | ⛔ | b |
| Storage-level document delete | ✅ store seam | ✅ `VectorStore.DeleteDocument` | ✅ `VectorStore.deleteDocument` | **a** |
| **Faithfulness gate v1** | ✅ `is_supported` | ✅ `gate.IsSupported` | ✅ `isSupported` | **a** |
| **Faithfulness gate v2 (order+polarity)** | ✅ `is_supported_v2`, `align` | ✅ `gate.IsSupportedV2`, `Align` | ✅ `isSupportedV2`, `align` | **a** |
| — gate v2 *wired into the ask path* | ✅ | ⛔ (v1) | ⛔ (v1) | c |
| **Relevance overlap** | ✅ `has_relevance_overlap[_v2]` | ✅ `HasRelevanceOverlap[V2]` | ✅ `hasRelevanceOverlap[V2]` | **a** |
| **Claim segmentation** | ✅ `split_claims` | ✅ `answer.SplitClaims` | ✅ `splitClaims` | **a** |
| **Chunking** | ✅ `chunk_text(text, max_tokens, overlap)` | ✅ `chunker.ChunkText` | ✅ `chunkText` | **a** |
| **Tokenizer v1 / v2** | ✅ `tokenize`, `tokenize_v2` | ✅ `Tokenize`, `TokenizeV2` | ✅ `tokenize`, `tokenizeV2` | **a** |
| **Script capability signals** | ✅ `SUPPORTED_SCRIPTS`, `scripts_in`, `unsupported_scripts` | ✅ `SupportedScripts`, `ScriptsIn`, `UnsupportedScripts` | ✅ same, camelCase | **a** — identical 14-script table |
| **RRF fusion** | ✅ `rrf_fuse(lists[Candidate], k)` | ✅ `rrf.Fuse([][]string, k)` | ✅ `rrfFuse(string[][], k)` | c — Python fuses `Candidate`s, ports fuse eu-id strings |
| **BM25 rank** | ≈ `Bm25TextSearch` (a store adapter) | ✅ `bm25.Rank(rows, query)` | ✅ `bm25(rows, query)` | c |
| **Result shape** | ✅ `answer.result.Result` | ✅ `result.Result` | ✅ `Result` | **a** — field-for-field |
| **Pinned refusal string** | ✅ | ✅ `result.RefusalAnswer` | ✅ `REFUSAL_ANSWER` | **a** |
| **Trust modes** | ✅ strict/normal/exploratory | ≈ `TrustModeStrict` only | ≈ `TrustMode` enum, strict only in flow | c |
| **Answer-language resolution** | ✅ `resolve_answer_language` | ✅ `lang.ResolveAnswerLanguage` | ✅ `resolveAnswerLanguage` | **a** |
| `search_languages` fan-out | ✅ | ⛔ | ⛔ | b |
| Language detection (model) | ✅ `FastTextDetector`, `HeuristicDetector` | 🔒 `core.Detect` | 🔒 `/ffi` `detect` | c |
| **Structure index** | ✅ `build_structure` | ✅ `structure.BuildStructure` | ✅ `buildStructure` | **a** |
| **Co-mention graph build** | ✅ `build_comention_graph` | ✅ `graph.BuildComentionGraph` | ✅ (graph.ts) | **a** |
| Graph *retrieval* / LLM distiller | ✅ | ⛔ | ⛔ | b |
| Wiki (all of it) | ✅ | ⛔ | ⛔ | b |
| **EU-ID construction** | ≈ inside `build_evidence_units` (no public helper) | ✅ `euid.BlockBuilderEUIDs` | ✅ `blockBuilderEuIds` | c |
| Extraction (PDF/OOXML/HTML…) | ✅ extractors | 🔒 `core.Extract` | 🔒 `/ffi` `extract` | c |
| Markdown tables | ✅ | 🔒 `core.ToMarkdown` | 🔒 `/ffi` `toMarkdown` | c |
| **Provider contract: embedding** | ✅ `EmbeddingProvider.embed_many` | ✅ `contracts.EmbeddingProvider.Embed` | ✅ `EmbeddingProvider.embed` | **a** |
| **Provider contract: generation** | ✅ `GeneratorProvider.answer` | ✅ `contracts.GeneratorProvider.Answer` | ✅ `GeneratorProvider.answer` | **a** |
| Provider contract: completion / vision / rerank | ✅ ×3 | ⛔ | ⛔ | b |
| **Shipped embedding client** | ✅ `OpenAICompatibleEmbedding` | ✅ `models.NewOpenAIEmbedding` | ✅ `OpenAIEmbedder` | **a** |
| **Shipped chat generator** | ✅ `OpenAICompatibleGenerator` | ✅ `models.NewOpenAIChatGenerator` | ✅ `OpenAIChatGenerator` | **a** |
| Anthropic generator | ≈ `AnthropicHttpEndpoint` (endpoint, not client) | ✅ `models.NewAnthropicGenerator` | ✅ `AnthropicGenerator` | c |
| Reranker / vision client | ✅ ×2 | ⛔ | ⛔ | b |
| **`${ENV}` header auth** | ✅ `headers=` on every client | ✅ `models.HTTPClient` + `WithHeaders` | ✅ `HttpClient.resolveHeaders` | **a** |
| **Postgres/pgvector store** | ✅ storage seam | ✅ `PostgresVectorStore` | ✅ `PostgresVectorStore` | **a** |
| LanceDB store | ✅ `LanceVectorStore` | 🔒 `LanceVectorStore` | 🔒 `/ffi` `Store` | c |
| Config layer (`from_config`) | ✅ | ⛔ | ⛔ | b |
| Authority policy + floor | ✅ | ⛔ | ⛔ | b |
| Deep-ask / agentic loop | ✅ | ⛔ | ⛔ | b |
| Access / partitions | ✅ | ⛔ | ⛔ | b |
| Conversation memory | ✅ `conversation_id`, `recall` | ⛔ | ⛔ | b |
| S3 location | ✅ `S3(...)` | ⛔ | ⛔ | b |
| Hooks | ✅ `Hooks` | ⛔ | ⛔ | b |
| Durable worker queue | ✅ (standalone) | ⛔ | ⛔ | b |

---

## 3. Per-page table

`Langs` = languages actually shown today. `Verdict` per §0.

| # | Page | Samples | Langs today | Verdict | Note |
|---|---|---|---|---|---|
| 1 | `index.mdx` | 3 | py/go/ts (Tabs) | **d** | Correct shape; **two bugs** (B1, B2). Being rewritten concurrently — recheck. |
| 2 | `install.mdx` | 3 | sh ×3 (Tabs) | **d** | B3: `Go 1.23` vs `go.mod: go 1.26`; and "extraction … via cgo over the shared Rust engine" hides the `citenexus_ffi` build tag. |
| 3 | `quickstart.mdx` | 3 (1 sh-tabs + 2 py) | sh ×3, then py | **c** | Install step is 3-tab; the *flow* is Python. Already says so. Could gain a Go/JS `ask`-over-corpus tab. |
| 4 | `concepts.mdx` | 3 | py/go/ts (Tabs) | **a** ✅ | Correct and accurate. Reference model for the rest. |
| 5 | `ask.mdx` | 6 | py ×4, go, ts (Tabs at end) | **d** | B2 (JS `r`/`response`). Trust modes / conversation memory / `k` are Python-only and unlabelled. |
| 6 | `providers.mdx` | 5 | py ×3, go, ts | **c** ✅ | The *best* page in the repo — has an explicit "five in Python, two in the ports" table. Go/JS samples are bare fences, not `<Tabs>`. |
| 7 | `custom-endpoints.mdx` | 6 | py ×4, go, ts | **a** | Content is right and all three verified. Go/JS are bare fences at the bottom instead of tabs beside the Python. **Top structural win.** |
| 8 | `models.mdx` | 1 | py | **c** | Embedding + chat generator exist in all three (`models.NewOpenAIEmbedding` / `OpenAIEmbedder`); reranker + vision are Python-only. |
| 9 | `result.mdx` | 1 | py | **a** | `result.Result` (Go) and `Result` (TS) are field-for-field identical. Pure win. |
| 10 | `languages.mdx` | 6 | py ×6 | **d** | **B4 — the significant one.** Page says the ports are "ASCII-only" and non-Latin "abstains". `tokenizeV2` / `TokenizeV2` / `SUPPORTED_SCRIPTS` claim the **same 14 scripts in all three ports**; only the frozen v1 `ask` path is ASCII. The doc under-claims. |
| 11 | `reranking.mdx` | 4 | py ×4 | **c** | RRF exists in all three (`rrf.Fuse` / `rrfFuse`, plus core-backed `rrf`); the reranker *seam* and `retrieve()` are Python-only. |
| 12 | `ingest.mdx` | 4 | py ×4 | **c** | Claims "extraction runs in the shared Rust core … whether you call from Go, JavaScript, or Python" but shows no Go/JS and never mentions the build tag / subpath import. |
| 13 | `evaluate.mdx` | 2 (+1 csv) | py | **b** | `evaluate()` is Python-only. Needs an explicit note. |
| 14 | `revoke.mdx` | 4 | py ×4 | **c** ✅ | Already has an honest per-port table — but prose only. The storage-level `DeleteDocument` could be a real three-tab. |
| 15 | `signals.mdx` | 1 | py | **b** | `Signal` is a Python-config concept. |
| 16 | `graph.mdx` | 1 | py | **c** | Co-mention *build* is three-port (`BuildComentionGraph`); graph retrieval + distillers are Python-only. |
| 17 | `wiki.mdx` | 1 | py | **b** | Nothing in Go/JS. |
| 18 | `vision.mdx` | 2 | py | **b** | `VisionProvider` explicitly not published in the ports. |
| 19 | `authority.mdx` | 4 (+2 text) | py ×4 | **b** | Python-only; `providers.mdx` already says so — this page does not. |
| 20 | `access.mdx` | 1 | py | **b** | Python-only. |
| 21 | `scope.mdx` | 0 | — | **b** | Prose. Claims "polyglot at parity" without the facade caveat. |
| 22 | `s3.mdx` | 1 | py | **b** | `S3` is Python-only. |
| 23 | `file-based.mdx` | 1 | py | **b** | Facade. |
| 24 | `bulk-ingest.mdx` | 2 | py ×2 | **b** | Facade + Python-only worker queue. |
| 25 | `domain-rag.mdx` | 3 (2 py + csv) | py | **b** | Recipe page over the facade. **B6**: still says CiteNexus "has no jurisdiction/authority weighting" while `authority.mdx` ships the floor. |
| 26 | `benchmark-law.mdx` | 2 (bash + text) | bash | **b** | A Python run. Fine as-is. |
| 27 | `scenarios/index.mdx` | 1 | py | **b** | Facade construction. |
| 28 | `scenarios/contract-review.mdx` | 3 | py ×3 | **b** | Facade. |
| 29 | `scenarios/conflicting-sources.mdx` | 4 | py ×4 | **b** | Facade. Also contradicts `result.mdx` ("conflicts is reserved, not emitted"). |
| 30 | `scenarios/subject-scope.mdx` | 1 (+text) | py | **b** | Facade. |
| 31 | `scenarios/regulated-audit.mdx` | 2 | py ×2 | **b** | `reconcile`/`remediate` — Python-only. |
| 32 | `scenarios/right-to-erasure.mdx` | 2 (+text) | py ×2 | **b** | Facade `delete`. |
| 33 | `scenarios/multilingual-desk.mdx` | 2 | py ×2 | **b** | Facade + `answer_language`. |
| 34 | `scenarios/multilingual-corpus.mdx` | 1 | py | **b** | `search_languages` — Python-only. |
| 35 | `scenarios/evaluate-a-corpus.mdx` | 2 | py ×2 | **b** | `evaluate`/`retrieve` — Python-only. |
| 36 | `scenarios/support-assistant.mdx` | 5 | py ×5 | **b** | Facade. |

**Tally:** 36 pages. **9** can honestly carry a three-tab example
(4, 5, 7, 9, 10, 11, 14, 16, plus the tab-shell already on 1/2/3/6). **21** are
Python-only by nature (13, 15, 17–35 excluding those noted) and need one explicit
sentence. **6** carry a bug.

---

## 4. Bugs found (verdict d)

**B1 — `index.mdx:80` wrong import path shape + undefined variable.**
```ts
const r = ask(corpus, "…")
console.log(response.answer)      // `response` is not defined — `r` is
```
Same file, line 86–88. The package name `@muthuishere/citenexus` is correct
(`js/package.json`), but the variable is not. This sample does not run.

**B2 — `ask.mdx:88` the identical `r` / `response` mismatch.** Copy of B1.

**B3 — `install.mdx:481` says `Go 1.23`.** `golang/go.mod` declares `go 1.26`.
Same line claims the Go port gives extraction "via cgo over the shared Rust
engine" — true only under `-tags citenexus_ffi`; a plain `go get` reader gets a
package that does not compile `core`/`ingest` at all. `install.mdx:502-504` repeats
the claim ("extraction (PDF/DOCX/…), language detection") for both ports without
the tag or the `/ffi` subpath.

**B4 — `languages.mdx:20-55` under-claims the ports (the important one).**
The table's "Go / JS" column says `abstains` for all 13 non-Latin scripts, and the
Aside says *"The Go and JavaScript ports are still ASCII-only … the frozen
SPEC-PORTS-v1 §4 tokenizer (`[a-z0-9]+`)"*. In fact `golang/tokenize/tokenize_v2.go`
and `js/src/tokenize/tokenize-v2.ts` both carry the **same 14-script table**
generated from the shared conformance tables (`js/src/gen/tables.ts:141`), and both
ports ship `multilingual_test.go` / equivalent conformance tests for tokenize,
gate, bm25 and chunker. What *is* ASCII-only is the **frozen v1 `ask` path**:
`golang/answer` → `AskWith` → `gate.HasRelevanceOverlap` / `gate.IsSupported` (v1),
and `js/src/answer/answer.ts:18` imports v1 likewise. The honest statement is
"the ports' *tokenizer, gate-v2, BM25 and chunker* are at 14-script parity; the
pinned `ask` flow still runs the frozen v1 predicate and abstains on non-Latin."
This is a rare under-claim, and it hides the single biggest three-tab win on the site.

**B5 — the JS model clients are not re-exported from the package root.**
`custom-endpoints.mdx:132` writes `import { OpenAIEmbedder, HttpClient } from "@muthuishere/citenexus"`.
`HttpClient` is exported from the root (`js/src/index.ts:38` → `./http.js`), but
`js/src/index.ts` has **no** `export * from "./models/…"`. `OpenAIEmbedder` lives in
`js/src/models/embed.ts` with no root re-export and no `./models` subpath in
`package.json` `exports`. Same problem for `providers.mdx:368`
(`import { askWith } from "@muthuishere/citenexus"` — that one *is* fine, `askWith`
comes via `./answer/answer.js`). **Either the doc is wrong or `index.ts` is missing
a line** — worth confirming against a built `dist/` before publishing three-tab
model examples.

**B6 — `domain-rag.mdx:68-76` contradicts `authority.mdx`.** It states CiteNexus
"has no jurisdiction / precedence / source-credibility weighting … This is
architectural, not a tuning knob". `authority.mdx` ships exactly that as an opt-in
floor. `benchmark-law.mdx` already carries the "this gap is now closed" Aside;
`domain-rag.mdx` was not updated.

*(Adjacent, not a port issue: `scenarios/conflicting-sources.mdx` demonstrates
conflict surfacing while `result.mdx:721` says `conflicts` is reserved and never
populated. Worth a separate look.)*

---

## 5. Prioritised plan

### Tier 1 — highest reader value, genuinely all three ports (do first)

**P1. `languages.mdx` — fix B4, then three-tab the script check.** ~2h.
This is both the biggest correctness fix and the biggest capability reveal.
Replace the "Go / JS: abstains" column with two columns — *tokenizer/gate-v2/BM25*
(14 scripts, all ports) vs *pinned `ask` flow* (Latin only in Go/JS) — and add:
```
py: from citenexus.tokenize import tokenize_v2, scripts_in, unsupported_scripts, SUPPORTED_SCRIPTS
go: tokenize.TokenizeV2(text) · tokenize.ScriptsIn(text) · tokenize.UnsupportedScripts(text) · tokenize.SupportedScripts()
ts: import { tokenizeV2, scriptsIn, unsupportedScripts, SUPPORTED_SCRIPTS } from "@muthuishere/citenexus"
```
Same input (`"従業員は機密情報を開示してはならない"`), same token list in all three —
pinned by `conformance/`. Keep the honest caveat that Go/JS `ask` still abstains.

**P2. `result.mdx` — three-tab the `Result` walk.** ~1h. Zero new prose needed.
`py: from citenexus.answer.result import Result, Decision` ·
`go: result.Result` / `res.Evidence.Decision == result.DecisionAnswered` /
`res.Sources[0]` · `ts: Result`, `r.evidence.decision === Decision.answered`,
`r.sources[0]`. Add one line naming the casing difference (Python/TS snake_case,
Go PascalCase with matching `json` tags) — that *is* the parity story.

**P3. `custom-endpoints.mdx` — wrap the existing Go/JS in `<Tabs syncKey="lang">`.** ~1h.
The content is already correct and verified (`models.NewHTTPClient` + `WithHeaders`
+ `Transport()`; `HttpClient.send` / `resolveHeaders`). This is pure restructure —
move the two orphan fences up beside the Python and add a **Python-only** marker on
the `from_config` section. Resolve **B5** first.

**P4. `concepts.mdx` — already three-tab, keep as the template.** ~0.5h. Only
change: link the gate-v2 parity note so the "Python is ahead of the ports" claim
(currently on `index.mdx:118`) lives in one place.

**P5. `reranking.mdx` — three-tab RRF, name the Python-only rest.** ~1.5h.
```
py: from citenexus.retrieve import rrf_fuse            # fuses Candidate objects
go: rrf.Fuse([][]string{a, b}, rrf.DefaultK)           # fuses eu_id strings
ts: rrfFuse([a, b], 60)
```
State the shape difference honestly (it is real). Then mark the reranker seam,
`retrieve()`, and the signal→retriever table **Python only**.

### Tier 2 — real three-tab wins, slightly more writing

**P6. `ask.mdx`** ~1.5h — fix B2, and label trust modes / `conversation_id` / `k`
as Python-only ("Go and JS run strict unconditionally: `result.TrustModeStrict`").

**P7. New page: "The deterministic core" (chunking · gate · segmentation).** ~3h.
The three cleanest full-parity APIs on the whole project have **no page at all**:
`chunk_text` / `ChunkText` / `chunkText` (same three params, same defaults 450/60);
`is_supported_v2` / `IsSupportedV2` / `isSupportedV2` plus `align` / `Align` /
`align` with the pinned `MAX_SINGLE_GAP=4` / `MAX_TOTAL_GAP=8`; `split_claims` /
`SplitClaims` / `splitClaims`. This is the strongest possible demonstration of
"byte-for-byte identical", and it's the page most likely to answer the owner's
complaint outright.

**P8. `models.mdx`** ~1.5h — three-tab embedding + chat generation
(`OpenAICompatibleEmbedding` / `models.NewOpenAIEmbedding` / `OpenAIEmbedder`;
`OpenAICompatibleGenerator` / `models.NewOpenAIChatGenerator` / `OpenAIChatGenerator`),
then a hard line: **reranker and vision clients are Python-only** — the ports do
not publish those contracts (`providers.mdx` already proves it).

**P9. `providers.mdx`** ~1h — the content is already the gold standard. Only wrap
the Go/JS `AskWith`/`askWith` fences in `<Tabs>` and add the Python
`CiteNexus(embedder=…, generator=…)` tab so the injection point is one comparison.

**P10. `revoke.mdx`** ~1h — turn the existing port table into a real three-tab at
the storage level: `rag.delete(id)` (orchestration) vs
`store.DeleteDocument(id) error` vs `await store.deleteDocument(id)`, with the
"Python orchestrates the full unwind, the ports expose the row primitive"
framing the page already has.

**P11. `graph.mdx`** ~1h — three-tab `build_comention_graph` /
`BuildComentionGraph` / co-mention build, then mark `GraphRetriever`,
`LLMGraphDistiller` and the `graph` signal **Python only**.

**P12. `ingest.mdx` + `install.mdx`** ~2h — fix B3, and either show the
build-tag / subpath extraction path in three tabs
(`core.Extract` under `-tags citenexus_ffi` · `import { extract } from "@muthuishere/citenexus/ffi"` ·
Python extractors) or drop the "whether you call from Go, JavaScript, or Python"
sentence. Showing it honestly is better — but it must carry the tag.

### Tier 3 — the honest-note sweep (no fabrication possible)

**P13. One-line marker on 21 Python-only pages.** ~2h total.
Pages: `evaluate`, `signals`, `wiki`, `vision`, `authority`, `access`, `scope`,
`s3`, `file-based`, `bulk-ingest`, `domain-rag`, `benchmark-law`, and the 9
`scenarios/*`. Add a single shared component/badge, e.g.:

> **Python only.** This is part of the batteries-included facade. The Go and
> JavaScript ports ship the deterministic core — see [Install](/citenexus/install/)
> for what each port gives you.

Do **not** invent Go/JS equivalents for any of these. Every one of them fails the
matrix in §2.

**P14. Fix B6** (`domain-rag.mdx` authority contradiction) ~0.5h, and open a
separate question on the `conflicts` contradiction between
`scenarios/conflicting-sources.mdx` and `result.mdx`.

### Estimate

| Tier | Pages | Effort |
|---|---|---|
| 1 (P1–P5) | 5 | ~6h |
| 2 (P6–P12) | 7 (incl. 1 new page) | ~11h |
| 3 (P13–P14) | 21 + 1 | ~2.5h |
| **Total** | **36 pages touched** | **~19–20h**, ≈3 focused days |

Do Tier 1 first: it fixes the one factual error that runs *against* the project's
own standard (B4 under-claims), converts the five pages a reader hits earliest, and
establishes the `<Tabs syncKey="lang">` pattern the rest copy.

### The rule to hold

Before writing any Go or JS tab, the symbol must appear in §1's ground-truth
listing. If it doesn't, the page gets a **Python only** note instead. Nine pages
earn three tabs; twenty-one earn an honest sentence. "It's okay to say we don't
know" applies to ports too.
