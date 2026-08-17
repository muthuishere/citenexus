# CiteNexus
[![Discord](https://img.shields.io/badge/AgentNexus-join%20the%20community-5865F2?logo=discord&logoColor=white)](https://discord.gg/V9C2kvHC8D)

> **Retrieval finds passages. CiteNexus proves the answer follows from one that
> governs — in 14 scripts — and refuses when it can't.**

[![Go Reference](https://pkg.go.dev/badge/github.com/muthuishere/citenexus/golang.svg)](https://pkg.go.dev/github.com/muthuishere/citenexus/golang)

CiteNexus is an **evidence-integrity layer** over retrieval, for domains where a
wrong answer is worse than no answer — legal, medical, finance/compliance,
enterprise search. It is not a better retriever. It is the set of deterministic
checks that stand between a retrieved passage and a claim you would be willing to
defend. The guarantee is **"no ungrounded claim,"** not "zero hallucination."

📖 **Docs: [muthuishere.github.io/citenexus](https://muthuishere.github.io/citenexus/)**

## Install

```bash
pip install citenexus                                  # 0.10.1 — the Python facade
npm install @muthuishere/citenexus                     # 0.10.1 — the deterministic core
go get github.com/muthuishere/citenexus/golang@v0.10.1 # resolves the golang/v0.10.1 tag
```

> **Upgrade off 0.10.0 if you use the Go or JS `Ask`/`ask`.** 0.10.0 shipped the
> per-claim faithfulness gate to three registries, but the Go and JS answer paths
> still ran the *old* predicate — the one that accepted 9 of 9 adversarial false
> answers. 0.10.1 fixes it. See the [changelog](CHANGELOG.md).

## Repository layout (polyglot)

One repo, one language per top-level folder, shared contract in the middle:

```
python/       reference FACADE (ingest/retrieve/ask/evaluate) — PyPI `citenexus`
golang/       Go deterministic core + hermetic ask + model clients — `github.com/muthuishere/citenexus/golang`
js/           TypeScript deterministic core + hermetic ask + model clients — npm `@muthuishere/citenexus`
rust/         Rust core (extraction, store, lid.176) — crates.io `citenexus-core`
conformance/  shared cross-language fixtures — the real contract; a fixture edit breaks any drifting port
docs/  openspec/  .github/   design, specs, and CI shared across all languages
```

**Python is the facade; Go and JS are the core, not a facade.** `ask()` with
retrieval, storage, reranking, authority and the `search_languages` fan-out is
Python. The ports ship the pinned deterministic algorithms — tokenizer v2, BM25,
RRF, the chunker, the faithfulness predicate — plus a hermetic `Ask` over an
in-memory corpus. Anything a doc claims for "all ports" should be read against
the parity table below.

Each language folder is self-contained (its own build file + tests). The repo
tracks one version (`0.10.1`), but the **registries are not uniform**: PyPI
`citenexus` and npm `@muthuishere/citenexus` are at 0.10.1, while npm
`@muthuishere/citenexus-core` is at 0.8.0 and the crates.io `citenexus-core`
crate at 0.5.0 — both behind this repo. The Go module is a monorepo submodule
tagged `golang/vX.Y.Z`; docs at
[pkg.go.dev](https://pkg.go.dev/github.com/muthuishere/citenexus/golang).

### Native core & distribution (roadmap)

The heavy, must-be-identical stages — binary-document extraction, `lid.176`
detection, and the Lance store — live once in the Rust core (`rust/`, a C-ABI
cdylib). Today the Go/JS/Python ports reimplement the pure logic and bind that
core opt-in (Go behind the `citenexus_ffi` build tag; JS via `koffi`; Python via
`ctypes`). **Planned (not yet shipped):** ship the core as a **prebuilt,
per-platform** library so every binding auto-loads it with **no toolchain** —
Python via platform wheels, TS via npm `optionalDependencies`, Go via `go:embed`
+ `purego` — plus a shared `lid.176` fetch-cache with SHA256 verification, built
by a two-tier CI (rare cross-compile matrix → durable release; per-tag repackage
→ PyPI / npm / Go via OIDC). The **load seam is proven** across linux x64+arm64,
macOS arm64, and windows x64 (`spikes/prebuilt-ffi/`); cross-compiling the full
core and the packaging are still in progress.


## Five ways a grounded answer is still wrong

Every one of these produces output where **every visible signal says trust me**:
verbatim text, a real document, a page, 100% groundedness. That is worse than an
obviously ungrounded answer, because there is nothing to notice. Each is closed
by a deterministic check, and each was closed only after it was **measured
failing**.

| # | The failure | What closes it | Measured |
|---|---|---|---|
| 1 | **The words came from the passage — the claim didn't follow.** Set containment is closed under reordering (swap the parties and the token set is identical) and deletion (drop the `not` and you have a subset). | Ordered, gap-bounded containment with a **polarity guard**, applied **per atomic claim**, drop-not-fail. (ADR-0009) | 9 of 9 adversarial false answers accepted before, across five domains, identically in Python, Go and JS. 0 of 30 false rejections on a legitimate-support control. → [Faithfulness](https://muthuishere.github.io/citenexus/faithfulness/) |
| 2 | **Two sources disagree and rank order quietly picks one.** The top hit wins and you never learn there was a second answer. | Conflict is detected deterministically and **surfaced, never resolved** — resolution is your policy call. Strict mode abstains and cites **both sides**. (ADR-0007) | 0 false positives on 27 hard negatives, 0 on 22 unrelated pairs, 0 on 10 held out after the thresholds froze. Recall 0.889 — precise, not exhaustive. |
| 3 | **The cited source has no authority over the question.** A Florida statute answered a Texas question with a real quote, a correct citation, and `all_claims_verified: true`. | An authority floor over **curator-asserted** tiers supplied at ingest — the library never infers standing from prose — applied after grounding, before generation. (ADR-0004) | Live California landlord–tenant corpus: out-of-jurisdiction citations **4 → 0**, abstain-when-no-evidence **33% → 100%**, groundedness 100% throughout. → [Authority](https://muthuishere.github.io/citenexus/authority/) |
| 4 | **The governing document is in a script the system can't read.** The English handbook answers, verbatim and correctly cited — while a binding Telugu annexure says something else. | A Unicode tokenizer makes it *citable*; `search_languages` makes it *reachable*. Both required, neither sufficient. (ADR-0011, ADR-0013) | 12-doc EN/TA/TE corpus: answered-when-groundable **44% → 89%**, cited-the-right-document **75% → 100%**, abstain-when-ungroundable **unchanged at 100%**. |
| 5 | **A model failed and the corpus was silently poisoned.** A Go embedder that timed out returned a zero vector, and ingest indexed it. Retrieval then quietly stops finding a document that is provably present. | Failure is expressible in the seam: the embedding contract returns an error, and the write path refuses empty, wrong-dimension, non-finite and all-zero vectors. (ADR-0014) | *Enforced in the Go and JS cores. In Python it remains an obligation stated on the provider contract, not an enforced write-path check.* |

→ [How it holds the line](https://muthuishere.github.io/citenexus/abstention/) ·
[Architecture](https://muthuishere.github.io/citenexus/architecture/) ·
[Deterministic core](https://muthuishere.github.io/citenexus/deterministic-core/)

## Languages — 14 scripts, at parity across all three ports

Latin, Cyrillic, Greek, Arabic, Hebrew, Devanagari, Bengali, Tamil, Telugu, Han,
Hiragana, Katakana, Hangul, Thai — each backed by a golden conformance fixture,
because **a script is claimed only when its evidence exists**. Space-less scripts
(Han, Kana, Thai) are indexed by character bigrams, which do not cross script
boundaries.

The same 14 are claimed in **Python, Go and JavaScript**: the tokenizer v2 table
is shared (`conformance/cases/tokenize_v2.json`) and drives BM25 and the
faithfulness predicate in every port. *(Older docs said the ports were
"Latin-script only". That was an undercount, and it is wrong.)*

Khmer, Lao, Myanmar, Georgian, Armenian, Kannada, Malayalam, Gujarati and Sinhala
are deliberately **not claimed**: a bigram path mechanically "works" for several
of them, and answering through an unfixtured segmentation is worse than refusing.
An unclaimed script produces **zero tokens and a refusal, by name**, before a
model call is spent — reported as `EvidenceSignals.unsupported_scripts`, a
**capability signal, not an evidence judgement**. Background:
[`docs/adr/0011`](docs/adr/0011-tokenizer-and-non-latin-scripts.md).

**Searching and answering are two knobs.** `search_languages` decides what gets
retrieved (default `("en",)`); `answer_language` decides what comes back. The
citation never moves: **a translated quote is not the evidence**, so it stays
verbatim in its source language and `sources[*].passage_language` tells you which
that is — which means an English answer can legitimately carry a Telugu citation.
→ [Languages](https://muthuishere.github.io/citenexus/languages/)

## Bring your own model — swap the transport

The library bundles **no models**. The shipped clients already know how to build
an OpenAI-shaped request, expand `${ENV}` secrets at the HTTP boundary, batch,
and parse the response. What they do not need to know is whether the bytes travel
over a socket — so bring your own model by replacing that one function:

```python
from citenexus import OpenAICompatibleGenerator

gen = OpenAICompatibleGenerator(
    base_url="http://in-process.invalid",   # never dialled
    model="qwen2.5-1.5b",
    transport=my_transport,                 # <- this line, and nothing else
)
```

`Transport` is `Callable[[str, bytes, dict[str, str]], bytes]` —
`(url, json body, headers) -> response bytes` (`python/src/citenexus/http.py:36`).
There is no class to subclass. It is **keyword-only** on all four clients
(`OpenAICompatibleEmbedding`, `OpenAICompatibleGenerator`,
`OpenAICompatibleReranker`, `OpenAICompatibleVision`, all importable top-level
from `citenexus`) and genuinely tri-port: Go `models.Transport`, JS `Transport`.

For a model that cannot be made OpenAI-shaped, `citenexus.contracts` holds seven
`runtime_checkable` Protocols — `EmbeddingProvider`, `GeneratorProvider`,
`CompletionProvider`, `VisionProvider`, `RerankerProvider`, `SingleTextEmbedder`,
`SequenceEmbedder`. That is the **escape hatch**, not the front door.
→ [Bring your own model](https://muthuishere.github.io/citenexus/bring-your-own-model/)

**Secrets never enter a constructor.** Auth is `${ENV}`-in-headers, expanded only
at the request boundary.

**Scope — document-evidence RAG, on purpose.** CiteNexus ingests *artifacts*
(PDF, DOCX, PPTX, HTML, MD, TXT, CSV, images-into-evidence) and answers over
them. It is deliberately **not** a source-code / call-graph tool (use a dedicated
one — evaluated and declined for this core), a memory "brain", a model host, or
an end-user app — it's a library; CLIs, dashboards, and agents are built *on* it.
The filter for what lands here: a capability must ingest an artifact or improve
grounded retrieval / evaluation **and** hold the "no ungrounded claim" bar.

**CiteNexus supports pluggable vector databases.** Storage is two protocols —
`VectorStore` (dense) and `TextSearch` (lexical) — and each backend is a named
(vector, text) pair:

| Backend | Vector | Text | When |
|---|---|---|---|
| **Lance** (recommended) | `LanceVectorStore` | `LanceTextSearch` (BM25-lite) | Zero infra, S3-native: point at a bucket and go |
| **Postgres** | `PostgresVectorStore` (pgvector) | `PostgresTextSearch` (native `tsvector`) | You already run Postgres — `pip install 'citenexus[postgres]'`, set `vector_store.backend: "postgres"` |
| **Yours** | implement `VectorStore` | implement `TextSearch` | Qdrant, Weaviate, Elasticsearch, Tantivy, … |

The seams are independent: mix LanceDB vectors with an Elasticsearch
`text_search=`, or let one Postgres serve both.

```python
from citenexus import CiteNexus, S3

rag = CiteNexus(
    S3(bucket="my-bucket"),
    embedder=my_embedding_endpoint,
    generator=my_llm_endpoint,
)
rag.ingest("policy.pdf")                         # any supported input type — SYNCHRONOUS
response = rag.ask("Can the employee disclose this information?")

print(response.answer)                              # the verbatim quote — or the pinned refusal
print(response.evidence.decision)                   # "answered" | "refused"
print(response.evidence.all_claims_verified)        # every claim survived the gate
print(response.evidence.unsupported_claims_removed) # how many did not
print(response.sources[0].document, response.sources[0].page)   # guard: empty on a refusal
```

`ingest()` is synchronous — **there is no `ingest_async`**, in any port. The
durable worker queue (`worker/queue.py`) buys *durability* — retry/backoff, DLQ,
idempotent-by-hash, resume — not concurrency, and is not reachable from the
`CiteNexus` constructor today.

**The client scales to exactly what you give it** — every model is optional,
and every rung below is additive (nothing above it changes):

```python
rag = CiteNexus("./data")                     # a folder…
rag = CiteNexus(S3(bucket="docs",             # …or real S3/MinIO/R2: ONE object
                   endpoint_url="https://<r2>.cloudflarestorage.com"))
                                              #    carries endpoint + credential
                                              #    env-var names for BOTH stores
# ZERO models — already FOUR retrieval signals, fused with RRF:
#   text (BM25) · structure (heading tree) · graph (co-mention) · wiki (page nav)
rag.ingest("handbook.pdf")
rag.retrieve("termination notice")            # works immediately, cited rows

rag = CiteNexus("./data", embedder=e)         # + vector signal (5-way hybrid RRF)
rag = CiteNexus("./data", ..., generator=g)   # + ask()/stream()/evaluate() — cite-or-abstain
rag = CiteNexus("./data", ..., reranker=r)    # + cross-encoder ordering of the fused pool
rag = CiteNexus("./data", ..., wiki_distiller=w)   # wiki pages become LLM-distilled,
                                                   #   cross-linked concept pages (+ Markdown tree in S3)
rag = CiteNexus("./data", ..., contextualizer=c)   # + Anthropic-style contextual chunk prefixes
rag = CiteNexus("./data", ..., reformulator=q)     # + EN dual-query RRF (cross-lingual recall)
rag = CiteNexus("./data", ..., vision=v)           # + images in PDFs/docs become described, cited evidence
rag = CiteNexus("./data", ..., detector=d)         # + real lid.176 language detection
rag = CiteNexus("./data", ..., sink=s, hooks=h)    # + telemetry (tokens/cost) + lifecycle hooks
rag = CiteNexus("./data", ..., vector_store=pg, text_search=es)  # + bring your own stores

rag.ask("...", conversation_id="c1")          # conversation memory — built in, no param
```

Or declare it all in one typed config: `CiteNexus.from_config(cfg)` builds only
what the config enables. `ask()` without a generator raises a clear error
pointing at `retrieve()` — search-only deployments are first-class, not a crash.

## What it ingests, what it does

**Extractors** (`python/src/citenexus/extract/`) — one plugin per file type,
routed by `dispatch.py`: PDF (`pdf.py`, via `pdfplumber` — per-page text + word
bboxes), DOCX (`docx.py`, via `python-docx` — heading tree + paragraphs), PPTX
(`pptx.py` — one block per slide), XLSX (`xlsx.py`), HTML (`html.py`), Markdown
(`md.py`), CSV (`csv.py`), plain text (`txt.py`), and an unknown-type fallback
(`plain.py`).
Anything not on the list falls through to plain-text rather than failing
ingest.

**Tables** — real, structured table extraction ships across **CSV, PDF, DOCX,
PPTX, HTML, and XLSX**. Each renders a table's rows as `EUType.table` evidence
(header row as schema, `"col: value"` pairs, `structure_path` = header) — a
genuine table-aware evidence type, not flattened text. `PdfExtractor` locates
ruled/aligned tables via `page.find_tables()`
(`extract/pdf.py::_extract_tables`), `DocxExtractor` iterates `document.tables`,
and CSV/PPTX/HTML/XLSX each have their own table path. A tabular cell stays
citable by page like any other unit.

**Image-to-text via a vision model** — figures are described through a
**two-phase, host-fulfilled seam** (ADR-0005) so the polyglot core never holds
the API key or opens a socket: the core **emits** model-ready
`PendingVisionRequest`s (a base64 `image_url` data URI + prompt + the figure's
`source_ref`), the host **fulfills** them with its own transport, and the core
**assembles** the descriptions into `EvidenceUnit(type=figure)`s cited by
page like any other unit. `ingest/pipeline.py`'s `_emit_vision_requests()`
runs the §9 gate and builds the requests; `vision/fulfill.py`'s
`fulfill_vision_requests()` is the reference fulfiller (wrapping the injected
`VisionPlugin`, its own auth/concurrency); `vision/units.py`'s
`build_vision_units()` is the assemble half (join on `request_id`).
`vision/client.py`'s `OpenAICompatibleVision` is the concrete client — posts the
payload to any OpenAI-compatible `/chat/completions` vision endpoint (Gemini's
OpenAI-compat endpoint, GPT-4o, a local VL server). **Public API is unchanged**:
pass `vision=` and `ingest()` drives emit → fulfill → assemble internally (see
the scaling ladder above). The two gaps that used to make this **inert on real
docs are now closed**:
1. **Image bytes are persisted at ingest.** Extractors emit `doc.image_bytes`;
   `ingest/pipeline.py`'s `_persist_image_bytes()` stores each via
   `StorageBackend.put_bytes` and stamps `blob_key`, so the emit phase loads
   them back and vision fires on real PDF/DOCX/PPTX images (not just
   manually-injected test bytes).
2. **The §9 pre-filter is wired in.** The emit phase calls
   `vision/prefilter.py`'s `decide()` per image — the deterministic router
   (text / ocr / vision / skip, gated on area ratio + aspect ratio +
   OCR-density) — so decorative images are skipped and only figures that
   warrant it become requests.

**`citenexus verify`** — a standalone CLI for the faithfulness gate, useful
outside a running `CiteNexus` instance (e.g. a CI gate on someone else's RAG
output). `citenexus verify <input.json> [--format text|json]` calls the exact
`is_supported_v2` predicate `ask()` uses internally
(`python/src/citenexus/cli/verify.py:97`) — ordered, gap-bounded containment with
a polarity guard, per claim — deterministically, with no LLM call, no S3 and no
network. (A sibling `citenexus cite-check` adds retrieval-grounded checking.)
Install
via `pip install citenexus`, entry point `citenexus.cli:main`
(`pyproject.toml`). There's also a matching GitHub Action
(`.github/actions/`) that wraps it as a CI dogfood gate. Python-only for now —
no Go/JS/Rust CLI equivalent, though the JS port has an analogous library-level
gate (`js/src/gate/gate.ts`).

**LLM wiki (Karpathy-shaped, navigate-not-cite)** — pass `wiki_distiller=` and a
small model distils the corpus into a browsable wiki: summary pages plus concept
pages that span documents, each with `[[links]]`, keywords, and the EU ids it's
grounded in (`wiki/distill.py`), stored as a Markdown tree in S3 (`pages/*.md` +
`index.md` + an append-only `log.md`). Its genuine edge over other knowledge/code
wikis is the **navigate-not-cite invariant**: a page is never a citation target —
every hit resolves down to cited Evidence Units, and any `eu_ref` the model
invents is sanitized out, so distilled navigation can never become an ungrounded
claim. **Honest gap (it's a grounded *skeleton*, not yet a deep Karpathy wiki):** the
distiller is a single whole-corpus call (`_MAX_CORPUS_CHARS = 24_000`, each EU
truncated to 500 chars) — a shallow stand-in, not deep per-document/per-community
distillation. The incremental `integrate_document()` now runs the injected
distiller on each new document (degrading to a deterministic page only when no
distiller is configured), so the compounding path is no longer deterministic-only.

**Language detection** — real, not a stub. `lang/detect.py`'s
`FastTextDetector` lazily downloads Facebook's `lid.176.ftz` model on first use
and predicts via `fasttext.load_model` (needs the optional `fasttext` package
+ network for that one-time fetch); a `HeuristicDetector` (script-majority, no
network, no extra dep) is the offline/test default.

**Capability status (honest):**

| Capability | Status |
|---|---|
| text (BM25) · structure · graph · wiki · vector · RRF fusion | ✅ shipped, zero-model tier included |
| ask/stream/evaluate with per-claim faithfulness gate (ADR-0009) | ✅ shipped (generator required; `ask`/`stream`/`evaluate` raise without one — `retrieve()` does not) |
| Conflict surfacing — detected, surfaced, **never resolved** (ADR-0007) | ✅ shipped **Python only**; the ports declare `conflicts` and always emit empty |
| Authority floor over curator-asserted tiers (ADR-0004) | ✅ shipped, **unranked by default** — attach `authority=` at ingest and set a floor. Python only; ports carry the signals for wire parity, no selection logic |
| 14-script Unicode tokenizer + BM25 + gate predicate (ADR-0011) | ✅ shipped **at parity** in Python, Go and JS |
| `search_languages` cross-lingual fan-out (ADR-0013) | ✅ shipped, Python facade only; **`evaluate()` does not fan out** |
| `reconcile()` / `remediate()` — diff the index against a declared corpus manifest (ADR-0008) | ✅ shipped (orphans / missing / drifted; remediation is a separate explicit call) |
| `delete()` / revoke | ✅ shipped and **fixed in 0.10.0** — it used to report success while leaving the pre-re-ingest blob in storage. Blobs stranded by earlier re-ingests are unrecoverable |
| Structural code + schema intake (`rag.code`, `rag.schema`) | ✅ shipped, with **explicit per-edge confidence** rather than asserted edges |
| Deep-ask agentic loop (`strategy="deep"`) | ✅ shipped, budgeted, through the same gate |
| Atomic-claim decomposition + drop-not-fail | ⚠️ **Python only.** The ports ship `SplitClaims`/`splitClaims` but nothing calls it — a port answer passes or refuses **whole** |
| `bbox` on `Result.sources` | ❌ captured at extraction, **never carried onto the answer path** — `SourceRef.bbox` is always `None`. Cite to document + page |
| `acl` as tenant isolation | ❌ **carried, not enforced.** Isolation is `PartitionPath` + the `allowed_partitions` pre-filter |
| `citenexus verify` — standalone faithfulness-gate CLI + CI Action | ✅ shipped, Python only |
| Table extraction (structured `table` evidence blocks) | ✅ shipped for **CSV, PDF, DOCX, PPTX, HTML, XLSX** — ruled/aligned tables become citable `EUType.table` rows |
| Image-to-text via injected vision model (describe → citable figure EU) | ✅ shipped end-to-end — extractors persist image bytes at ingest and the §9 `decide()` pre-filter routes each image (skip / ocr / vision) |
| Real lid.176 language detection (`FastTextDetector`) | ✅ shipped (`detector=`), `HeuristicDetector` is the no-network default |
| LLM wiki distillation — grounded, navigate-not-cite (concept pages, `[[links]]`, S3 Markdown tree) | ⚠️ shipped but **shallow** (`wiki_distiller=`) — one 24k-char whole-corpus call; incremental `integrate_document()` now distils per new doc. Deep per-doc/per-community distill = not yet |
| Contextual chunking · dual-query RRF · hooks · telemetry · web crawl · Postgres backend | ✅ shipped |
| **LLM graph extraction** (entity/relation model behind the graph signal) | ⏳ not yet — graph is deterministic co-mention; the `GraphExtractorPlugin` seam exists, no LLM impl |
| Leiden community clustering | ⏳ not yet (community signal rides the graph retriever) |
| True BGE-M3 sparse lexical | ⏳ BM25-lite stands in (needs a sparse-capable endpoint) |
| Lists · code blocks · captions · document metadata as evidence | ✅ shipped — HTML/DOCX/MD `<li>` reach the store; fenced/indented code + HTML `<pre>` → `EUType.code_block`; HTML `<caption>`/`<figcaption>`; title/author/created (+ PDF page count) via `DocumentMetadata` |
| Footnotes as structured evidence | ❌ no extractor or evidence concept yet |
| LLM-as-judge · MCP server | ⏳ later (config sections reserved) |

Full block-by-block trace (captured → carried as a typed unit → actually
citable), including the gaps above: [`docs/CONTENT-COVERAGE.md`](docs/CONTENT-COVERAGE.md).

Or wire real OpenAI-compatible endpoints from typed config — one call builds the
embedding / answering-LLM / reranker plugins (answers stay temperature-0):

```python
from citenexus import CiteNexus, GeminiHttpEndpoint, OpenAIHttpEndpoint
from citenexus.config.schema import EmbeddingConfig, LLMConfig, StorageConfig, CiteNexusConfig

# Auth goes in headers as ${ENV_VAR} and expands at the HTTP boundary — the key
# value never enters a constructor, a repr, or a log. (`api_key=` still works and
# is the LEGACY path; see python/src/citenexus/http.py:103-118.)
jina   = OpenAIHttpEndpoint(base_url="https://api.jina.ai/v1",
                            headers={"Authorization": "Bearer ${JINA_API_KEY}"})
gemini = GeminiHttpEndpoint(headers={"Authorization": "Bearer ${GEMINI_API_KEY}"})

config = CiteNexusConfig(
    storage=StorageConfig(bucket="./data"),                  # or "s3://bucket"
    embedding=EmbeddingConfig(endpoint=jina, model="jina-embeddings-v3"),
    llm=LLMConfig(endpoint=gemini, model="gemini-2.5-flash"),
    # the SAME endpoint objects can serve context_model / reformulation /
    # wiki_distill / graph_distill — declare a connection once, reuse it.
)
rag = CiteNexus.from_config(config)
```

Endpoints carry everything connection-shaped: key, custom headers, timeout,
pre/post hooks, auth style (`AnthropicHttpEndpoint` → Messages API automatically;
`HttpEndpoint(auth_header="api-key", auth_scheme=None)` for Azure-style).

## Known limits — read these before you quote a number

We would rather say "don't know" than be wrong, and that applies to our own docs.

- **Subject-scope applicability is an OPEN GAP** ([ADR-0012](docs/adr/0012-subject-scope-applicability.md),
  *proposed*). Chunking severs a precondition from the operative rule it governs,
  so **8 of 11 operative EUs are citable without the clause that governs them**
  (73% severance). Such an answer is verbatim, correctly cited, passes the
  faithfulness gate **and** clears the authority floor — and still governs a
  different subject. Neither check catches it. This is the next failure class,
  and it is not solved.
- **The tuning constants are pinned, non-configurable, and English-fitted.** The
  gate's `(4, 8)` gap budget (`MAX_SINGLE_GAP`/`MAX_TOTAL_GAP`,
  `answer/verify.py:135-136`) and conflict's `MAX_RESIDUAL = 1`
  (`answer/conflict.py:84`) were swept on **synthetic, single-sentence, English**
  fixtures and have never been re-measured on a live non-English corpus.
- **Port parity is predicate-only.** Both ports ship `SplitClaims`/`splitClaims`
  but nothing on the answer path calls it, so atomic-claim decomposition and
  drop-not-fail are effectively Python-only — a Go or JS answer passes or refuses
  **whole**, never trimmed. Conflict detection, authority, reranking and the
  language fan-out are Python-only outright.
- **`evaluate()` does not fan out over `search_languages`**, so it always runs at
  the `("en",)` default — which is why the multilingual example's
  `library_evaluate` disagrees with its own harness. It also **cannot score
  abstention**: a blank `expected` earns credit only if the row was *answered*, so
  a correct refusal lowers the rate. Gate on refusals by driving `ask()` and
  asserting `Decision.refused`.
- **Every benchmark number above is a single live run.** Gemini is not
  deterministic at temperature 0 — an identical re-run moved the *rate* metrics by
  a question. Only the **safety** metrics reproduced: 0 out-of-jurisdiction
  citations, 100% groundedness/citation, 100% abstain-when-no-evidence. Treat the
  rates as directions, not rates you can plan against. The corpora are small and
  authored; these are demonstrations, not a benchmark suite.
- **`bbox` never reaches `Result.sources`**, and **`acl` enforces nothing** — see
  the capability table above.

## Status

Spec-driven via **OpenSpec**, built foundation-first. **0.10.1** is current.
L0–L5 are shipped and L6 partially: the public client exposes `ingest()`,
`retrieve()`, `ask()` (incl. `strategy="deep"`), `stream()`, `recall()`,
`delete()`, `reconcile()`/`remediate()`, `evaluate(csv)`, and the typed
`rag.code` / `rag.schema` intake, with graph and wiki navigation resolving back
to citable EUs. Still later work: Leiden communities, the MCP server, the online
judge, LLM graph extraction, and external-store authorization enforcement.

See [`CLAUDE.md`](CLAUDE.md) for the build plan and conventions,
[`docs/SPEC-v6.md`](docs/SPEC-v6.md) for the specification, and
[`docs/adr/`](docs/adr/) for why — ADRs 0004, 0007, 0008, 0009, 0011, 0012, 0013
and 0014 govern current behaviour.

## Develop

**Run `task` from `python/`** — both Taskfiles live there; there is no repo-root
Taskfile.

```bash
cd python
task setup            # uv sync
task check            # lint + typecheck + unit tests (the CI gate)
task test             # hermetic unit suite (fakes only)

task local:example    # end-to-end demo: ingest → ask → evaluate (hosted stack, no infra)
```

Unit tests are hermetic (fakes only) and need nothing running.

### The examples

Three runnable examples, all on a **cheap, hosted, no-infra** stack:

| Example | What it shows | Run it |
|---|---|---|
| [`python/example/`](python/example/) | the quickstart: ingest → ask → evaluate over a tiny multilingual corpus | `task local:example` (from `python/`) |
| [`examples/multilingual/`](examples/multilingual/) | a 12-document EN/TA/TE corpus — the `search_languages` fan-out (ADR-0013) and the answer-language rule | `uv run python run.py` |
| [`examples/law-authority/`](examples/law-authority/) | a California landlord–tenant corpus with `golden.csv` and committed `results.json` / `RESULTS.md` — the authority-floor benchmark (ADR-0004) | `uv run python run.py` |

The stack:

- **Storage** — LocalFs (a folder). Point `CITENEXUS_S3_ENDPOINT_URL` at MinIO
  or Cloudflare R2 to exercise the real S3 path.
- **Embedding + reranker** — [Jina](https://jina.ai) (`/v1/embeddings` + `/rerank`, one key).
- **Answering LLM** — Gemini's OpenAI-compatible endpoint (temperature 0).

Secrets live in a [vsync](https://muthuishere.github.io/vsync/) vault
(`infra/vault/dev/.env.dev`, encrypted on S3), referenced in code by env-var
*name* only. `task local:example` loads it via `dotenv`. Copy
[`python/example/.env.example`](python/example/.env.example) if you'd rather use
a plain file.

Heavier all-local paths stay opt-in: `task local:minio:up` (real S3 backend),
`task local:models:up` (infinity — bge-m3 embed + bge-reranker on one port), and
`task local:ollama:up` (a local answering LLM — bge-m3, qwen2.5,
`xitao/bge-reranker-v2-m3`). See [`python/compose.yaml`](python/compose.yaml).

## Community

Questions, ideas, or built something with this? Join **[AgentNexus](https://discord.gg/V9C2kvHC8D)** — a Discord
for people building with AI agents and open tools. This project lives in **#citenexus**.

## License

Apache-2.0
