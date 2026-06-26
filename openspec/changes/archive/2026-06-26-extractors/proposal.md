## Why

Ingest accepts any input type, but nothing yet turns those raw bytes into the
shared `ExtractedDoc` the rest of L3 consumes. The system needs one extractor per
source type — and a universal-intake dispatcher that routes any file extension,
explicit type, or raw content to the right one, falling back to plain text for the
unknown rather than failing. Best-effort structure (heading tree, slide sequence,
table schema, page layout) is captured where it exists and degrades to `none`
where it does not, never blocking extraction.

## What Changes

- Add **per-type extractors**, each an `ExtractorPlugin` subclass returning an
  `ExtractedDoc` of ordered `ExtractedBlock`s (+ `ImageRef`s):
  - `txt` — blank-line paragraphs, no structure.
  - `md` (markdown-it-py) — headings → heading blocks (level + ancestor
    `structure_path`); paragraphs → paragraph blocks under their heading path.
  - `csv` (stdlib `csv`) — header row → `table_schema`; each data row → a table
    block carrying the header as its `structure_path`.
  - `html` (bs4) — headings/paragraphs in document order; `<script>`/`<style>`
    stripped first.
  - `docx` (python-docx) — heading styles → `heading_tree`; body paragraphs;
    embedded images → `ImageRef`.
  - `pptx` (python-pptx) — one block per slide → `slide_sequence`; pictures →
    `ImageRef`.
  - `pdf` (pdfplumber) — text per page with page numbers + a word-derived bbox →
    `page_layout`; page images → `ImageRef`.
  - `plain` — raw `str`/`bytes` → a single paragraph; **also the unknown-type
    fallback**.
- Add **dispatch**: `extractor_for(source)` maps file extension / explicit
  `source_type` / raw content to an extractor (unknown extension, raw string, and
  raw bytes all → `PlainExtractor`); plus an `extract(source)` convenience.
- Every extractor sets `source_type` and a best-effort `structure_type` (`none`
  when there is no real structure) and derives `document_id` from the filename
  stem or a caller-supplied id.

## Capabilities

### New Capabilities
- `extractors`: universal intake — one extractor per source type plus a dispatcher
  with an unknown→plain fallback, each producing the shared `ExtractedDoc`
  (ordered blocks + image refs + best-effort structure).

### Modified Capabilities
<!-- none — extractors consume the existing extract.types vocabulary unchanged -->

## Impact

- New modules under `src/trustrag/extract/`: `txt.py`, `md.py`, `csv.py`,
  `html.py`, `plain.py`, `docx.py`, `pptx.py`, `pdf.py`, `dispatch.py`. The shared
  types in `extract/types.py` and the package `__init__.py` are unchanged.
- New tests under `tests/extract/` (incl. a hermetic `fixtures/sample.pdf`).
- Dependencies already installed: pdfplumber, python-docx, python-pptx, bs4,
  markdown-it-py, pillow. No new dependency or lockfile change.
- Downstream: the evidence-builder and structure-index consume `ExtractedDoc`;
  ingest will route through `dispatch.extract`.
