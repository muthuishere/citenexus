# emit-markdown Specification

## Purpose
Deterministic ExtractedDoc→markdown rendering plus the any-supported-format→markdown front door (bytes + source_type → markdown) exposed through the C ABI to every language binding.
## Requirements
### Requirement: Deterministic ExtractedDoc→markdown rendering

The system SHALL provide a pure function `to_markdown(doc: ExtractedDoc) -> str`
that renders the document's blocks, in `order`, to GitHub-flavored markdown
using these deterministic rules:

- `heading` → `#` repeated `clamp(level or 1, 1, 6)` times, a space, then the
  block text.
- `paragraph`, `thread_turn`, `ocr_block` → the block text verbatim.
- `table` → a run of contiguous `table` blocks sharing the same non-empty
  `structure_path` (their header) fuses into ONE GitHub-flavored pipe table:
  a header row from `structure_path`, a `| --- |` separator, then one row per
  block built from its `cells` (truncated/`""`-padded to the header width).
  Each cell has `|`→`\|` and newline→space applied. A `table` block with an
  empty `structure_path` falls back to its text verbatim.
- `code` → the block text wrapped in triple-backtick fences on their own lines.
- `image` → the block text verbatim (caption/OCR text, or an inline
  `![image](data:…base64…)` data-URI from the image extractor) when non-empty,
  otherwise the literal placeholder `![image]()`.
- `slide` → a `## Slide {page}` heading (1-based slide number from `page`;
  omitted entirely when `page` is null) followed by a blank line and the slide
  text verbatim.

Blocks are joined by exactly one blank line (`\n\n`); non-empty output ends
with a single trailing `\n`; a document with zero blocks renders as the empty
string. The function is total over the closed `BlockKind` set and never fails.

#### Scenario: Heading levels render and clamp

- **WHEN** a doc contains heading blocks with `level` 2, null, and 9
- **THEN** they render as `## `, `# `, and `###### ` prefixed lines
  respectively.

#### Scenario: Rendering is deterministic and byte-stable

- **WHEN** the same `ExtractedDoc` is rendered twice
- **THEN** the two markdown strings are byte-identical.

#### Scenario: Empty document renders empty

- **WHEN** a doc has no blocks
- **THEN** `to_markdown` returns the empty string.

#### Scenario: Contiguous table rows fuse into a GFM pipe table

- **WHEN** two consecutive `table` blocks share `structure_path` `(name, age)`
  with `cells` `(ada, 36)` and `(lin, 29)`
- **THEN** they render as one table:
  `| name | age |` / `| --- | --- |` / `| ada | 36 |` / `| lin | 29 |`,
  and a following block with a different `structure_path` starts a new table.

#### Scenario: A standalone image inlines as a base64 data-URI

- **WHEN** an image file at or below the 256 KiB inline cap with a recognized
  magic (png/jpeg/gif/webp) is extracted
- **THEN** its `image` block text is `![image](data:image/<mime>;base64,<…>)`;
  above the cap or for an unrecognized magic the text is empty and the emitter
  renders the `![image]()` placeholder.

### Requirement: Excel workbooks extract as per-sheet tables

The system SHALL extract `.xlsx` workbooks (new `SourceType.xlsx`, mapped from
the `.xlsx` extension in both dispatchers) with csv-twin semantics per sheet:
one heading block carrying the sheet name, then one `table` block per data row
rendered as `col: value` pairs zipped (shortest) against the sheet's first-row
header, the header carried on `structure_path`, `page` set to the 1-based
sheet index, `structure_type = table_schema` when any sheet has rows. The
Python implementation (`openpyxl`) is the behavior reference; the Rust twin
(`calamine`) SHALL produce byte-identical `ExtractedDoc` JSON.

#### Scenario: A two-sheet workbook extracts sheet-scoped rows

- **WHEN** a workbook with two named sheets, each with a header row and data
  rows, is extracted
- **THEN** each sheet contributes a heading block with its name followed by
  its `col: value` table blocks, with `page` distinguishing the sheets.

#### Scenario: An empty workbook is not a failure

- **WHEN** a workbook whose sheets have no data rows is extracted
- **THEN** extraction succeeds with the sheet heading blocks only and no
  table blocks.

### Requirement: Any supported format converts to markdown through one front door

The Rust core SHALL expose `citenexus_to_markdown(bytes, len, source_type)` in
the C ABI, composing the existing extraction dispatch with the markdown
emitter: it accepts every `SourceType` the core extracts (txt, md, csv, html,
docx, pptx, xlsx, pdf, plain fallback), returns `{"markdown": "..."}` JSON on
success and `{"error": "..."}` on failure (same conventions as
`citenexus_extract`, released via `citenexus_free_string`). PDF availability
follows the existing `pdf` feature gate.

#### Scenario: A docx converts to markdown via the C ABI

- **WHEN** `citenexus_to_markdown` is called with docx bytes and
  `source_type = "docx"`
- **THEN** the result JSON contains a `markdown` field whose headings carry
  `#` prefixes matching the document's heading levels.

#### Scenario: An unknown source type falls back to plain

- **WHEN** bytes are converted with an extension-mapped unknown type (`plain`)
- **THEN** the markdown is the plain-text paragraphs joined by blank lines,
  not an error.

#### Scenario: Failures return the error convention

- **WHEN** invalid docx bytes are converted as `source_type = "docx"`
- **THEN** the result is `{"error": ...}` and no markdown field.

### Requirement: Python reference and Rust emitter are byte-identical

The Python implementation (`citenexus.extract.markdown.to_markdown`) SHALL
remain the behavior reference; for every conformance fixture, markdown
produced by Python (`to_markdown(extract(...))`) and by the Rust core through
the real C ABI SHALL be byte-identical.

#### Scenario: Parity across all fixture formats

- **WHEN** the parity suite renders every conformance fixture through both
  implementations
- **THEN** each pair of markdown strings is byte-identical.

### Requirement: All bindings expose the converter

The Go binding SHALL expose `core.ToMarkdown(data []byte, sourceType string)`
and the TS binding SHALL expose `toMarkdown(buf, sourceType)`, each a thin
wrapper over `citenexus_to_markdown` following that binding's existing
error-surface conventions.

#### Scenario: Go and TS wrappers convert a fixture

- **WHEN** the same html fixture is converted via `golang/core.ToMarkdown` and
  `js` `toMarkdown`
- **THEN** both return the same markdown string the Rust core produced.
