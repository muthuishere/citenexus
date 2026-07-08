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
| 4a | Tables — CSV | ✅ | ✅ `EUType.table` | partial | `extract/csv.py:CsvExtractor.extract` — header row → `StructureType.table_schema`, each data row → `BlockKind.table` (`"col: value"` pairs, `structure_path`=header) → `evidence/builder.py:_KIND_TO_TYPE[BlockKind.table] = EUType.table`, a real typed EU. But `Candidate` (`retrieve/types.py`) carries no `type` field and `AnswerFlow.ask` (`answer/flow.py:60-131`) builds `SourceRef`/`Claim`/`ProvenanceEntry` with zero branch on EU type — a table row would be cited exactly like a paragraph. Only `tests/evidence/test_builder.py` proves the block→type mapping; no `retrieve`/`answer` test cites a table EU end-to-end. |
| 4b | Tables — PDF/DOCX/PPTX/HTML | ❌ | ❌ | ❌ | `extract/pdf.py:PdfExtractor.extract` calls `page.extract_text()`, never `page.extract_tables()`. `extract/docx.py:DocxExtractor.extract` iterates `document.paragraphs` only, never `document.tables`. `extract/pptx.py` never checks `shape.has_table`. `extract/html.py`'s tag selector omits `<table>`. A table in PDF/DOCX/PPTX becomes ordinary paragraph prose; in HTML it's dropped (outside the selector). |
| 5 | Images/figures via vision | partial | ✅ (logic sound) | ❌ (real docs) | Description→EU shaping is real: `vision/units.py:build_vision_units` turns `(ImageRef, VisionRecord)` into `EvidenceUnit(type=EUType.figure)`, cited by page+bbox. But `extract/pdf.py`/`docx.py`/`pptx.py` always leave `ImageRef.blob_key=None` (`extract/types.py:ImageRef` default); `ingest/pipeline.py:_image_bytes` (`if not blob_key: return None`) then makes `_vision_units` skip every real image before `describe_image` is ever called (`ingest/pipeline.py:251-255: data = self._image_bytes(image); if data is None: continue`). Additionally `vision/prefilter.py:decide()` — the §9 text/ocr/vision/skip router — is defined and tested but **never called from `ingest/pipeline.py`** (confirmed: only import site is `vision/__init__.py`'s re-export). Only proven with manually-injected bytes in tests (`FakeVision`). |
| 6 | Footnotes / captions | ❌ | ❌ | ❌ | `grep -rn "footnote\|caption" extract/*.py evidence/*.py` → zero matches. (`VisionRecord.short_caption` in `vision/describe.py` is the *model's own generated* caption for a figure, not extraction of a document's real caption/footnote text — unrelated concept.) |
| 7 | Code blocks | ❌ (schema exists, unreachable) | ❌ | ❌ | `extract/types.py:BlockKind.code` and `evidence/unit.py:EUType.code_block` are defined, and `evidence/builder.py:_KIND_TO_TYPE[BlockKind.code] = EUType.code_block` maps them — but no extractor ever constructs `BlockKind.code`. `md.py` drops fenced-code (`fence`) tokens in the same skip branch as lists; `html.py` never selects `<pre>/<code>`. Dead schema path. |
| 8 | Document metadata (title, author, created date, page count) | ❌ | ❌ | ❌ | `extract/types.py:ExtractedDoc` fields are only `document_id`, `source_type`, `structure_type`, `source_uri`, `blocks`, `images` — no metadata fields. No extractor reads DOCX `core_properties` or a PDF's metadata dict. `evidence/unit.py:EvidenceUnit` likewise carries no document-metadata fields; only `document_id` survives downstream (e.g. into `SourceRef.document`). |

## Top gaps, ranked

1. **Vision never fires on a real document.** Two independent, stacked
   failures: (a) no extractor persists image bytes (`ImageRef.blob_key`
   always `None`), and (b) the §9 pre-filter that would gate/cheapen vision
   calls is never invoked by the ingest pipeline. `vision=` only proves
   itself in tests with injected bytes — on `rag.ingest("file.pdf")` today it
   is completely inert. **This is the subject of the companion spec**,
   `docs/SPEC-vision-image-description-v1.md`.
2. **Tables work for CSV only.** PDF/DOCX/PPTX tables silently flatten into
   paragraph prose; HTML tables are dropped outright — no error, no warning.
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
