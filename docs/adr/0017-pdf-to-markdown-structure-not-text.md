# 0017 — PDF→markdown in the Rust core: models propose structure, the PDF supplies the text

Status: accepted · 2026-09-24 (consumer-approved with additions 8–11) · research: [`docs/research/2026-09-24-pdf-to-markdown.md`](../research/2026-09-24-pdf-to-markdown.md) (`f3d9458`)

## Context

`rust/src/extract/pdf.rs` emits one paragraph per page from `page.text().all()`. It
has no headings, no tables, no hyphen joining and no header/footer handling, and
pdfium's U+0002 soft-hyphen marker survives into the text. A consumer (rag_go,
Lex5 corpus) measured these gaps. Their spike 185 then showed that routing each
page, and using an injected text LLM or vision model gated by deterministic
checks, recovers tables: 127/149 cells and 32/36 rows, against 91 and 21 for flat
text.

The research found two facts that change the design:

1. **The spike's gate checks vocabulary, not placement.** At its strictest
   thresholds it accepts amounts swapped between rows, `7.000,00` → `70.000,0`,
   `5.100,00` → `100`, and a "geen" moved to another sentence (research §0, §5
   W1). Every one of those is a confidently-wrong table, which is the error
   class this library exists to prevent.
2. **The spike's score rests on AGPL and GPL code.** It uses PyMuPDF (spike
   `build_final.py:183`, `build_corpus.py:32`) and poppler `pdftotext -layout`
   (`build_final.py:79`). Neither may enter the Apache-2.0 core (ADR-0005), so
   the score has to be re-earned on pdfium.

The leading text-layer systems avoid (1) by construction: the model decides
*structure*, and the cell text is the PDF's own characters (research §8 #1).

## Decision

**One implementation, in the Rust core.** Python, JS and Go all call it through
the existing C ABI. Go uses `golang/core` behind `citenexus_ffi`, the same place
as `Extract` and `ToMarkdown` (`golang/core/core.go:78,96`). This is tier-3 work
under ADR-0010: real parsing over pdfium character boxes.

1. **Base extraction, deterministic, no model.** From pdfium character boxes
   (x/y, font size and weight):
   - **Layout text layer** per page, the equivalent of `pdftotext -layout`.
   - **Hyphen joining** at the U+0002 marker. Join only when the document
     itself shows the joined form elsewhere. Without that evidence, a
     per-language keep-list decides. Coordinated compounds ("in- en verkoop")
     and real compounds ("e-mail", "long-term") are never merged.
   - **Headings**, in this order of sources: the tagged-PDF structure tree
     (`FPDF_StructTree_*`), then the outline, then numbering, then font
     clustering. A heading is emitted only when the available sources agree.
   - **Reading order:** the structure tree when the PDF is tagged. Otherwise a
     rule-based ordering, with XY-Cut++ as the fallback.
   - **Running headers and footers:** a line in a top or bottom band, repeated
     across pages. Each such line is kept **once** per document as tagged
     furniture, not deleted, so "laatst bijgewerkt <date>" stays citable.
   - **Per-page output** with bboxes.
2. **Per-page routing with its signals exposed.** Every page is classified as
   plain, formatted, table, image region, or scan with no text layer. The
   classification returns the evidence behind it: ruling lines, column tracks,
   text-layer soundness, image coverage.
3. **Deterministic tables first.** For a ruled grid (lines and rects) or
   inferred column tracks, a scored grid search runs, with fake-table
   validators. The tagged structure tree, when present, wins outright. A model
   is asked only when the grid score is low.
