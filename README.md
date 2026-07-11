# CiteNexus

> Multilingual RAG that answers only when the evidence is strong.

## Repository layout (polyglot)

One repo, one language per top-level folder, shared contract in the middle:

```
python/       reference library (full RAG) — PyPI `citenexus`
golang/       Go port (§4 core + hermetic ask + model clients) — `github.com/muthuishere/citenexus/golang`
js/           TypeScript port (§4 core + hermetic ask + model clients) — npm `@muthuishere/citenexus-core`
rust/         Rust core (extraction, store, lid.176) — crates.io `citenexus-core`
conformance/  shared cross-language fixtures — the real contract; a fixture edit breaks any drifting port
docs/  openspec/  .github/   design, specs, and CI shared across all languages
```

Each language folder is self-contained (its own build file + tests) but versioned
together (one version across all). Install the Go port with
`go get github.com/muthuishere/citenexus/golang` (monorepo submodule, tagged
`golang/vX.Y.Z`).

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


Evidence-first, multilingual, S3-native RAG for domains where a wrong answer is
worse than no answer (legal, medical, finance/compliance, enterprise search).
CiteNexus answers **only** from retrieved evidence — every claim is grounded in a
bbox-cited source passage, and it refuses or states uncertainty when evidence is
weak, missing, or conflicting. The guarantee is **"no ungrounded claim,"** not
"zero hallucination."

The library bundles **no models** — embedding, LLM, reranker, and vision are
injected endpoints. CiteNexus owns orchestration, storage, retrieval, fusion,
grounding, and evaluation.

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
rag.ingest("policy.pdf")                         # any supported input type
answer = rag.ask("Can the employee disclose this information?")
print(answer)                                    # grounded answer; .sources are bbox-cited
```

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
citable by page + bbox like any other unit.

**Image-to-text via a vision model** — the description → citable-EU half is
real and end-to-end: `vision/describe.py`'s `describe_image()` calls the
injected `VisionPlugin` and shapes its output into a `VisionRecord` (caption,
description, detected objects/relationships, any OCR text read out of the
image); `vision/units.py`'s `build_vision_units()` turns each
`(ImageRef, VisionRecord)` pair into a real `EvidenceUnit(type=figure)`, cited
by page + bbox exactly like any other unit. `vision/client.py`'s
`OpenAICompatibleVision` is the concrete client — base64-encodes image bytes
into an OpenAI-style `image_url` data URI and posts to any OpenAI-compatible
`/chat/completions` vision endpoint (Gemini's OpenAI-compat endpoint, GPT-4o,
a local VL server). Enable it by passing `vision=` to the client (see the
scaling ladder above). The two gaps that used to make this **inert on real
docs are now closed**:
1. **Image bytes are persisted at ingest.** Extractors emit `doc.image_bytes`;
   `ingest/pipeline.py`'s `_persist_image_bytes()` stores each via
   `StorageBackend.put_bytes` and stamps `blob_key`, so `_vision_units()` loads
   them back and vision fires on real PDF/DOCX/PPTX images (not just
   manually-injected test bytes).
2. **The §9 pre-filter is wired in.** `_vision_units()` calls
   `vision/prefilter.py`'s `decide()` per image — the deterministic router
   (text / ocr / vision / skip, gated on area ratio + aspect ratio +
   OCR-density) — so decorative images are skipped and only figures that
   warrant it reach a model call.

**`citenexus verify`** — a standalone CLI for the faithfulness gate, useful
outside a running `CiteNexus` instance (e.g. a CI gate on someone else's RAG
output). `citenexus verify <input.json> [--format text|json]` calls the exact
`is_supported`/`has_relevance_overlap` functions `ask()` uses internally
(`python/src/citenexus/cli/verify.py`), proving `tokens(claim) ⊆
tokens(passage)` deterministically — no LLM call, no S3, no network. Install
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
every hit resolves down to bbox-cited Evidence Units, and any `eu_ref` the model
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
| ask/stream/evaluate with per-claim faithfulness gate | ✅ shipped (generator required) |
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
import os
from citenexus import CiteNexus, GeminiHttpEndpoint, OpenAIHttpEndpoint
from citenexus.config.schema import EmbeddingConfig, LLMConfig, StorageConfig, CiteNexusConfig

# YOUR app reads its environment — the library never touches env vars.
jina   = OpenAIHttpEndpoint(base_url="https://api.jina.ai/v1",
                            api_key=os.environ["JINA_API_KEY"])
gemini = GeminiHttpEndpoint(api_key=os.environ["GEMINI_API_KEY"])   # SecretStr — repr/log-safe

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

## Status

Early development, built layer-by-layer (foundation-first) and spec-driven via
**OpenSpec**. L0-L6 core retrieval/answering is implemented: the public client
exposes `ingest()`, `retrieve()`, `ask()`, `stream()`, memory recall, and
`evaluate(csv)`, with graph and wiki navigation resolving back to citable EUs.
MCP and external auth enforcement are still later work. See [`CLAUDE.md`](CLAUDE.md)
for the build plan and conventions, and [`docs/SPEC-v6.md`](docs/SPEC-v6.md) for
the full specification.

**Validated live** (real Jina + Gemini, not fakes): on a small multilingual
legal/HR corpus, CiteNexus answered Dutch questions in Dutch (answer-language
invariant), produced grounded verbatim citations, attributed public-law vs
internal-policy sources correctly, and abstained on an out-of-corpus question —
100% groundedness + citation on the golden set. Reproduce with `task local:example`.

## Develop

```bash
task setup            # uv sync
task check            # lint + typecheck + unit tests (the CI gate)
task test             # hermetic unit suite (fakes only)

task local:example    # end-to-end demo: ingest → ask → evaluate (hosted stack, no infra)
```

Unit tests are hermetic (fakes only) and need nothing running.

### The example ([`example/`](example/))

`task local:example` runs ingest → ask → evaluate over a tiny multilingual
corpus using a **cheap, hosted, no-infra** stack:

- **Storage** — LocalFs (a folder). Point `CITENEXUS_S3_ENDPOINT_URL` at MinIO
  or Cloudflare R2 to exercise the real S3 path.
- **Embedding + reranker** — [Jina](https://jina.ai) (`/v1/embeddings` + `/rerank`, one key).
- **Answering LLM** — Gemini's OpenAI-compatible endpoint (temperature 0).

Secrets live in a [vsync](https://muthuishere.github.io/vsync/) vault
(`infra/vault/dev/.env.dev`, encrypted on S3), referenced in code by env-var
*name* only. `task local:example` loads it via `dotenv`. Copy
[`example/.env.example`](example/.env.example) if you'd rather use a plain file.

Heavier all-local paths stay opt-in: `task local:minio:up` (real S3 backend),
`task local:models:up` (infinity — bge-m3 embed + bge-reranker on one port), and
`task local:ollama:up` (a local answering LLM). See [`compose.yaml`](compose.yaml).

## License

Apache-2.0
