# Code-block audit — CiteNexus docs site

Scope: every fenced code block under `site/src/content/docs/` (41 pages).
Branch `main`, repo state 2026-08-17. Read-only audit; no docs page was edited.

Requirement being audited: **"there should be never a single language code"** —
every sample shows Python / Go / JavaScript tabs, or the page says plainly why it
cannot.

Deciding constraint: **Python is the batteries-included facade; Go and JS are
core-only.** There is no `CiteNexus` class, no `ingest`/`ask`/`evaluate`/
`reconcile`/`delete`, no config layer, no authority policy, no vision, no
reranker client and no deep-ask in Go or JS. Nothing below invents a port symbol:
every symbol named here was read out of the source.

Totals: **160 code blocks**. 50 already tri-port tabbed · 91 Python-only (facade)
· 11 not code · 2 convertible · 2 partial · 2 port-only · **2 broken**.

---

## 1. BROKEN blocks (bugs, fix first)

| # | Page:line | Problem | Fix |
|---|---|---|---|
| B1 | `languages.mdx:212` | `from citenexus.config.schema import LanguageConfig` — **`LanguageConfig` does not exist**. `translate_citations` lives on `MultilingualConfig` (`python/src/citenexus/config/schema.py:247`, field at `:263`). The snippet raises `ImportError`. | `from citenexus.config.schema import MultilingualConfig` / `MultilingualConfig(translate_citations=True)` |
| B2 | `bring-your-own-model.mdx:43` | `def embed_many(self, texts: Sequence[str]) -> list[float]` — wrong return type. The published contract is `embed_many(texts) -> list[Vector]` where `Vector = list[float]` (`python/src/citenexus/contracts.py:104`), i.e. one vector **per input**. The body (`[self._vector(t) for t in texts]`) already returns `list[list[float]]`, so the annotation contradicts the code and fails `mypy --strict`. | `-> list[list[float]]` (or `-> list[Vector]` with `from citenexus import Vector`, matching `providers.mdx:58`) |

Two adjacent smells, not bugs, worth noting:

- `scenarios/regulated-audit.mdx:97` calls `read_audit(rag._backend, rag.partition)`
  — a **private** attribute. `read_audit` and both attributes exist
  (`reconcile/audit.py:36`, `client.py:158/160`), so the snippet runs, but the
  page documents a private seam as public API.
- `install.mdx:12` / `quickstart.mdx:19` use `go get …/golang` unpinned while the
  published tag is `v0.10.1`. Pinning (`@v0.10.1`) would match the pip/npm tabs.

---

## 2. Ground truth — the real public surface

### Python (`python/src/citenexus/__init__.py`, `client.py`) — the facade

- `CiteNexus` + `CiteNexus.from_config`; methods: `ingest`, `code`, `schema`,
  `revoke`, `delete`, `crawl`, `refresh_slow_path`, `retrieve`, `ask`, `stream`,
  `tools`, `evaluate`, `reconcile`, `remediate`, `recall`.
- Top-level `__all__`: `S3`, `CiteNexus`, `Hooks`, `DeleteResult`,
  `CorpusEntry`/`CorpusManifest`/`DriftedDocument`/`ReconcileReport`/`RemediationReport`,
  the contracts (`EmbeddingProvider`, `GeneratorProvider`, `CompletionProvider`,
  `RerankerProvider`, `VisionProvider`, `SingleTextEmbedder`, `SequenceEmbedder`,
  `Vector`), the four model clients (`OpenAICompatibleEmbedding`,
  `OpenAICompatibleGenerator`, `OpenAICompatibleReranker`,
  `OpenAICompatibleVision`), and the HTTP layer (`HttpClient`, `HttpEndpoint`,
  `OpenAIHttpEndpoint`, `GeminiHttpEndpoint`, `AnthropicHttpEndpoint`,
  `OpenRouterHttpEndpoint`, `OllamaHttpEndpoint`). `__version__ = "0.10.1"`.
- Deterministic core (deep paths, not top-level): `citenexus.tokenize.tokenize` /
  `tokenize_v2` / `scripts_in` / `unsupported_scripts` / `SUPPORTED_SCRIPTS` (14
  scripts) · `citenexus.answer.verify.is_supported` / `is_supported_v2` / `align`
  / `MAX_SINGLE_GAP=4` / `MAX_TOTAL_GAP=8` · `citenexus.answer.segment.split_claims`
  · `citenexus.evidence.chunker.chunk_text(text, *, max_tokens, overlap)` ·
  `citenexus.evidence.structure.build_structure` ·
  `citenexus.graph.store.build_comention_graph` ·
  `citenexus.retrieve.rrf_fuse(lists, k=60)` (**takes `Candidate` lists**, not ids).

