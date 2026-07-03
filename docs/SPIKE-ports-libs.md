# Spike — Library Landscape for the Go & TypeScript Ports

> Companion to [SPEC-PORTS-v1.md](SPEC-PORTS-v1.md). Every version below was
> verified against npm / crates.io / the Go module proxy on 2026-07-02.
> Verdict up front: **TS is fully served off the shelf; Go gets Lance,
> ALL parsing, and lid.176 detection from one shared Rust core
> (`citenexus-core`) — one bridge instead of five parser dependencies.**

## 0. The Rust core — verified crates

The decision (locked with Muthu): since Go links Rust for Lance anyway, the
bridge carries every parser Rust does best, and becomes the shared engine for
all bindings (cgo/Go now, napi/TS for parity later, pyo3/Python eventually).

| Core duty | Rust crate | Verified on crates.io |
|---|---|---|
| Lance store | `lancedb` | **0.30.0** ✅ (same version line as the TS SDK) |
| PDF text + word rects | `pdfium-render` | **0.9.2** ✅ (pdfium — same engine as go-pdfium) |
| DOCX/PPTX | `quick-xml` + std zip (OOXML-direct) | **0.41.0** ✅ (`docx-rs` 0.4.20 exists but is writer-focused) |
| HTML | `scraper` (html5ever, browser-grade) | **0.27.0** ✅ |
| Markdown | `pulldown-cmark` (CommonMark reference) | **0.13.4** ✅ |
| Language detect | `fasttext` — **pure-Rust fastText, loads the exact lid.176 model** | **0.8.0** ✅ (alt: `lingua` 1.8.0, `whatlang` 0.18.0) |
| XLSX (future) | `calamine` | **0.35.0** ✅ |

The pure-Rust `fasttext` crate is the spike's best find: it erases the Go
detection-drift risk entirely — same model file, same labels, byte-identical
with Python.

## 1. The Lance bridge (the one hard problem — decided)

| Language | Binding | Verified | Note |
|---|---|---|---|
| Python | `lancedb` (pyo3) | in use | reference |
| TypeScript | `@lancedb/lancedb` **0.30.0** | npm ✅ | official SDK (napi-rs over the same Rust core) |
| Go | **none exists** → build `citenexus-lance-ffi` | `lancedb` crate **0.30.0** on crates.io ✅ | thin C-ABI shim over the Rust crate, cgo-linked; exposes exactly `upsert/search/scan/drop` with JSON rows (SPEC §3.4). Same pattern lancedb itself uses for Node (napi-rs) and Python (pyo3) — we're adding the C lane. |

Rust crate and TS SDK are on the **same 0.30.x version line** — healthy,
synchronized releases; the shim pins one crate version per port release.
Both support S3/MinIO object stores natively (same `storage_options`).

## 2. Full library matrix

**Legend:** ✅ verified on registry · `std` = standard library / no dependency.

| Capability | Python (ref) | TypeScript | Go |
|---|---|---|---|
| Lance vector store | `lancedb` | `@lancedb/lancedb` 0.30.0 ✅ | `citenexus-lance-ffi` (ours, cgo) |
| Postgres vector | `psycopg` | `pg` 8.22.0 ✅ | `pgx/v5` v5.10.0 ✅ + `pgvector-go` v0.4.0 ✅ |
| S3 backend | `boto3` | `@aws-sdk/client-s3` | `aws-sdk-go-v2` v1.42.1 ✅ (or `minio-go`) |
| Config schema | `pydantic` | `zod` 4.4.3 ✅ | typed structs + `yaml.v3` v3.0.1 ✅ (strict decode) |
| HTTP model clients | `urllib` (std) | `fetch` (std) | `net/http` (std) |
| BM25 / RRF / chunker / gates | pure code | pure code | pure code |
| **HTML / web extract** | `bs4` | `cheerio` 1.2.0 ✅ | `goquery` v1.12.0 ✅ |
| **Web crawl** | ours (std fetch + bs4) | std `fetch` + cheerio | std `net/http` + goquery |
| Markdown | `markdown-it-py` | `markdown-it` | `goldmark` v1.8.2 ✅ |
| CSV / TXT | std | std | std |
| **PDF (text + word bboxes)** | `pdfplumber` | `pdfjs-dist` 6.1.200 ✅ (text items carry transforms → bboxes) | `go-pdfium` v1.19.4 ✅ — pdfium with **WebAssembly mode (no cgo!)** or cgo mode; gives char/word rects |
| **DOCX** | `python-docx` | `mammoth` 1.12.0 ✅ (or OOXML-direct) | `fumiama/go-docx` ✅ (MIT) or **OOXML-direct** |
| **PPTX** | `python-pptx` | `officeparser` 7.2.3 ✅ (docx/pptx/xlsx text) | **no good MIT reader → parse OOXML directly** (see §3) |
| Legacy **.doc / .ppt** | ❌ not supported | ❌ | ❌ (see §4) |
| Language detect | fastText `lid.176` | `fasttext.wasm.js` 1.0.0 ✅ (same lid.176 model!) or `tinyld` 1.3.4 ✅ | `lingua-go` v1.4.0 ✅ (pure Go, high accuracy) |
| OLE (if .doc ever) | — | — | `richardlehane/mscfb` v1.0.7 ✅ |
| Tests | `pytest` | `vitest` | std `testing` |