4. **Model hooks: STRUCTURE, not text.** The core never makes a network call.
   It uses the ADR-0005 two-phase pattern:
   - `prepare(pdf, opts)` returns the pages, routes and signals, plus **requests**.
   - The host fulfils the requests with its own injected text LLM or vision
     model. The prompts are host **config**; a default `prompts.json` ships as
     data, not code.
   - `assemble(pdf, responses)` returns the markdown plus provenance.
     `assemble` re-parses the PDF, so the core keeps no state between calls.
   - On a page **with a text layer**, the model returns a grid, or region
     boundaries, over the text-layer **word IDs** the request lists. Rust fills
     every cell from those pdfium characters. Model-written text is never used
     on such a page.
   - On a page or region **with no text layer**, vision-written markdown is
     used and flagged `vision_transcribed`, and only under **dual
     transcription** (amended 2026-09-25, consumer requirement):
     - every `vision_page` / `vision_region` request is issued **twice**,
       with distinct ids (`…:v1`, `…:v2`), a `variant` field (1/2) and a
       `hint` telling the host to use a different model or sampling seed.
       Prompts stay host config.
     - Each transcription still passes the step-5 guards and checks on its
       own (digit bag, values, coverage/novelty against any OCR layer); a
       variant that fails is dropped.
     - Assemble aligns the two by sentence after normalisation (NFKC,
       case-fold, whitespace, and every number replaced by its ADR-0015
       reading). Only sentences **identical in both** become content.
     - A sentence that differs or appears in one only stays in the unit,
       inside a `<!-- vision_disputed\nv1: …\nv2: …\n-->` block, and the unit
       carries `provenance.vision_disputed = true`. Disputed text is **not
       citable**: hosts cite `citable_text(markdown)` (Rust
       `vision::citable_text`, Go `core.CitableText`), which strips those
       blocks.
     - One response back (the other missing, timed out or failed its
       checks): the whole unit is one disputed block, single-source, never
       silently trusted. No response: base output.
     - This closes the "moved word" gap that no bag of words can see: a
       "geen" moved between sentences, or two amounts swapped between
       lines, makes both sentences disputed.
   - Live-harness amendments (2026-09-25, consumer):
     - a `vision_region` response states its `mode`. A `description` of a
       region with no meaningful text (a logo) becomes an
       `image_description` unit. It is never citable and never put through
       dual agreement, because it is not evidence.
     - `{"tables": []}` is the model's verdict "no table" (recorded as
       `model_verdict`), not a failure.
     - List-marker glyphs and leaders are filler a grid may leave out.
     - Request regions grow to whole units, and tables of contents are
       never requested.
     - The full host contract is [`docs/pdf-model-contract.md`](../pdf-model-contract.md).
5. **Deterministic checks before anything replaces base text.** All of these
   are library functions:
   - **Geometry:** every cell's characters sit in one row band and one column
     band.
   - **Digit bag and value parse:** locale-aware under ADR-0015, ignoring
     model-added list markers, but catching "I.3" → "1.3".
   - **Coverage and novelty.** For vision-only content, the thresholds
     0.90/0.08 carry over from the spike, and furniture is exempt.
   - **Choosing between grids:** GriTS plus the position check replaces "more
     rows wins".
   - **Model-output guards:** finish reason, repetition and length.
   - **Fallback:** any failure falls back to the base text.
6. **Provenance on every unit:** `route`, `table_source`
   (struct_tree | ruled | tracks | model_grid), `vision_transcribed`,
   `table_uncertain`, and which check failed when a fallback happened.
7. **What we borrow, and what we don't.** We borrow parts, not tools, and we
   take **no dependency** on Xberg. Code is ported from permissive sources at
   pinned commits, with attribution in `rust/NOTICE`: LiteParse router and
   repetition, Marker `table_recon`, Xberg `table_core` and hyphen witnesses,
   Docling reading order and text quality, GriTS, olmOCR guards. Nothing
   AGPL, GPL or non-commercial anywhere in the stack.

8. **DOCX and PPTX use the same output, from their own structure, with no
   model.** OOXML already carries real structure: `w:tbl` (including merged
   cells via `gridSpan`/`vMerge`), heading styles, list numbering, and PPTX
   `a:tbl` and title placeholders. The extractor emits markdown tables and
   headings from that deterministically, with the same unit, bbox-where-known
   and provenance shape (`route` = `ooxml`).
9. **An image region on a text-layer page** (for example a screenshot of a
   form inside a policy page) is its own unit, `vision_transcribed`. It is
   never merged into text-layer content and never overrides it. Where a vision
   region overlaps text-layer characters, **the text layer wins** and those
   characters are removed from the vision unit's claim to coverage.
