# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Dist name on PyPI is **`citenexus`** (the import package is `citenexus`; see
`docs/adr/0003-pypi-dist-name.md`).

## [Unreleased]

## [0.10.0] - 2026-08-16

Evidence-integrity release. Three defects here produced output that *looked*
trustworthy — verbatim-sourced, correctly cited, and wrong. Each is now closed.

### Fixed

- **The faithfulness gate accepted answers that asserted the opposite of their
  source.** `is_supported` was set containment, and set containment is closed
  under reordering ("The landlord shall indemnify the tenant" is the same token
  set as its inverse) and under deletion (`not` is a token). Measured on
  adversarial fixtures across five domains: **9 of 9 false answers accepted,
  identically in Python, Go and JavaScript** — one specification defect three
  implementations reproduced faithfully. Verification now requires the claim's
  tokens in order within a bounded gap, and any polarity marker in the matched
  span to survive into the claim. **BREAKING (behavioral):** answers whose
  assertion does not follow from their citation are now rejected or trimmed. The
  predicate is strictly narrower, so nothing new is admitted. (ADR-0009)
- **`delete()` reported success while leaving the document's text in storage.**
  Re-ingest overwrote the single-valued `document_id → checksum` map without
  removing the prior blob, so revoke could only ever delete the *current* copy.
  The manifest now remembers retired checksums and revoke sweeps all of them.
  Blobs stranded by re-ingests predating this release are not recoverable — their
  checksums are gone from the manifest by construction. (ADR-0008)
- **Every non-Latin-script answer abstained**, including on a verbatim quote of
  its own source, because the pinned tokenizer was `[a-z0-9]+` over `.lower()`.
  The library advertised "multilingual"; the gate's multilingual coverage was
  German. (ADR-0011)
- **The published npm package threw on import.** Runtime modules read
  `conformance/*.json` from disk, but only `dist/` was shipped, so the path
  resolved to `node_modules/conformance`. Tables are now generated into the
  bundle.

### Added

- **Conflict surfacing.** `EvidenceSignals.conflicts_detected` and
  `Result.conflicts` were declared in the public contract and never written, so
  every Result asserted "zero conflicts" meaning "we never looked". Contradiction
  between grounded sources is now detected deterministically and **surfaced,
  never resolved** — in strict mode a conflict touching the answer's own claim
  abstains with both sides cited. Measured 0 false positives on 27 hard negatives
  and 10 held-out cases. (ADR-0007)
- **Near-duplicate collapse**, so `distinct_documents` stops counting mirrors of
  one sentence as independent corroboration. Claims surface clones only.
- **Per-claim verification with drop-not-fail.** A partly-supported answer
  returns its supported claims instead of being discarded whole;
  `Result.claims` and `unsupported_claims_removed` now carry real values.
- **`tokenize_v2`** — NFKC, full case folding, Unicode category scan, character
  bigrams for space-less scripts. **13 scripts claimed**, each backed by a golden
  fixture; Khmer, Lao, Myanmar, Georgian and Armenian are deliberately not
  claimed even though the bigram path works for them.
- **`EvidenceSignals.unsupported_scripts`** — a capability signal, distinct from
  "the evidence isn't there".
- **`reconcile()` / `remediate()`** — diff the live index against a
  caller-declared corpus manifest (orphans / missing / drifted, disjoint,
  read-only), with remediation as a separate explicit call. (ADR-0008)
- **Seven worked scenarios** in the docs, and a library-level adversarial stress
  harness (`spikes/library-stress/`) kept green by CI.

### Changed

- Go promotes `golang.org/x/text` from indirect to **direct** (`go.sum`
  unchanged) for full case folding. Pure Go — the ports gain no native
  dependency.
- `ProcessingManifest` is **deprecated**, not removed; it was never read or
  written and `worker.queue.DurableQueue` owns that status set. Removal in 0.7 of
  the successor line.
- Docs now state script support explicitly per port rather than claiming
  "multilingual".

### Known limitations

