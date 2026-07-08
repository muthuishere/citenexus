# Content-coverage matrix

Traced by hand from the actual code path — extractor → evidence-builder →
retrieval/answer/citation — not from what the plugin protocols *allow*. Three
questions per content type:

- **Captured** — does an extractor produce a block/ref for it at all?
- **Carried** — does it reach the evidence store as its own typed thing
  (`EvidenceUnit.type`), not silently flattened into plain paragraph text?
- **Cited** — can it actually end up as the cited passage in an `ask()`
  answer? (`answer/flow.py:AnswerFlow.ask` and `retrieve/types.py:Candidate`
  carry no per-type branching — if a unit reaches the candidate pool, it can
  be cited exactly like a paragraph. So "cited" here means "reaches the
  candidate pool at all", which for images depends on the ingest wiring, not
  on the answer flow.)

| # | Content type | Captured | Carried (typed EU) | Cited | Evidence |
|---|---|---|---|---|---|
| 1 | Prose paragraphs | ✅ | ✅ (`EUType.paragraph`) | ✅ | All extractors' body text → `evidence/builder.py:_KIND_TO_TYPE[BlockKind.paragraph]` → `AnswerFlow.ask` |
| 2 | Headings | ✅ | ✅ (`EUType.section`) | partial | `docx.py`/`html.py`/`md.py` detect heading styles/tags → own `BlockKind.heading` → own EU, not just `structure_path` context on other blocks. No test exercises a heading EU as the *cited* claim, but nothing blocks it. |
| 3 | Lists (bullet/numbered) | ❌ | ❌ | ❌ | `html.py:extract` only selects `h1-h6, p` — `<ul>/<ol>/<li>` never selected, text dropped entirely. `md.py` skips `bullet_list_open`/`list_item_open` tokens (`else: i += 1`). `docx.py` only checks `Heading*` styles — a Word list paragraph is treated as a plain paragraph (its bullet is lost, not preserved, but the text does survive as prose). |
| 4a | Tables — CSV | ✅ | ✅ (`EUType.table`) | partial | `extract/csv.py:CsvExtractor` → `BlockKind.table` → `evidence/builder.py` maps to `EUType.table`, a real EU. But `Candidate`/`AnswerFlow.ask` have zero type-awareness — a table row is cited exactly like a paragraph, and no `retrieve`/`answer` test proves a table EU actually gets cited end-to-end (only `tests/evidence/test_builder.py` asserts the block→type mapping). |
| 4b | Tables — PDF/DOCX/PPTX/HTML | ❌ | ❌ | ❌ | `pdf.py` calls `page.extract_text()`, never `page.extract_tables()`. `docx.py` iterates `document.paragraphs`, never `document.tables`. `pptx.py` never checks `shape.has_table`. `html.py`'s selector omits `<table>`. A table in any of these formats is ingested as ordinary paragraph text (DOCX/PDF) or dropped (HTML, since it's outside the `h1-h6, p` selector). |
| 5 | Images/figures via vision | partial | ✅ (logic sound) | ❌ (real docs) | `vision/units.py:build_vision_units` correctly turns `(ImageRef, VisionRecord)` into `EvidenceUnit(type=figure)` — the shaping logic is real and type-preserving. But `pdf.py`/`docx.py`/`pptx.py` always leave `ImageRef.blob_key=None`; `ingest/pipeline.py:_image_bytes` returns `None` when `blob_key` is unset, so `_vision_units` skips every image before `describe_image` is ever called. **Additionally**, `vision/prefilter.py:decide()` — the §9 text/ocr/vision/skip router — is never called from `ingest/pipeline.py`; if bytes were wired up, every image would go straight to a vision call with no decoration filtering. Only proven with manually-injected bytes in tests. |
| 6 | Footnotes / captions | ❌ | ❌ | ❌ | No extractor or evidence module references "footnote" or "caption" as a block concept (image captions inside a `VisionRecord` are the model's own text, not a document's real caption). |
| 7 | Code blocks | ❌ | ❌ | ❌ | `BlockKind.code`/`EUType.code_block` are defined and mapped in `evidence/builder.py`, but no extractor ever constructs `BlockKind.code`. `md.py` silently drops fenced-code tokens (same skip branch as lists); `html.py` never selects `<pre>/<code>`. The type exists in the schema but is dead code. |
| 8 | Document metadata (title, author, created date, page count) | ❌ | ❌ | ❌ | `extract/types.py:ExtractedDoc` carries only `document_id`, `source_type`, `structure_type`, `source_uri`, `blocks`, `images` — no metadata fields. No extractor reads DOCX `core_properties` or PDF metadata. `EvidenceUnit` likewise carries no document-metadata fields; only `document_id` survives downstream. |

## Top gaps, ranked

1. **Vision never actually fires on a real document.** Two independent gaps
   stack: no extractor persists image bytes (`blob_key` stays `None`), *and*
   the §9 pre-filter that would gate/cheapen those calls isn't wired into the
   pipeline at all. Today `vision=` only proves itself in tests with injected
   bytes — it's inert on a real `rag.ingest("file.pdf")`.
2. **Tables only work for CSV.** PDF/DOCX/PPTX/HTML tables are silently
   flattened into paragraph prose (PDF/DOCX) or dropped outright (HTML) — no
   error, no warning, just quietly worse retrieval for tabular evidence.
3. **Lists and code blocks are lost, not flattened.** In Markdown and HTML,
   list items and fenced code blocks are skipped by the extractor loop
   entirely — that content never reaches the evidence store in any form.
   (DOCX lists at least survive as plain-paragraph text, just without
   list structure.)
4. **No type-awareness at citation time.** Even where a typed EU exists
   (table, figure, section), `AnswerFlow.ask`/`Candidate` don't know or care
   what type they're citing — there's no way to say "prefer a table over a
   paragraph for this numeric question" or to label a citation as
   table-sourced in the output.
5. **No document metadata anywhere.** Title/author/date aren't captured, so
   there's no way to answer "what does the 2024 policy say" by filtering on
   metadata — only full-text/structure signals exist.

See [`README.md`](../README.md#what-it-ingests-what-it-does) for the
capability-level summary; this file is the block-by-block trace behind it.
