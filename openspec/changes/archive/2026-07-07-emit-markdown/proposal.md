## Why

Every host language keeps reimplementing "give me this document as text an LLM
can read" — and the ecosystem's answer (Microsoft's markitdown) is a Python-only
dependency whose file-based converters largely duplicate extractors we already
ship, parity-tested, in `citenexus-core`. Our `ExtractedDoc` blocks already
carry heading levels, order, and kinds — everything a markdown renderer needs.
One small deterministic emitter turns the Rust core into a native
any-to-markdown engine for **all** bindings (Python, Go, TS) at once: useful
standalone (a fast markitdown alternative on npm/crates/PyPI) and internally
(markdown-shaped evidence for LLM prompts).

Deliberately out of scope: markitdown's network/model-dependent converters
(audio transcription, LLM image captions, YouTube/Wikipedia/Bing fetchers,
Azure doc-intel) — the core is the engine, not the brain, and ships no models.
Also deferred: docx/pptx table extraction (`w:tbl`/`a:tbl`), today's real
fidelity gap vs markitdown — its own follow-up change, since it improves RAG
extraction independently of markdown.

Confirmed target format set: **HTML, PDF, Word (docx), PowerPoint (pptx),
Excel (xlsx)** — plus txt/md/csv, which the core already extracts for free.
Everything except xlsx is already parity-tested; xlsx is the one new extractor
this change adds.

## What Changes

- Add an `xlsx` SourceType + extractor, csv-twin semantics per sheet: a
  heading block per sheet (its name), then one Table block per row rendered as
  `col: value` pairs against the sheet's first-row header (carried on
  `structure_path`), `page` = 1-based sheet index. Python reference via
  `openpyxl`; Rust twin via `calamine`; `.xlsx` extension mapped in both
  dispatchers.
- Add a pure, deterministic markdown emitter to the Python reference
  implementation (`extract/markdown.py`: `to_markdown(ExtractedDoc) -> str`)
  and its byte-identical Rust twin (`rust/src/emit/markdown.rs`), covering the
  full closed `BlockKind` set (heading/paragraph/table/code/image/slide/
  thread_turn/ocr_block).
- Add one C ABI function `citenexus_to_markdown(bytes, len, source_type)` →
  `{"markdown": ...}` JSON (or `{"error": ...}`), composing the existing
  extract dispatch with the emitter.
- Expose wrappers in the existing bindings: `golang/core.ToMarkdown`,
  `js/src/core.toMarkdown`, and a Python parity-test path through the real
  C ABI (Python callers use the native `to_markdown` directly).
- Extend the Rust↔Python parity suite: for every conformance fixture, the
  markdown produced by Python and by the Rust FFI is byte-identical.

## Capabilities

### New Capabilities

- `emit-markdown`: deterministic ExtractedDoc→markdown rendering plus the
  any-supported-format→markdown front door (`bytes + source_type → markdown`)
  exposed through the C ABI to every language binding.

## Impact

- New `python/src/citenexus/extract/markdown.py` + `extract/xlsx.py`,
  `rust/src/emit/` module + `extract/xlsx.rs`, one new FFI symbol in
  `rust/src/ffi.rs`; additive wrappers in `golang/core/core.go` and
  `js/src/core/core.ts`. Two new dependencies, one per side of the parity
  seam: `openpyxl` (Python) and `calamine` (Rust) — both pure readers, no
  models. `SourceType` gains `xlsx` (additive); existing extractors and
  `ExtractedDoc` fields are unchanged. PDF path inherits the existing `pdf`
  feature gate.
