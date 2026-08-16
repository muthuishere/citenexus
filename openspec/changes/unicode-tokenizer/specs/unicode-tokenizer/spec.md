## ADDED Requirements

### Requirement: Versioned tokenizer

The Unicode tokenizer SHALL ship as `tokenize_v2`, **alongside** the frozen
`tokenize`, never as an edit to it. `tokenize` SHALL remain byte-identical so the
shipped conformance vectors and the Go/JS ports continue to pass unchanged.

`tokenize_v2` SHALL treat Unicode letter, number and mark classes as
word-forming, and SHALL case-fold rather than lowercase. It SHALL be pure and
deterministic, and SHALL be computed without regular expressions so it ports to
RE2-based and JS runtimes without property-escape divergence.

`tokenize_v2` SHALL agree with `tokenize` on any input whose word characters are
all ASCII.

#### Scenario: v1 stays frozen

- **GIVEN** any text in a non-Latin script
- **WHEN** `tokenize` is called
- **THEN** it returns the empty list, exactly as before

#### Scenario: v2 produces tokens where v1 produced none

- **GIVEN** a sentence in Japanese, Chinese, Arabic or Tamil
- **WHEN** `tokenize_v2` is called
- **THEN** it returns a non-empty token list

#### Scenario: ASCII behavior is unchanged

- **GIVEN** any text whose word characters are all ASCII
- **WHEN** both tokenizers are called
- **THEN** they return identical token lists

#### Scenario: Accented Latin is not truncated

- **GIVEN** the text "Café"
- **WHEN** `tokenize_v2` is called
- **THEN** it returns `["café"]`, not the truncated stub `["caf"]`

#### Scenario: Case folding, not lowercasing

- **GIVEN** the texts "Straße" and "STRASSE"
- **WHEN** `tokenize_v2` is called on each
- **THEN** both return `["strasse"]`

### Requirement: Segmentation for scripts written without spaces

Scripts that do not separate words with spaces SHALL be segmented, not merely
classified. Whitespace splitting yields one token per sentence, which makes BM25
and any containment predicate degenerate.

Such scripts SHALL be character-bigram indexed — deterministic and dictionary-
free. Bigrams SHALL form within a single script run and SHALL NOT cross a script
boundary. Dictionary-based word breaking is explicitly out of scope.

Scripts that DO write spaces — including Hangul — SHALL NOT be bigram indexed.

#### Scenario: CJK is bigram indexed

- **GIVEN** the passage "员工不得披露机密信息"
- **WHEN** `tokenize_v2` is called
- **THEN** it returns the character bigrams of that run, one fewer than its length

#### Scenario: A CJK sub-span is contained in its passage

- **GIVEN** the passage "员工不得披露机密信息"
- **WHEN** the claim is "机密信息"
- **THEN** the faithfulness predicate returns true

#### Scenario: CJK reordering is still rejected

- **GIVEN** the passage "员工不得披露机密信息"
- **WHEN** the claim reorders those characters
- **THEN** the faithfulness predicate returns false

#### Scenario: Korean is not bigram indexed

- **GIVEN** the text "직원은 기밀 정보를"
- **WHEN** `tokenize_v2` is called
- **THEN** it returns one token per space-delimited word

### Requirement: A script is claimed, not assumed

Supported scripts SHALL be an explicit allowlist. **No script may be claimed as
supported without a golden fixture**, and the fixture SHALL assert three things
for that script: tokens are produced, a verbatim quote of a passage is accepted
by the faithfulness gate, and unrelated text is still rejected.

Generation of the conformance fixtures SHALL FAIL when the allowlist and the
fixture set disagree in either direction, so the claim and the evidence for it
are the same artifact.

Scripts SHALL be added one at a time.

#### Scenario: Claiming a script without a fixture is impossible

- **GIVEN** a script added to the supported allowlist
- **WHEN** the conformance fixtures are generated with no golden fixture for it
- **THEN** generation raises rather than emitting an unbacked claim

#### Scenario: Every claimed script survives its own quote

- **GIVEN** any script in the allowlist
- **WHEN** a passage in that script is quoted verbatim as the claim
- **THEN** the faithfulness predicate returns true

### Requirement: Unsupported script is a distinct signal

Where the tokenizer cannot be trusted with a script, the Result SHALL say so,
**distinct** from "no supporting evidence". A capability gap SHALL NOT be
reported as an evidence judgement.

The signal SHALL be carried on `EvidenceSignals` and SHALL be empty for input in
claimed scripts only, so existing Results are unchanged.

A script that the tokenizer will mechanically process but that is NOT claimed
SHALL be treated as unsupported. Producing tokens is not the same as having a
verified segmentation, and an unverified answer that looks verified is worse than
an abstain.

#### Scenario: An unreadable question abstains and says why

- **GIVEN** a question in an unclaimed script
- **THEN** the decision is `refused`
- **AND** `missing_evidence` names the unsupported script
- **AND** `unsupported_scripts` lists it

#### Scenario: The evidence-absent refusal stays about the evidence

- **GIVEN** a question in a claimed script with no relevant evidence
- **THEN** the decision is `refused`
- **AND** `missing_evidence` is the evidence-absent reason
- **AND** `unsupported_scripts` is empty

#### Scenario: An unclaimed passage is reported but never cited

- **GIVEN** evidence in a claimed script and evidence in an unclaimed script
- **WHEN** the question is answerable from the claimed evidence
- **THEN** the answer cites only the claimed passage
- **AND** `unsupported_scripts` still reports the gap

### Requirement: Tokenizer version recorded per index

The tokenizer version SHALL be recorded per partition when it is indexed, so a
tokenizer/index mismatch is detectable rather than silent.

A partition with no recorded version SHALL read as version 1 — it was written
before versioning existed, therefore by v1. It SHALL NOT default to the running
version.

#### Scenario: An unstamped partition reads as stale

- **GIVEN** a partition indexed before the stamp existed
- **WHEN** its tokenizer manifest is read
- **THEN** the version is 1 and the index reports as stale

#### Scenario: Ingest stamps the partition

- **GIVEN** a document ingested by the current library
- **WHEN** the partition's tokenizer manifest is read
- **THEN** it records the running tokenizer version and reports as fresh
