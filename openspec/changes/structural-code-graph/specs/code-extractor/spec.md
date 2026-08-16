## ADDED Requirements

### Requirement: Code extraction yields one verbatim EU per symbol

The system SHALL provide a `CodeExtractor` that parses a source file into one
`ExtractedBlock` of `BlockKind.code` per top-level named symbol (function, method,
class, type, constant/variable declaration). Each block's `text` MUST be the
**verbatim source span** of that symbol (byte-for-byte, so citations are exact),
and the block MUST carry the symbol's line range so the resulting Evidence Unit
resolves to a `file:Lx-Ly` citation. The returned `ExtractedDoc` MUST set
`structure_type = StructureType.code_ast`. Nested symbols MUST record their
enclosing symbol names in `structure_path` (e.g. a method carries its class name),
and file-level preamble (imports, package/module declarations) MUST be preserved as
at least one leading block so no source content is silently dropped.

#### Scenario: A function becomes a citable symbol EU

- **WHEN** a source file with a top-level function `Tokenize` is extracted
- **THEN** the `ExtractedDoc` contains a `code` block whose `text` is the verbatim
  source of `Tokenize`
- **AND** the block carries `Tokenize`'s line range so its Evidence Unit cites
  `file:Lx-Ly`
- **AND** `structure_type` is `code_ast`

#### Scenario: A method records its enclosing class

- **WHEN** a source file defines a method inside class `Parser`
- **THEN** the method's `code` block carries `("Parser",)` in `structure_path`

#### Scenario: Preamble is preserved, not dropped

- **WHEN** a source file has import/package statements before any symbol
- **THEN** the extraction preserves that preamble as a leading block
- **AND** the concatenation of block texts loses no source content that belongs to
  a recognised symbol or the preamble

### Requirement: Code is ingested through a dedicated typed verb

The system SHALL provide a dedicated code-intake verb `rag.code.ingest_from(source)`
where `source` is a local folder path OR a git URL. It MUST acquire the source
(clone a git URL / walk a folder), filter to code files (skipping vendored and
build directories), and drive the code extractor per file. Code MUST NOT rely on
the generic document `ingest()` firehose — intake is explicit and typed by source
class.

#### Scenario: A folder of code is ingested

- **WHEN** `rag.code.ingest_from("./repo")` is called on a folder
- **THEN** each recognised code file is extracted into symbol Evidence Units
- **AND** vendored/build directories are skipped

#### Scenario: A git URL is cloned and ingested

- **WHEN** `rag.code.ingest_from("<git-url>")` is called
- **THEN** the repository is acquired and its code files are ingested

### Requirement: Code intake requires the graph signal

Because code is meaningless without its structural graph, `rag.code.ingest_from`
MUST raise a clear error immediately when the instance was created without the
`graph` (or `community`) signal declared. It MUST NOT perform a silent or partial
ingest in that case.

#### Scenario: Missing graph signal fails loud

- **WHEN** `rag.code.ingest_from(...)` is called on an instance with no `graph`
  signal declared
- **THEN** it raises an error naming the missing signal
- **AND** no code is ingested

### Requirement: The code extractor is core-provided and cross-SDK at parity

The code extractor SHALL be implemented in the Rust core and exposed through the
`citenexus_extract` C ABI, so every language SDK (Go, JS, Python) obtains it over
FFI without a separate reimplementation. Its output MUST be byte-identical across
SDKs for the same input, proven by a parity test against the Python reference
implementation.

#### Scenario: Same source yields byte-identical extraction across SDKs

- **WHEN** the same source file is extracted through the core from any SDK
- **THEN** the resulting `ExtractedDoc` JSON is byte-identical
- **AND** a parity test asserts the core output matches the Python reference

### Requirement: Unsupported languages fall back without failure

The `CodeExtractor` SHALL support a defined set of languages (at minimum Python and
Go). For a source whose language it cannot parse, extraction MUST NOT raise; the
system MUST fall back to plain-text extraction ("no structure → plain, not
failure"), keeping the source ingested and citable as text.

#### Scenario: An unsupported source degrades to plain text

- **WHEN** a code file in a language the extractor does not support is ingested
- **THEN** ingestion succeeds
- **AND** the content is available as plain-text Evidence Units rather than raising
  an error
