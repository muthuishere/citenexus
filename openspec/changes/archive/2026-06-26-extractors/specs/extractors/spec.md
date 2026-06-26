## ADDED Requirements

### Requirement: Every extractor returns the shared ExtractedDoc shape

Each extractor SHALL be an `ExtractorPlugin` subclass with a non-empty
`plugin_version` whose `extract(source)` returns an `ExtractedDoc`. The doc MUST
set `source_type`, a best-effort `structure_type`, and `document_id` (the
filename stem when the source is a path, else a caller-supplied id or a default).
Every `ExtractedBlock` MUST carry a sequential `order` starting at 0, a `kind`,
and `text`; optional `page`/`bbox`/`level`/`structure_path` MUST be populated only
where known.

#### Scenario: Blocks are ordered from zero

- **WHEN** any extractor returns an `ExtractedDoc` with N blocks
- **THEN** the blocks' `order` values are `0, 1, … N-1` in emission order.

#### Scenario: Document id derives from the filename stem

- **WHEN** a source is a filesystem path `notes.txt`
- **THEN** the resulting `ExtractedDoc.document_id` is `notes` and `source_uri`
  is the path.

### Requirement: Plain text extraction and unknown-type fallback

The system SHALL provide a `PlainExtractor` that treats any source as raw text —
decoding `bytes` as UTF-8 — and emits exactly one `paragraph` block containing the
whole text, with `source_type=plain` and `structure_type=none`. The same extractor
MUST serve as the fallback for unknown source types.

#### Scenario: Raw string becomes one paragraph

- **WHEN** `PlainExtractor` extracts the string `"just some text"`
- **THEN** the doc has `source_type=plain`, `structure_type=none`, and exactly one
  `paragraph` block whose text is `"just some text"`.

#### Scenario: Bytes are decoded as UTF-8

- **WHEN** `PlainExtractor` extracts the bytes of `"café"`
- **THEN** the single block's text is `"café"`.

### Requirement: Text extractor splits paragraphs without structure

The `TxtExtractor` SHALL split a `.txt` source into blank-line-separated
paragraphs, emitting one `paragraph` block per non-empty chunk, with
`source_type=txt` and `structure_type=none`.

#### Scenario: Blank lines delimit paragraphs

- **WHEN** `TxtExtractor` extracts `"First paragraph line.\n\nSecond paragraph here."`
- **THEN** it yields two `paragraph` blocks with those two texts and
  `structure_type=none`.

### Requirement: Markdown extraction builds a heading tree

The `MdExtractor` (markdown-it-py) SHALL emit `heading` blocks carrying their
`level` and the ancestor headings as `structure_path`, and `paragraph` blocks
carrying the enclosing heading path. `structure_type` MUST be `heading_tree` when
at least one heading exists, otherwise `none`. `source_type` MUST be `md`.

#### Scenario: Headings carry level and ancestor path

- **WHEN** `MdExtractor` extracts `"# Title\n\nIntro paragraph.\n\n## Section A\n\nBody of A.\n"`
- **THEN** it yields heading `Title` (level 1, empty path), paragraph
  `Intro paragraph.` (path `("Title",)`), heading `Section A` (level 2, path
  `("Title",)`), and paragraph `Body of A.` (path `("Title","Section A")`), with
  `structure_type=heading_tree`.

#### Scenario: Structureless markdown reports none

- **WHEN** `MdExtractor` extracts `"just a line of prose"`
- **THEN** `structure_type` is `none` and the only block is a `paragraph`.

### Requirement: CSV extraction yields a table schema and row blocks

The `CsvExtractor` (stdlib `csv`) SHALL treat the first row as the header schema,
set `structure_type=table_schema`, and emit one `table` block per data row whose
`structure_path` is the header columns and whose `level` is the 0-based row index.
An empty source MUST yield no blocks and `structure_type=none`. `source_type` MUST
be `csv`.

#### Scenario: Header becomes schema and rows become table blocks

- **WHEN** `CsvExtractor` extracts `"name,age\nalice,30\nbob,25\n"`
- **THEN** it yields two `table` blocks, the first with `structure_path=("name","age")`,
  `level=0`, and text containing `alice` and `30`, with `structure_type=table_schema`.

#### Scenario: Empty CSV has no structure

- **WHEN** `CsvExtractor` extracts the empty string
- **THEN** it yields no blocks and `structure_type=none`.