## 3. The pptx/docx insight: OOXML is just ZIP + XML

`python-docx`/`python-pptx` are conveniences over `word/document.xml` and
`ppt/slides/slideN.xml` inside a ZIP. CiteNexus only needs **block text +
structure + image refs** — not styling. A ~150-line OOXML walker using each
language's std `zip` + `xml` covers docx **and** pptx with zero dependencies
and identical block semantics across ports. **Recommendation: OOXML-direct in
Go (mandatory — no MIT pptx reader exists) and optional in TS** (officeparser
works but flattens structure; direct parsing keeps heading/slide blocks
matching the Python extractor's `BlockKind` output, which the conformance
fixtures check).

## 4. Legacy .doc / .ppt — honest status

**Python doesn't support these today either** (extractors: pdf/docx/pptx/html/
md/txt/csv/image + plain fallback). OLE binary parsing is a large, low-value
surface. Recommendation: keep out of scope for all three languages in
ports-v1; if demanded, add a **converter seam** (injected endpoint, e.g.
LibreOffice headless or a hosted converter → docx/pdf → existing extractors) —
consistent with the injected-model philosophy, no bundled binaries. Logged as
a spec decision, not a port gap.

## 5. Language detection nuance

fastText `lid.176` is the spec's detector. TS can run the **identical model**
(`fasttext.wasm.js` loads lid.176 → same labels/confidences). Go has no
maintained fastText binding — `lingua-go` is the recommended stand-in
(pure Go, excellent short-text accuracy). Consequence: Go's *detected*
languages may differ at the margin from Python/TS. Mitigation: the conformance
`language.json` cases test the **fallback chain** (pure logic, identical), and
detection itself is a plugin in every port — a team needing exact parity can
inject a lid.176 endpoint. Alternative if exactness matters later: add
`detect` to the Rust FFI shim (fasttext-rs) since Go already links Rust.

## 6. go-pdfium's WASM mode — de-risks Go builds

`go-pdfium` runs pdfium either via cgo **or via Wazero (pure-Go WASM
runtime — no cgo)**. Since the Lance shim already forces cgo, either mode
works; WASM mode keeps PDF support alive even in `CGO_ENABLED=0` builds where
Lance would be swapped for the Postgres backend. Nice degradation story:
**a pure-Go, no-cgo CiteNexus = Postgres backend + WASM pdfium.**

## 7. Risk register

| Risk | Level | Mitigation |
|---|---|---|
| `citenexus-core` maintenance (C ABI, per-platform prebuilds) | **Medium — the main port cost, now amortized over store+parse+detect** | JSON in/out; ~6 exported calls; pin crate versions; prebuilt static libs per platform (lancedb's own packaging pattern) |
| pdfium bbox math differs from pdfplumber's | Low-Med | conformance compares block text + page, tolerant on bbox floats (1e-3); long-term Python adopts the core too (pyo3) and the difference disappears |
| TS extraction drift until it adopts the napi core | Low | conformance fixtures are the arbiter; napi binding is the parity path |
| Rust `fasttext` crate model-load compat with lid.176 | Low | validated in the core's own CI against pinned fixtures |

## 8. Spike verdict

- **The Rust core is the strategy, not a workaround.** One crate
  (`citenexus-core`: lance store + pdf/docx/pptx/html/md extraction + lid.176
  detection) with three bindings — cgo (Go, required), napi-rs (TS, parity
  path), pyo3 (Python, later). One parser implementation, byte-identical
  `ExtractedDoc` everywhere, one place to fix parsing bugs.
- **TypeScript: green today** on native libs (official Lance SDK, pdfjs,
  cheerio, the same lid.176 via WASM); SHOULD migrate extraction to the napi
  core when published.
- **Go: green** — everything hard rides the core; the pure-Go remainder is
  mature (pgx + pgvector-go, goquery crawl, net/http, yaml.v3).
- **Web crawl in both** is ~100 lines of pure logic (BFS + caps) ported from
  `ingest/web.py` — std HTTP + the HTML capability they already have.
- Legacy .doc/.ppt stays out of scope everywhere (Python included) pending a
  converter seam (§4).
