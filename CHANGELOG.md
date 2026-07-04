# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Dist name on PyPI is **`citenexus`** (the import package is `citenexus`; see
`docs/adr/0003-pypi-dist-name.md`).

## [Unreleased]

## [0.2.1] - 2026-07-03

### Changed
- Repository restructured to a polyglot layout: one language per top-level folder
  (`python/`, `golang/`, `js/`, `rust/`) with shared `conformance/`, `docs/`,
  `openspec/`, and `.github/`. No change to the published `citenexus` package's
  behavior or public API — this release is functionally identical to 0.2.0.

## [0.2.0] - 2026-07-02

First public release. Evidence-first, multilingual, S3-native RAG: answers only
from retrieved evidence, cites verbatim, and abstains when evidence is weak,
missing, or conflicting.

### Added

- **Public client, three verbs** — `CiteNexus("s3://bucket", signals=[...])` with
  `ingest()` / `ingest_async()`, `ask()` (strict cite-or-abstain default),
  `retrieve()` (documents-only engine under `ask`), `stream()` (sentence-gated in
  strict mode), memory `recall()`, and `evaluate(csv)` with deterministic
  aggregate metrics and an append-only audit trail.
- **Grounded answer flow** — temperature-0 generation over retrieved evidence,
  per-claim token faithfulness gate, cite-or-abstain, conflict surfacing,
  answer-language invariant (regenerate on mismatch), verbatim citations.
- **Multi-provider answering LLM** — OpenAI-compatible, Google Gemini, and
  Anthropic clients behind one injected seam; `from_config` factory; no bundled
  models anywhere (embedding / LLM / reranker / vision are injected endpoints).
- **Universal ingest** — files, S3 prefixes, raw text, plus **web fetch and
  same-domain crawl**; sync + async via a durable worker queue
  (retry/backoff, DLQ, idempotent-by-hash, resume). Extractors for
  pdf/docx/pptx/html/md/txt/csv/images with unknown-type plain fallback.
- **Chunking + contextual retrieval** — recursive structure-aware chunker with
  parent-child evidence building and LLM-contextualized chunks (Anthropic-style
  contextual retrieval).
- **Conditional vision-into-evidence** — vision pre-filter + 3-way decision;
  `OpenAICompatibleVision` describes figures into first-class evidence units.
- **Retrieval engine** — vector + BM25 lexical + structure retrievers fused with
  RRF (k=60), **English dual-query RRF** with a shared query-reformulation
  cache, and a reranker seam; navigate-not-cite invariant (graph/wiki resolve
  down to evidence units before answering).
- **Storage seams** — `VectorStore` / `TextSearch` protocols with backend-paired
  implementations: **LanceDB + BM25** (zero-infra default) and
  **Postgres/pgvector + full-text** (`pip install "citenexus[postgres]"`).
  S3-native layout with manifests, partition resolution, artifact provenance
  stamps, and a partial-rebuild planner.
- **Trust & access** — variable-depth partitions, scope → `allowed_partitions`
  hard pre-filter (`acl` carried, not enforced), trust modes, warn-only config
  validation (`citenexus.validate.yaml`).
- **Graph, wiki, memory, streaming** — deterministic rebuildable graph/wiki
  artifacts with retrievers; partition-scoped conversation memory (context, not
  citation evidence); token/sentence streaming from verified results.
- **Lifecycle hooks + telemetry** — toolnexus-style hooks around
  ingest/retrieve/answer, one telemetry event stream with cost and counter
  views, LLM token-usage surfacing, fused-retrieval events.
- **Multilingual** — fastText lid.176 language detection (fetched on first use,
  not a pip dep), detection threshold + answer-language fallback chain.
- **`citenexus-core` (Rust) scaffold** — native extraction engine with
  parity-proven output against the Python reference extractors, groundwork for
  the Go/TypeScript ports (`docs/SPEC-PORTS-v1.md`); optional, Python remains
  the reference implementation.
- **Tooling** — uv + hatchling, Taskfile-first rituals, ruff + mypy --strict,
  hermetic unit suite on deterministic fakes, SHA-pinned GitHub Actions CI, and
  a tag-triggered release workflow publishing to PyPI via OIDC trusted
  publishing. Runnable multilingual example against local MinIO + Ollama.

[Unreleased]: https://github.com/muthuishere/citenexus/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/muthuishere/citenexus/releases/tag/v0.2.0