### Go (`golang/`, module `github.com/muthuishere/citenexus/golang`)

Untagged — available to a plain `go get`:

| package | exported |
|---|---|
| `answer` | `Doc{DocumentID,Text}`, `DefaultTopK=5`, **`Ask(corpus, question, topK) result.Result`** (`answer/answer.go:46`), `Providers`, `AskWith(corpus, question, topK, Providers) (Result, error)`, `SplitClaims` |
| `result` | `Result`, `EvidenceSignals`, `SourceRef`, `Claim`, `ProvenanceEntry`, `BBox`, `LoopSignals`, `Decision`+`DecisionAnswered/Refused/Partial`, `TrustMode`+**`TrustModeStrict` only**, `RefusalAnswer`, `Refused()` |
| `gate` | `ContentTokens(V2)`, `HasRelevanceOverlap(V2)`, `IsSupported`, `IsSupportedV2`, `Align`, `AlignWithBudget`, `Alignment`, `PolarityMarkers` |
| `tokenize` | `Tokenize`, `TokenizeV2`, `ScriptOf`, `ScriptsIn`, `UnsupportedScripts`, `SupportedScripts()` (14), `ContinuousScripts`, `TokenizerVersion=2` |
| `chunker` | `ChunkText(text, maxTokens, overlap)` |
| `euid` | `BlockBuilderEUIDs`, `ChunkedBuilderEUIDs`, `Checksum`, `ChunkText` |
| `rrf` | `Fuse(lists [][]string, k) []string`, `DefaultK=60` |
| `bm25` | `Rank(rows, query)`, `Row`, `Result` |
| `graph` | `BuildComentionGraph(rows) Index`, `Node`, `Edge`, `Row` |
| `structure` | `BuildStructure(doc) Index` |
| `lang` | `ResolveAnswerLanguage`, `Detection`, `AutoAnswerLanguage` |
| `contracts` | `EmbeddingProvider`, `GeneratorProvider`, `SingleTextEmbedder`, `EmbedTexts`, `EmbedOne`, `SingleFrom`, `IsZeroVector`, `CheckVector`, `Vector` |
| `models` | `NewOpenAIEmbedding`, `NewOpenAIChatGenerator`, `NewAnthropicGenerator`, `NewHTTPClient`, `WithHeaders`, `ExpandEnv`, `Transport`, `SystemPrompt` |
| `storage` | `VectorStore`/`TextSearch` protocols, `PostgresVectorStore`, `PostgresTextSearch`, `TableNameFor` |
| `fakes` | `FakeEmbedding`, `FakeLLM`, `Cosine`, `Dim` |

**Behind `//go:build citenexus_ffi` — NOT reachable from a plain `go get`, must
never be shown as if it were:** `core` (`Version`, `Fuse`, `Extract`,
`ToMarkdown`, `Detect`, `Store` + `Open/Upsert/Search/Scan/DeleteDocument/Drop/Close`),
`ingest.Ingest`, `storage.LanceVectorStore` (`storage/lance_adapter.go`).

### JavaScript (`js/src/index.ts`, package `@muthuishere/citenexus` 0.10.1)

Root entry (dependency-free): `ask(corpus, question, topK=5)` (`js/src/answer/answer.ts:69`),
`askWith(corpus, question, providers)` — **topK rides inside `providers`**,
`CorpusDoc{document_id,text}`, `REFUSAL_ANSWER`; `splitClaims`; `bm25`; `rrfFuse`;
`chunkText`; `tokenize`, `tokenizeV2`, `scriptOf`, `scriptsIn`,
`unsupportedScripts`, `SUPPORTED_SCRIPTS` (a `ReadonlySet`, 14); `contentTokens(V2)`,
`hasRelevanceOverlap(V2)`, `isSupported`, `isSupportedV2`, `align` (→ `Alignment | null`),
`MAX_SINGLE_GAP`, `MAX_TOTAL_GAP`; `buildComentionGraph`; `buildStructure`;
`resolveAnswerLanguage`; the `Result` family + `Decision`/`TrustMode` enums
(**`TrustMode.strict` only**); contracts; `HttpClient` (`.send(url, body, headers)`),
`expandEnv`, `wireHeaders`; the model clients `OpenAIEmbedder`,
`OpenAIChatGenerator`, `AnthropicGenerator`; `PostgresVectorStore`; `fakes`.
**Native-only subpaths:** `@muthuishere/citenexus/ffi` (`Store`, `extract`,
`toMarkdown`, `detect`, `rrf`, `version`) and `/ingest` (`ingest`).

