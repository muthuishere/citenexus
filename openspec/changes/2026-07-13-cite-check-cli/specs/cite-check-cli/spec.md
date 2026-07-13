## ADDED Requirements

### Requirement: The tool retrieves evidence from a directory it reads itself

`citenexus cite-check "<claim>" <evidence-dir>` SHALL extract text passages from
the files under `<evidence-dir>` using the built-in extractor dispatch, and
SHALL choose the supporting passage(s) for the claim itself. The caller SHALL
NOT supply passage text. No S3 access, no LLM call, and no running `CiteNexus`
instance is required.

#### Scenario: A grounded claim is CITED with a source span
- **GIVEN** an evidence directory containing a file whose text contains every content token of the claim
- **WHEN** the caller runs `citenexus cite-check "<claim>" <dir>`
- **THEN** the verdict is `CITED`
- **AND** the report names the source span — the file path and the block index (and page, when the extractor supplies one) of the passage that supports the claim
- **AND** the process exits `0`

#### Scenario: A fabricated claim with no supporting evidence ABSTAINS
- **GIVEN** an evidence directory whose files contain none of the claim's content tokens in any single passage
- **WHEN** the caller runs `citenexus cite-check "<claim>" <dir>`
- **THEN** the verdict is `ABSTAIN`
- **AND** the report lists the claim's content tokens that no passage covers
- **AND** the process exits `3`, distinct from a setup error

#### Scenario: An empty or unreadable evidence directory ABSTAINS, never CITES
- **GIVEN** an evidence directory with no extractable text
- **WHEN** the caller runs `citenexus cite-check "<claim>" <dir>`
- **THEN** the verdict is `ABSTAIN` (fail-closed), never `CITED`

### Requirement: The default verdict is AIS-strict full support; abstain fails safe

By default the tool SHALL return `CITED` only when a single retrieved passage
contains every content token of the claim (an AIS full-support proxy), and SHALL
return `ABSTAIN` otherwise. A `--min-coverage <ratio>` option (0.0–1.0, default
1.0) MAY relax the threshold to a RAGAS-style content-token coverage ratio;
lowering it SHALL only ever turn ABSTAIN into CITED, never the reverse.

#### Scenario: Partial support abstains under the strict default
- **GIVEN** a claim whose best passage covers some but not all of its content tokens
- **WHEN** the caller runs `citenexus cite-check` with no `--min-coverage`
- **THEN** the verdict is `ABSTAIN`

#### Scenario: --min-coverage relaxes toward a coverage ratio
- **GIVEN** the same claim whose best passage covers 0.8 of its content tokens
- **WHEN** the caller runs `citenexus cite-check --min-coverage 0.75`
- **THEN** the verdict is `CITED` and the report records the achieved coverage ratio

### Requirement: The gate reuses the pinned faithfulness primitives, never a copy

The tool SHALL decide full support using `citenexus.answer.verify.is_supported`
and compute coverage using `citenexus.answer.verify.content_tokens` —  the same
functions the internal answer flow uses — so its verdict cannot drift from the
library's faithfulness gate.

#### Scenario: cite-check and the internal gate agree on identical text
- **GIVEN** a (claim, passage) pair where the passage is the single file in an evidence dir
- **WHEN** both `cite-check` and `is_supported(claim, passage)` evaluate it
- **THEN** `cite-check`'s CITED/ABSTAIN verdict matches `is_supported`'s boolean under the strict default

### Requirement: A machine-readable verdict for downstream organs

With `--format json` the tool SHALL emit a stable JSON verdict object carrying at
least: `verdict` (`"CITED"`|`"ABSTAIN"`), `claim`, `coverage` (0.0–1.0),
`min_coverage`, `sources` (each with `file`, `block`, optional `page`, and the
matched `passage` excerpt), and `uncovered_tokens`. This object is the
integration contract consumed by the brain (recorded as an episode) and the
huddle verifier (consumed as evidence).

#### Scenario: JSON verdict is emitted for both outcomes
- **WHEN** the caller runs `citenexus cite-check "<claim>" <dir> --format json`
- **THEN** stdout is a single JSON object with the fields above
- **AND** for `CITED` the `sources` array is non-empty; for `ABSTAIN` `uncovered_tokens` is non-empty

### Requirement: Exit codes distinguish CITED, ABSTAIN, and setup error

The process SHALL exit `0` for `CITED`, `3` for `ABSTAIN`, and `2` for a setup
error (missing/unreadable directory, bad arguments) — so a caller (the CEO's
pre-"done" gate, a CI job) can tell "the gate ran and refused" (`3`) from "the
gate could not run" (`2`).

#### Scenario: A missing evidence directory is a setup error, not an abstention
- **GIVEN** an evidence-dir path that does not exist
- **WHEN** the caller runs `citenexus cite-check "<claim>" /no/such/dir`
- **THEN** the process exits `2`, distinct from the `3` used for ABSTAIN