### Requirement: HTML extraction strips scripts and styles

The `HtmlExtractor` (bs4) SHALL remove `<script>` and `<style>` subtrees before
extraction, then emit `heading` and `paragraph` blocks in document order — headings
carrying `level` and ancestor `structure_path`. `structure_type` MUST be
`heading_tree` when a heading exists, else `none`. `source_type` MUST be `html`.

#### Scenario: Headings, paragraphs, and stripped non-content

- **WHEN** `HtmlExtractor` extracts an HTML body with `<h1>Main</h1><p>Para one</p>`,
  a `<script>`, a `<style>`, and `<h2>Sub</h2><p>Para two</p>`
- **THEN** it yields heading `Main` (level 1), paragraph `Para one`, heading `Sub`
  (level 2, path `("Main",)`), paragraph `Para two` (path `("Main","Sub")`), and no
  block text contains the script or style content.

### Requirement: DOCX extraction maps heading styles and images

The `DocxExtractor` (python-docx) SHALL map `Heading N` paragraph styles to
`heading` blocks (level N + ancestor `structure_path`), other non-empty paragraphs
to `paragraph` blocks under their heading path, and each embedded image part to an
`ImageRef`. `structure_type` MUST be `heading_tree` and `source_type` `docx`.

#### Scenario: Heading styles, body, and an embedded image

- **WHEN** `DocxExtractor` extracts a document with a Heading 1, a body paragraph,
  a Heading 2, another body paragraph, and one embedded image
- **THEN** it yields the two headings (levels 1 and 2, the level-2 heading with path
  `("Title One",)`), the two paragraphs, and exactly one `ImageRef`, with
  `structure_type=heading_tree`.

### Requirement: PPTX extraction emits one block per slide

The `PptxExtractor` (python-pptx) SHALL emit one `slide` block per slide — text
frames joined — with `page` set to the 1-based slide number and
`structure_type=slide_sequence`, and one `ImageRef` per picture anchored to its
slide's page. `source_type` MUST be `pptx`.

#### Scenario: Two slides and a picture

- **WHEN** `PptxExtractor` extracts a deck of two slides where slide one has a
  picture
- **THEN** it yields two `slide` blocks with `page` 1 and 2 and the slides' text,
  `structure_type=slide_sequence`, and one `ImageRef` with `page=1`.

### Requirement: PDF extraction yields page text with page numbers and bboxes

The `PdfExtractor` (pdfplumber) SHALL emit one block per page carrying the page
text and its 1-based `page` number, set a word-derived `bbox` where words are
available, set `structure_type=page_layout`, and emit an `ImageRef` per page image.
`source_type` MUST be `pdf`.

#### Scenario: Single-page text with page number and bbox

- **WHEN** `PdfExtractor` extracts a single-page PDF containing one text line
- **THEN** it yields one block with `page=1`, text containing that line, a 4-number
  `bbox`, and `structure_type=page_layout`.

### Requirement: Dispatch routes any source to one extractor

The system SHALL provide `extractor_for(source)` that resolves an extractor by, in
order: an explicit `source_type` (when given), then the source's file extension,
then a plain-text fallback. Known extensions MUST map to their extractors
(`.txt`→txt, `.md`/`.markdown`→md, `.csv`→csv, `.html`/`.htm`→html, `.docx`→docx,
`.pptx`→pptx, `.pdf`→pdf). An unknown extension, a raw string, and raw bytes MUST
all resolve to the `PlainExtractor`. A companion `extract(source)` MUST resolve and
run the extractor in one call.

#### Scenario: Extensions map to their extractors

- **WHEN** `extractor_for` is given `a.md` (as a path or string)
- **THEN** it returns a `MdExtractor`; likewise each known extension maps to its
  matching extractor.

#### Scenario: Unknown extension and raw content fall back to plain

- **WHEN** `extractor_for` is given `a.xyz`, a raw string `"just some prose"`, or
  raw bytes
- **THEN** each returns a `PlainExtractor`.

#### Scenario: Explicit source type overrides the extension

- **WHEN** `extractor_for("a.txt", source_type=md)` is called
- **THEN** it returns a `MdExtractor`.

#### Scenario: Convenience extract runs the resolved extractor

- **WHEN** `extract("hello world")` is called
- **THEN** it returns an `ExtractedDoc` with `source_type=plain` whose single block
  text is `"hello world"`.