### Parity map for the operations the docs actually show

| operation | Python | Go | JS | verdict |
|---|---|---|---|---|
| answer over an in-memory corpus | *(facade only)* | `answer.Ask` | `ask` | port-side pair, Python differs |
| answer with injected providers | `CiteNexus(embedder=…, generator=…)` | `answer.AskWith` | `askWith` | shape-parallel |
| `Result` / signals / sources | `citenexus.answer.result` | `result` | `result` | **all three** |
| chunk text | `chunk_text` | `chunker.ChunkText` | `chunkText` | **all three** |
| faithfulness gate v2 + align | `is_supported_v2` / `align` | `gate.IsSupportedV2` / `gate.Align` | `isSupportedV2` / `align` | **all three** |
| claim segmentation | `split_claims` | `answer.SplitClaims` | `splitClaims` | **all three** |
| RRF fusion | `rrf_fuse` (Candidates) | `rrf.Fuse` (ids) | `rrfFuse` (ids) | all three, **signatures differ** |
| tokenizer v2 / scripts | `tokenize_v2` … | `tokenize.TokenizeV2` … | `tokenizeV2` … | **all three** |
| co-mention graph | `build_comention_graph` | `graph.BuildComentionGraph` | `buildComentionGraph` | **all three** (undocumented) |
| structure index | `build_structure` | `structure.BuildStructure` | `buildStructure` | **all three** (undocumented) |
| BM25 | only inside `LexicalRetriever` | `bm25.Rank` | `bm25` | **Go+JS only — do not fake a Python tab** |
| embedding + chat model clients | `OpenAICompatible*` | `models.New*` | `OpenAIEmbedder`/`OpenAIChatGenerator` | **all three** |
| reranker / vision clients | yes | — | — | **Python only** |
| ingest / ask / evaluate / delete / reconcile / crawl / memory / authority / deep-ask / config / access / S3 | yes | — | — | **Python only** |
| file→store ingest | `rag.ingest` | `ingest.Ingest` **(`citenexus_ffi` tag)** | `/ingest` subpath | Python plain; ports native-only |

---

## 3. Per-block inventory

Legend: **TABBED** = already inside a complete `<Tabs syncKey="lang">` group with
Python + Go + JS · **PY-ONLY** = facade, no port equivalent · **NOT CODE** =
shell/CSV/JSON/ASCII.

### Already tri-port (50 blocks — verified against source, no changes needed)

| Page | Lines | Blocks | What | Verified |
|---|---|---|---|---|
| `install.mdx` | 12/18/24 | 3 sh | `go get` · `npm install` · `pip install` | ✅ names match go.mod / package.json / pyproject |
| `quickstart.mdx` | 19/24/29 | 3 sh | install | ✅ |
| `quickstart.mdx` | 100/117 | 2 (go, ts) | hermetic `Ask`/`ask` | ✅ Python tab is prose + a pointer, deliberate and explained |
| `index.mdx` | 214/235/248 | 3 | corpus → answer / facade | ✅ |
| `ask.mdx` | 117/127/137 | 3 | answered-vs-refused branch | ✅ `result.DecisionAnswered`, `res.Sources[0].Passage` |
| `concepts.mdx` | 103/118/133 | 3 | grounded vs refused | ✅ `Doc{DocumentID,Text}` / `{document_id,text}` |
| `result.mdx` | 19/35/60 | 3 | reading a `Result` | ✅ Go `Page *int`; JS snake_case `answer_language`/`missing_evidence`/`passage_language` |
| `deterministic-core.mdx` | 37/45/53 | 3 | `chunk_text` | ✅ |
| `deterministic-core.mdx` | 78/95/114 | 3 | `is_supported_v2` + `align` + gap consts | ✅ 4/8 in all three; JS `align` → `null` |
| `deterministic-core.mdx` | 155/163/171 | 3 | `split_claims` | ✅ Go's lives in package `answer` |
| `languages.mdx` | 67/81/93 | 3 | tokenizer v2 + scripts | ✅ 14 scripts in all three; `.size` for the JS `Set` |
| `languages.mdx` | 123/130/141 | 3 | Japanese corpus answer | ✅ |
| `custom-endpoints.mdx` | 26/41/59 | 3 | embedding client + `${ENV}` headers | ✅ `embed_many` · `WithHeaders` · `OpenAIEmbedder` + `HttpClient.send` |
| `custom-endpoints.mdx` | 88/99/109 | 3 | chat generator client | ✅ config keys `base_url`/`model`/`headers` |
| `custom-endpoints.mdx` | 229/241/251 | 3 | raw HTTP transport | ✅ py `HttpClient.__call__`, Go `client.Do`, JS `http.send` |
| `reranking.mdx` | 105/112/120 | 3 | RRF fusion | ✅ divergence (Candidates vs ids) is already stated in prose |
| `bring-your-own-model.mdx` | 111/127/143 | 3 | provider contracts | ✅ Go `AskWith(…, topK, Providers)`; JS `askWith(corpus, q, {…, topK})` |
| `providers.mdx` | — | — | see PORT-ONLY below | ⚠ the go/ts blocks are **not** in a Tabs group |