- The `(4, 8)` gap budget and the conflict detector's `max_residual = 1` are
  pinned in conformance vectors but were fitted against **synthetic,
  single-sentence, English** fixtures. They have not been re-measured on a live
  corpus with real models.
- The Go and JavaScript `Ask` flows still run the frozen v1 predicate; only the
  exported gate functions moved to v2.


## [0.6.0] - 2026-07-08

### Added
- **GFM pipe tables** in `to_markdown`: a run of contiguous `table` blocks
  sharing a header (`structure_path`) now fuses into one GitHub-flavored pipe
  table built from a new `ExtractedBlock.cells` field, with `|`/newline
  escaping and short-row padding. Per-row citation granularity is preserved —
  each row stays its own block/EvidenceUnit; fusion happens only at render.
  csv and xlsx extractors populate `cells`; a headerless `table` block still
  falls back to verbatim text.
- **HTML links and lists**: `<a href>` renders inline as `[text](href)` and
  `<ul>`/`<ol>` become `- ` / `1. ` line blocks from their direct `<li>`
  children (elements nested in a list are not double-emitted). Byte-identical
  across the Rust (`scraper`) and Python (`bs4`) twins.
- **Base64 data-URI images**: a new standalone-image extractor sniffs
  png/jpeg/gif/webp magic and inlines the bytes as
  `![image](data:image/<mime>;base64,…)`; above a 256 KiB cap, or for an
  unrecognized magic, it emits the `![image]()` placeholder. `SourceType.image`
  now routes here instead of falling back to plain text.

### Changed
- `ExtractedBlock` gains a `cells: list[str]` field (defaults to empty, like
  `structure_path`), reflected in the C ABI JSON and the JS/TS binding type.

## [0.5.0] - 2026-07-07

### Added
- **Any supported format → markdown** (`emit-markdown`): a deterministic
  `to_markdown(ExtractedDoc)` emitter — Python reference
  (`citenexus.extract.to_markdown`) and byte-identical Rust twin
  (`emit::markdown`, parity-tested) — plus one C ABI front door
  `citenexus_to_markdown(bytes, len, source_type)` exposed in every binding:
  Go `core.ToMarkdown`, TS `toMarkdown` (`@muthuishere/citenexus-core/ffi`).
  Covers html, pdf (feature-gated), docx, pptx, xlsx, md, csv, txt, plain.
- **xlsx extraction** (`SourceType.xlsx`): csv-twin semantics per sheet — a
  heading block per sheet name, `col: value` table blocks zipped against the
  sheet's first-row header, `page` = 1-based sheet index. Python via
  `openpyxl` (reference), Rust via `calamine` — byte-identical, plus a shared
  `conformance/fixtures/sample.xlsx`.

### Fixed
- The Python↔Rust extract parity suite was silently skipping since the repo
  restructure (it looked for the dylib under `python/core`); it now points at
  `rust/target` and runs again.

## [0.4.0] - 2026-07-04

### Added
- **Rust engine bound into the Go and TS ports via FFI** (opt-in): the shared
  `citenexus-core` C ABI is now callable from **Go (cgo, `citenexus_ffi` build
  tag)** and **TS (koffi)** — `extract`, `detect` (lid.176), and the LanceDB
  `store` — plus a minimal `ingest` orchestrator in each (extract → chunk → embed
  → store). The pure ports stay `go get` / `npm i`-clean; the native engine is
  strictly opt-in.
- **native-libs release workflow**: on a `v*` tag, cross-builds
  `citenexus_core` for darwin/linux/windows × amd64/arm64 and attaches the
  libraries to the GitHub Release for consumers to download.

## [0.3.0] - 2026-07-04

Unified version across all four languages (python/go/js/rust ship the same number).

### Added
- **Byte-identical semantic extraction in the Go and TS ports**: the deterministic
  **co-mention graph** (`build_comention_graph`) and **document structure index**
  (`build_structure`), proven against new shared conformance fixtures
  (`graph_comention.json`, `structure.json`). Python remains the arbiter.

### Changed
- `citenexus.graph.store.build_comention_graph` extracted as a pure function (the
  cross-language arbiter); `GraphStore.build_from_store` behavior is unchanged.

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
