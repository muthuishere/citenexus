# Spike — Library Landscape for the Go & TypeScript Ports

> Companion to [SPEC-PORTS-v1.md](SPEC-PORTS-v1.md). Every version below was
> verified against npm / crates.io / the Go module proxy on 2026-07-02.
> Verdict up front: **TS is fully served off the shelf; Go is fully served
> except Lance (Rust bridge, as decided) and pptx (parse OOXML directly).**

## 1. The Lance bridge (the one hard problem — decided)

| Language | Binding | Verified | Note |
|---|---|---|---|
| Python | `lancedb` (pyo3) | in use | reference |
| TypeScript | `@lancedb/lancedb` **0.30.0** | npm ✅ | official SDK (napi-rs over the same Rust core) |
| Go | **none exists** → build `trustrag-lance-ffi` | `lancedb` crate **0.30.0** on crates.io ✅ | thin C-ABI shim over the Rust crate, cgo-linked; exposes exactly `upsert/search/scan/drop` with JSON rows (SPEC §3.4). Same pattern lancedb itself uses for Node (napi-rs) and Python (pyo3) — we're adding the C lane. |

Rust crate and TS SDK are on the **same 0.30.x version line** — healthy,
synchronized releases; the shim pins one crate version per port release.
Both support S3/MinIO object stores natively (same `storage_options`).

## 2. Full library matrix

**Legend:** ✅ verified on registry · `std` = standard library / no dependency.

| Capability | Python (ref) | TypeScript | Go |
|---|---|---|---|
| Lance vector store | `lancedb` | `@lancedb/lancedb` 0.30.0 ✅ | `trustrag-lance-ffi` (ours, cgo) |
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
`ppt/slides/slideN.xml` inside a ZIP. TrustRAG only needs **block text +
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
**a pure-Go, no-cgo TrustRAG = Postgres backend + WASM pdfium.**

## 7. Risk register

| Risk | Level | Mitigation |
|---|---|---|
| `trustrag-lance-ffi` maintenance (C ABI, per-platform prebuilds) | **Medium — the main port cost** | shim exposes only 4 calls; JSON rows; pin crate version; prebuilt static libs per platform in releases (lancedb's own packaging pattern) |
| Go pptx gap | Low | OOXML-direct (§3) |
| Detection drift in Go | Low | plugin seam + fallback-chain fixtures (§5) |
| pdfjs bbox math differs from pdfplumber's | Low-Med | conformance compares block text + page, tolerant on bbox floats (1e-3) |
| officeparser flattens pptx structure | Low | prefer OOXML-direct in TS too |

## 8. Spike verdict

- **TypeScript: green.** Everything off the shelf, including the official
  Lance SDK and the *same* lid.176 model via WASM. No blockers.
- **Go: green with two build items** — the Rust FFI shim (decided, bounded to
  4 calls) and an OOXML-direct docx/pptx walker (~150 lines, shared design
  with TS). Everything else is mature: pgx+pgvector-go, goquery crawl,
  goldmark, go-pdfium (with a no-cgo escape hatch), lingua-go.
- **Both ports carry web crawl at T1-adjacent cost** — std HTTP + the HTML
  lib they already need for extraction; the crawler itself is ~100 lines of
  pure logic (BFS + caps) ported from `ingest/web.py`.