### Convertible (2)

| Page:line | What it does | Now | Verdict | Symbols per tab |
|---|---|---|---|---|
| `abstention.mdx:14` | prints `evidence.decision`, `missing_evidence`, `evidence` off a refusal | python | **CONVERT** | Go: `res := answer.Ask(corpus, q, answer.DefaultTopK)` → `res.Evidence.Decision` (`result.DecisionRefused`), `res.MissingEvidence`, `res.Evidence` · JS: `ask(corpus, q)` → `res.evidence.decision`, `res.missing_evidence`, `res.evidence` (only the producing line changes) |
| `languages.mdx:222` | reads `src.passage` / `src.translation` | python | **CONVERT** | Go: `src.Passage`, `src.Translation` (`*string`) · JS: `src.passage`, `src.translation` |

### Partial (2)

| Page:line | What | Verdict |
|---|---|---|
| `models.mdx:17` | constructs 4 model clients and wires them into `CiteNexus` | **PARTIAL** — embedding + chat generator exist in all three (`models.NewOpenAIEmbedding` / `NewOpenAIChatGenerator`; `OpenAIEmbedder` / `OpenAIChatGenerator`); **reranker and vision clients are Python-only**, and the `CiteNexus(...)` wiring is Python-only. Split the block: a tri-port "build the two clients" tab group + a Python-only "wire them in" block. |
| `providers.mdx:58` | full in-process provider, then `CiteNexus` + ingest + ask | **PARTIAL** — the two provider classes convert cleanly (Go `contracts.EmbeddingProvider`/`GeneratorProvider` + `answer.AskWith`; JS `EmbeddingProvider`/`GeneratorProvider` + `askWith`); the ingest/ask tail is facade-only. Split at the `rag = CiteNexus(...)` line. |

### Port-only (2)

| Page:line | Lang | Verdict |
|---|---|---|
| `providers.mdx:348` | go | **PORT-ONLY** — `answer.AskWith` + compile-time `var _ contracts.EmbeddingProvider = (*MyEmbedding)(nil)`. Correct, but sits alone with no Tabs wrapper. |
| `providers.mdx:366` | ts | **PORT-ONLY** — `askWith(corpus, q, {embedding, generator, topK})`. Correct (topK inside providers ✅). Fold both into one Tabs group with the Python provider half of `:58`. |

### Not code (11)

| Page:line | Kind | Port tab meaningful? |
|---|---|---|
| `architecture.mdx:18` | ASCII ingest pipeline | No — but the page should state the pipeline is the **Python facade's**; Go/JS expose only the deterministic stages |
| `architecture.mdx:63` | ASCII ask pipeline | Same note |
| `authority.mdx:108` | authority CSV data | No |
| `authority.mdx:150` | ASCII authority flow | No |
| `benchmark-law.mdx:197` | bash example runner | No — the harness is a Python script |
| `domain-rag.mdx:47` | golden CSV | No |
| `evaluate.mdx:24` | golden CSV | No |
| `scenarios/contract-review.mdx:46` | sample cited output | No |
| `scenarios/evaluate-a-corpus.mdx:31` | golden CSV | No |
| `scenarios/right-to-erasure.mdx:54` | ASCII blob-lifecycle | No |
| `scenarios/subject-scope.mdx:62` | sample EU text | No |

### Python-only, facade (91)

Every one of these calls a verb that **does not exist** in Go or JS. Nothing here
should be tabbed; each page needs one honest note instead (see §5).

