# Content-coverage matrix — 2026-07-08

Traced by hand from the actual code path — extractor → evidence-builder →
retrieval → answer/citation — not from what the plugin protocols *allow*.
Three questions per content type, each with file+function proof:

- **Captured** — does an extractor produce a block/ref for it at all?
- **Carried** — does it reach the evidence store as its own typed thing
  (`EvidenceUnit.type`), not silently flattened into plain paragraph text?
- **Sent/cited** — can it actually end up as the cited passage in an `ask()`
  answer? `retrieve/types.py:Candidate` and `answer/flow.py:AnswerFlow.ask`
  carry **no per-type branching** — any unit that reaches the candidate pool
  is cited exactly like a paragraph. So "sent" here means "reaches the
  candidate pool at all"; for tables that's proven only at the mapping level
  (no end-to-end retrieve/answer test), and for images it depends entirely on
  ingest wiring that's currently broken (see row 5).

| # | Content type | Captured | Carried (typed EU) | Sent/cited | Proof |
|---|---|---|---|---|---|
| 1 | Prose paragraphs | ✅ | ✅ `EUType.paragraph` | ✅ | `extract/pdf.py:PdfExtractor.extract` (`page.extract_text()` → `BlockKind.paragraph`), `docx.py`/`html.py`/`md.py` body text → `evidence/builder.py:_KIND_TO_TYPE[BlockKind.paragraph] = EUType.paragraph` → `answer/flow.py:AnswerFlow.ask` cites via `SourceRef` |
| 2 | Headings | ✅ | ✅ `EUType.section` | partial | `docx.py:_heading_level` (Word `Heading N` styles), `html.py:extract` (`soup.find_all([*_HEADINGS, "p"])`), `md.py` heading tokens → own `BlockKind.heading` → `builder.py:_KIND_TO_TYPE[BlockKind.heading] = EUType.section` — a real, independently-citable EU, not just `structure_path` context on sibling blocks. No `answer`/`retrieve` test proves a heading EU is ever the *cited* claim, but nothing in `AnswerFlow.ask` blocks it. |
| 3 | Lists (bullet/numbered) | ❌ | ❌ | ❌ | `html.py:extract` selector is `[*_HEADINGS, "p"]` only — `<ul>/<ol>/<li>` never selected, text dropped entirely, not merged into any paragraph. `md.py`'s token loop only handles `heading_open`/`paragraph_open`; `bullet_list_open`/`list_item_open` fall into `else: i += 1` — silently skipped. `docx.py:_heading_level` only checks `Heading*` styles; a Word list paragraph is treated as a plain `BlockKind.paragraph` — the text survives but list/numbering structure is lost. |
| 4a | Tables — CSV | ✅ | ✅ `EUType.table` | ✅ | **2026-07-09: GREEN.** `extract/csv.py:CsvExtractor.extract` — header row → `StructureType.table_schema`, each data row → `BlockKind.table` (`"col: value"` pairs, `structure_path`=header) → `evidence/builder.py:_KIND_TO_TYPE[BlockKind.table] = EUType.table`, a real typed EU. `Candidate`/`AnswerFlow.ask` still carry no per-type branching (a table row is cited exactly like a paragraph — no special-casing, none needed), but that's now proven end-to-end: `tests/ingest/test_csv_table_citation_e2e.py` ingests a real CSV via the public `CiteNexus` client, asks a numeric question one row answers, and asserts the cited `SourceRef.passage` is the rendered table row (`"NoticeDays: 45"`), not paragraph prose. |
| 4b | Tables — PDF | ✅ | ✅ `EUType.table` | ✅ | **2026-07-09: GREEN.** `extract/pdf.py:PdfExtractor.extract` now calls `page.find_tables()` (pdfplumber's real ruled/aligned-text table detector, not text-alignment guessing) and `_extract_tables` renders each data row as `"col: value"` (same convention as `extract/csv.py`) → `BlockKind.table` → `EUType.table`. The table's region is also cropped OUT of the page's paragraph text (`_text_excluding_tables`, via `page.outside_bbox`) so a row's fact doesn't leak into — and tie retrieval score with — the paragraph EU. Proof: `tests/ingest/test_pdf_table_citation_e2e.py` — a real hand-built ruled-table PDF, ingested via the public `CiteNexus` client, a numeric question one row answers, cited passage is the table row (`SourceRef.page` set). |
| 4b′ | Tables — DOCX/PPTX/HTML | ❌ | ❌ | ❌ | Not yet started. `extract/docx.py:DocxExtractor.extract` iterates `document.paragraphs` only, never `document.tables`. `extract/pptx.py` never checks `shape.has_table`. `extract/html.py`'s tag selector omits `<table>`. A table in DOCX/PPTX becomes ordinary paragraph prose; in HTML it's dropped (outside the selector). |
| 5 | Images/figures via vision | ✅ (real docs) | ✅ `EUType.figure` | ✅ (real docs) | **2026-07-09: GREEN.** `ingest/pipeline.py:_persist_image_bytes` stores every extractor-supplied image and stamps `ImageRef.blob_key` (was already fixed 2026-07-08, commit `da6087c`). `ingest/pipeline.py:_vision_units` now also calls `vision/prefilter.py:decide()` when the extractor supplies a page area — `extract/pdf.py:PdfExtractor.extract` now stamps `ImageRef.width`/`height` from the image bbox and a new `ExtractedDoc.image_page_area` (keyed by `image_id`), so a real PDF image is routed `vision`/`skip` by real §9 geometry, not sent unconditionally. docx/pptx have no fixed page geometry to compute an area ratio from, so their images fall through to unconditional `vision` (prior, already-tested behavior — unchanged, not a regression). Proof: `tests/ingest/test_vision_prefilter_wiring.py` (meaningful figure → vision called once, cited; decoration-sized image → vision never called, no figure EU) and `tests/ingest/test_vision_real_pdf_e2e.py` (real embedded JPEG → described → cited, `FakeVision`). Live, real-model proof (not a fake): `docs/DEMO-live-vision-2026-07-08.md` — real Gemini `gemini-2.5-flash` vision call on a real chart PDF, grounded + cited answer, re-confirmed live 2026-07-09 after the pre-filter wiring landed. |
| 6 | Footnotes / captions | ❌ | ❌ | ❌ | `grep -rn "footnote\|caption" extract/*.py evidence/*.py` → zero matches. (`VisionRecord.short_caption` in `vision/describe.py` is the *model's own generated* caption for a figure, not extraction of a document's real caption/footnote text — unrelated concept.) |
| 7 | Code blocks | ❌ (schema exists, unreachable) | ❌ | ❌ | `extract/types.py:BlockKind.code` and `evidence/unit.py:EUType.code_block` are defined, and `evidence/builder.py:_KIND_TO_TYPE[BlockKind.code] = EUType.code_block` maps them — but no extractor ever constructs `BlockKind.code`. `md.py` drops fenced-code (`fence`) tokens in the same skip branch as lists; `html.py` never selects `<pre>/<code>`. Dead schema path. |
| 8 | Document metadata (title, author, created date, page count) | ❌ | ❌ | ❌ | `extract/types.py:ExtractedDoc` fields are only `document_id`, `source_type`, `structure_type`, `source_uri`, `blocks`, `images` — no metadata fields. No extractor reads DOCX `core_properties` or a PDF's metadata dict. `evidence/unit.py:EvidenceUnit` likewise carries no document-metadata fields; only `document_id` survives downstream (e.g. into `SourceRef.document`). |

## Top gaps, ranked

1. ~~**Vision never fires on a real document.**~~ **RESOLVED 2026-07-09** — see
   row 5. Image bytes are persisted (`_persist_image_bytes`) and the §9
   pre-filter is now called from `ingest/pipeline.py:_vision_units` for PDF
   (docx/pptx still fall through to unconditional vision, no page-geometry
   signal to route on). Companion spec: `docs/SPEC-vision-image-description-v1.md`.
2. **Tables now also work for PDF** (`2026-07-09`, row 4b), on top of CSV
   (row 4a). **DOCX/PPTX tables still silently flatten into paragraph
   prose; HTML tables are still dropped outright** — no error, no warning.
   Next up.
3. **Lists and code blocks are lost, not flattened**, in HTML/Markdown
   extraction — that content never reaches the evidence store in any form.
   (DOCX lists at least survive as plain-paragraph text, structure lost.)
4. **No type-awareness at citation time.** Even where a typed EU exists
   (table, figure, section), `AnswerFlow.ask`/`Candidate` don't know or care
   what type they're citing — no way to prefer a table for a numeric
   question, or to label a citation as table/figure-sourced in the output.
5. **No document metadata anywhere** — no title/author/date filtering is
   possible; only full-text/structure signals exist.

Companion spec for the top gap: [`docs/SPEC-vision-image-description-v1.md`](SPEC-vision-image-description-v1.md).
