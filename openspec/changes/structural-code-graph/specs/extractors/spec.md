## MODIFIED Requirements

### Requirement: Dispatch routes any source to one extractor

The system SHALL provide `extractor_for(source)` that resolves an extractor by, in
order: an explicit `source_type` (when given), then the source's file extension,
then a plain-text fallback. Known extensions MUST map to their extractors
(`.txt`→txt, `.md`/`.markdown`→md, `.csv`→csv, `.html`/`.htm`→html, `.docx`→docx,
`.pptx`→pptx, `.pdf`→pdf). Recognised **code** extensions (at minimum `.py`→code,
`.go`→code) MUST map to the `CodeExtractor`. An unknown extension, a raw string,
and raw bytes MUST all resolve to the `PlainExtractor`. A companion
`extract(source)` MUST resolve and run the extractor in one call.

#### Scenario: Extensions map to their extractors

- **WHEN** `extractor_for` is given `a.md` (as a path or string)
- **THEN** it returns a `MdExtractor`; likewise each known extension maps to its
  matching extractor.

#### Scenario: Code extensions map to the code extractor

- **WHEN** `extractor_for` is given `a.py` or `a.go`
- **THEN** it returns a `CodeExtractor`.

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