| Page | Lines | n | What (grouped) |
|---|---|---|---|
| `access.mdx` | 38 | 1 | `resolve_scope` / `filter_partitions` / `acl=` — `citenexus.access` has no port |
| `ask.mdx` | 13, 27, 77, 104 | 4 | facade branch · `ask()` signature · `TrustMode.exploratory` (**ports have `strict` only**) · `conversation_id` memory |
| `authority.mdx` | 41, 71, 117, 139, 182 | 5 | `AuthorityPolicy`, `AuthorityConfig`, `authority=` on ingest, ask, signals. **Go/JS carry `authority_tier`/`authority_floor_applied` for wire parity only and always emit empty/false** — a port tab here would be a false capability claim |
| `bring-your-own-model.mdx` | 66 | 1 | `CiteNexus(embedder=…, generator=…)` |
| `bulk-ingest.mdx` | 13, 36 | 2 | ingest loop · `crawl` |
| `custom-endpoints.mdx` | 132, 164, 179, 197 | 4 | vision client (page already says "Python only" ✅) · endpoint presets · `HttpEndpoint` · `CiteNexusConfig` |
| `domain-rag.mdx` | 18, 29, 57 | 3 | ingest · ask · must-refuse assertions |
| `evaluate.mdx` | 11, 47 | 2 | `evaluate()` · must-refuse |
| `file-based.mdx` | 9 | 1 | `CiteNexus` + `ingest`. Note: Go/JS file ingest exists **only** behind `citenexus_ffi` / the `/ingest` subpath and has no `ask` facade |
| `graph.mdx` | 20 | 1 | `signals=[…,"graph"]` + ask |
| `index.mdx` | 61 | 1 | `search_languages=` |
| `ingest.mdx` | 11, 22, 42 | 3 | source kinds · `IngestResult` · `crawl` |
| `languages.mdx` | 189, 234, 280, 323 | 4 | `ReformulationConfig` · `search_languages` · `answer_language` · `HeuristicDetector` |
| `providers.mdx` | 197, 218 | 2 | facade wiring · mixing own+shipped |
| `quickstart.mdx` | 40, 58 | 2 | construct · ingest+ask (page explains the facade split ✅) |
| `reranking.mdx` | 37, 56, 78 | 3 | `signals=` · `OpenAICompatibleReranker` (**no port reranker**) · `top_k` / `retrieve` |
| `revoke.mdx` | 14, 31, 65, 82 | 4 | delete/revoke · `DeleteResult` repr · idempotence · `Hooks` |
| `s3.mdx` | 11 | 1 | `S3(...)` storage |
| `signals.mdx` | 12 | 1 | `signals=` |
| `vision.mdx` | 21, 37, 93, 113, 127 | 5 | vision client + the two-phase `build_pending_request` / `fulfill_vision_requests` / `build_vision_units` (all Python-host only) |
| `wiki.mdx` | 18 | 1 | `signals=[…,"wiki"]` |
| `scenarios/conflicting-sources.mdx` | 16, 27, 48, 132 | 4 | ingest · conflicts · trust modes · dedup signals |
| `scenarios/contract-review.mdx` | 17, 24, 31, 66, 94 | 5 | ingest · ask · branch · signals · `PartitionPath` |
| `scenarios/evaluate-a-corpus.mdx` | 42, 53, 68, 109, 137 | 5 | evaluate · must-refuse · regression asserts · signals · `retrieve` (`c.citable_text` ✅ exists as a property) |
| `scenarios/index.mdx` | 65 | 1 | construct with model clients |
| `scenarios/multilingual-corpus.mdx` | 32, 45, 57, 70 | 4 | `ReformulationConfig` · `search_languages` · language fields · `UnsupportedSearchLanguageError` ✅ |
| `scenarios/multilingual-desk.mdx` | 18, 26, 32, 56, 82 | 5 | ingest · ask · language fields · `answer_language` · `unsupported_scripts` |
| `scenarios/regulated-audit.mdx` | 25, 42, 55, 97 | 4 | `CorpusManifest`/`CorpusEntry` ✅ · `reconcile` ✅ · `remediate` ✅ · `read_audit` (private-attr smell) |
| `scenarios/right-to-erasure.mdx` | 26, 37, 81 | 3 | delete · reconcile · shared-blob |
| `scenarios/subject-scope.mdx` | 110 | 1 | ingest with `authority=` |
| `scenarios/support-assistant.mdx` | 17, 24, 30, 47, 58, 75, 92, 104 | 8 | ingest · ask · branch · missing_evidence · memory · trust modes · reply · delete |