10. **Go binding shape.** rag_go uses exactly this surface:

    ```go
    // Base only: no model, never fails for lack of a provider.
    units, err := core.PdfUnits(pdf, core.PdfOptions{Language: "nl"})
    // each unit: Page, BBox, Kind (heading|paragraph|table|list|furniture|image),
    // Markdown, Route, Provenance{TableSource, VisionTranscribed, TableUncertain, FailedCheck}

    // With models: two-phase, the host owns transport and keys.
    prep, err := core.PdfPrepare(pdf, opts)      // routes, signals, prep.Requests
    responses := fulfil(prep.Requests)           // the host's own text-LLM / vision calls
    units, err = core.PdfAssemble(pdf, opts, responses)
    // a missing or failed response == base output for that page, with FailedCheck set
    ```

    `PdfUnits` is exactly `PdfAssemble` with no responses. So ingestion
    degrades gracefully to the base output when the model provider is down,
    and the same functions exist in Python and JS.
11. **Determinism.** The same PDF, options and responses give **byte-identical**
    output: no hash-map iteration order, no clock, no randomness, and
    floating-point geometry rounded before any comparison is serialized. A
    conformance test runs `assemble` twice, and across the ports, and compares
    bytes. This matters for audits with legal clients.

## Runtime (Linux amd64, Scaleway container)

- `pdfium-render` keeps binding **libpdfium dynamically** (`rust/Cargo.toml`,
  feature `pdf`).
- Ship a **pinned** `libpdfium.so` from bblanchon/pdfium-binaries
  (`pdfium-linux-x64.tgz`, glibc, about 3.7 MB; pdfium itself is BSD-3), next to
  the `citenexus-core` cdylib. Point `PDFIUM_DYNAMIC_LIB_PATH` at it, or put it
  on the loader path.
- No GPU, no ONNX Runtime and no model weights in the core. An optional small
  table model (TATR or SLANet_plus via `ort`) is deferred until measurement
  shows grid search misses too often. Even then it can stay host-side.
- A Dockerfile snippet and a smoke test that loads the `.so` ship with step 1.
  The exact binary size and glibc floor get re-checked when the binary is
  pinned.

## Verification and acceptance

- **The host-facing contract** (request/response shapes, ids, variants,
  disputed markup, failure semantics, a worked example) is
  [`docs/pdf-model-contract.md`](../pdf-model-contract.md) with a JSON Schema
  in `docs/schema/`.
- **Conformance vectors from synthetic PDFs only.** They are the spike's 11
  check tests, olmOCR-bench-style present / absent / order / cell-neighbour
  tests, and a **must-reject** adversarial set: swapped row amounts, a dropped
  digit, `7.000,00` → `70.000,0`, a moved "geen". The dehyphenation vectors
  include "e-mail", "long-term" and "in- en verkoop". OOXML vectors: a DOCX
  table with merged cells, a DOCX heading hierarchy, and a PPTX table. A
  determinism vector: the same input twice gives byte-identical output.
- **Lex5, 82 originals, read in place and never copied:**
  - cells ≥127/149 and rows ≥32/36;
  - quote support ≥282/468;
  - **positional integrity: 100% of emitted table-cell values traceable to
    their pdfium character boxes.**
  - The table sample is 7 tables and 149 cells, so a ±1-cell difference is
    noise. Report the count and the table-level result, not a rate.
- All Go, Python and JS suites stay green. Nothing merges or tags before the
  owner's port condition is met.

## Build order

1. Probe what share of Lex5 is tagged (an evening).
2. Hyphen join, text-layer soundness, router, header/footer, reading order and
   headings. None of these needs a model.
3. The geometry gate and the structure-not-text request/response contract,
   with the adversarial vectors.
4. Deterministic tables.
5. Model hooks across Python, JS and Go.
6. The optional table model, only if measured necessary.

## Consequences

- The model can no longer invent a value on a text-layer page. Its worst case
  is a wrong **structure**, and the geometry gate and GriTS catch or downgrade
  that. The price is a request schema more complex than "page → markdown".
- Scans and image regions remain as trustworthy as the AGREEMENT of two
  independent vision transcriptions. They are **labelled**
  `vision_transcribed`, never passed off as backed by the text layer, and any
  sentence the two do not agree on is `vision_disputed` and not citable. The
  price is two vision calls per region instead of one.
- The spike's numbers are a target, not a baseline: they have to be re-earned
  without PyMuPDF or poppler.