---

## 4. Counts

| Verdict | Blocks |
|---|---|
| Already tri-port TABBED | 50 |
| PYTHON-ONLY (facade) | 91 |
| NOT CODE | 11 |
| CONVERT | 2 |
| PARTIAL | 2 |
| PORT-ONLY | 2 |
| **BROKEN** | **2** |
| **Total** | **160** |

Pages with **zero single-language code blocks today**: `install.mdx`,
`concepts.mdx`, `result.mdx`, `deterministic-core.mdx` (+ `faithfulness.mdx`,
`scope.mdx`, which contain no code at all) — **6 of 41**.

After the plan in §5 (converting the 2 CONVERT blocks and splitting the 2 PARTIAL
ones) `abstention.mdx` and `models.mdx` join them; every remaining page keeps
Python-only blocks by necessity and is closed out with a stated reason instead.
Realistic end state: **8 pages with zero single-language blocks, 33 pages carrying
an explicit "why Python only" note.**

---

## 5. Prioritised conversion plan

**P0 — fix the two BROKEN blocks** (`languages.mdx:212` → `MultilingualConfig`;
`bring-your-own-model.mdx:43` → `list[list[float]]`). Both are wrong-as-published.

**P1 — one reusable note component, applied to all 33 facade pages.** This is what
actually satisfies the requirement for the 91 Python-only blocks; tabs are
impossible there and inventing them is the failure mode the owner banned. Suggested
single sentence, page-level Aside:

> `ingest` / `ask` / `evaluate` are the **Python facade**. The Go and JavaScript
> packages ship the same deterministic core (`Ask`/`ask`, the faithfulness gate,
> the tokenizer, chunking, RRF, `Result`) but no store, no config and no facade —
> see [Deterministic core](/citenexus/deterministic-core/).

Variants where the reason is sharper:
- `authority.mdx` — "Go/JS carry `authority_tier` / `authority_floor_applied` for
  wire parity only and always emit the empty defaults; authority selection runs in
  the Python facade."
- `ask.mdx:77`, trust modes — "the ports define `TrustMode.strict` only."
- `vision.mdx`, `reranking.mdx:56`, `custom-endpoints.mdx:132` — "the vision and
  reranker clients exist only in Python."
- `file-based.mdx` — "Go/JS file ingest is native-only: Go build tag
  `citenexus_ffi`, the JS `/ingest` subpath."
- `architecture.mdx` — "this pipeline is the Python facade's."

**P2 — `providers.mdx` (4 blocks, highest single-page win).** Wrap `:348` (go) and
`:366` (ts) together with the provider half of `:58` into one
`<Tabs syncKey="lang">`: Python `EmbeddingProvider`/`GeneratorProvider` +
`isinstance` shape check · Go `contracts.EmbeddingProvider` +
`answer.AskWith(corpus, q, answer.DefaultTopK, answer.Providers{Embedding:…, Generator:…})`
· JS `askWith(corpus, q, {embedding, generator, topK})`. Keep the
`CiteNexus(...)` tail as a separate Python-only block with the P1 note.

**P3 — the two CONVERT blocks.** `abstention.mdx:14` and `languages.mdx:222`
(exact symbols in §3).

**P4 — `models.mdx:17` split.** Tri-port group for the two shipped clients
(`OpenAICompatibleEmbedding`/`OpenAICompatibleGenerator` ·
`models.NewOpenAIEmbedding`/`models.NewOpenAIChatGenerator` ·
`OpenAIEmbedder`/`OpenAIChatGenerator`), then a Python-only block for
reranker + vision + `CiteNexus(...)` with the reason stated.

**P5 — pin the install tabs** (`install.mdx:12`, `quickstart.mdx:19`) to
`@v0.10.1` so all three tabs pin the same release.

**P6 — optional new tri-port blocks (real parity, currently undocumented).** These
add port coverage without touching a facade page:
- `graph.mdx` — `citenexus.graph.store.build_comention_graph` ·
  `graph.BuildComentionGraph` · `buildComentionGraph`.
- `deterministic-core.mdx` — `build_structure` / `structure.BuildStructure` /
  `buildStructure`; and `tokenize` v1 in all three.
- **Do not** add a BM25 tri-port block: `bm25.Rank` / `bm25` exist in Go and JS,
  but Python exposes BM25 only inside `LexicalRetriever`. That one is genuinely
  PARTIAL — say so, don't fake a Python tab.
