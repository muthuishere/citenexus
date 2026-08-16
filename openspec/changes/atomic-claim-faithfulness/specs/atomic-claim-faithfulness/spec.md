## ADDED Requirements

### Requirement: Ordered containment predicate

The faithfulness predicate SHALL verify that a claim's tokens appear in the cited
passage **in order**, within a bounded gap, rather than as an unordered set. The
predicate SHALL be a pure, deterministic function of two token arrays, computed
without regular expressions so it ports unchanged to RE2-based runtimes.

The predicate SHALL be strictly narrower than `is_supported`: any claim it
accepts, `is_supported` also accepts. It SHALL therefore never admit a claim that
the frozen predicate rejected.

#### Scenario: Reordered claim is rejected

- **GIVEN** the passage "The tenant shall indemnify the landlord for damage"
- **WHEN** the claim is "The landlord shall indemnify the tenant for damage"
- **THEN** the predicate returns false
- **AND** the claim is not returned to the caller

#### Scenario: Verbatim claim is accepted

- **GIVEN** any passage
- **WHEN** the claim is a verbatim quote of that passage
- **THEN** the predicate returns true

#### Scenario: Contiguous sub-span is accepted

- **GIVEN** the passage "The contractor shall maintain liability insurance at all times"
- **WHEN** the claim is "The contractor shall maintain liability insurance"
- **THEN** the predicate returns true

#### Scenario: Compressed claim within the gap budget is accepted

- **GIVEN** a passage containing the claim's tokens in order with interior words omitted
- **WHEN** the omitted run is within the pinned gap budget
- **THEN** the predicate returns true

#### Scenario: Predicate is narrower than the frozen predicate

- **GIVEN** any claim and passage pair
- **WHEN** the ordered predicate returns true
- **THEN** `is_supported` also returns true for that pair

### Requirement: Polarity guard

A claim SHALL be rejected when the matched span of the passage contains a
polarity marker that the claim does not contain. Polarity markers SHALL be read
from a single canonical table; no port may hand-maintain its own copy.

A language SHALL NOT be declared supported by the polarity table until a golden
fixture exists for it. The table SHALL ship with English only.

#### Scenario: Dropped negation is rejected

- **GIVEN** the passage "The employee shall not disclose confidential information"
- **WHEN** the claim is "The employee shall disclose confidential information"
- **THEN** the predicate returns false

#### Scenario: Preserved negation is accepted

- **GIVEN** the passage "The employee shall not disclose confidential information"
- **WHEN** the claim is "The employee shall not disclose confidential information"
- **THEN** the predicate returns true

#### Scenario: Unclaimed language is absent from the table

- **WHEN** the canonical polarity table is loaded
- **THEN** it contains entries only for languages that have a golden fixture

### Requirement: Guarded claim segmentation

An answer SHALL be decomposed into atomic claims on deterministic boundaries. The
segmenter SHALL consult a table of sentence terminators and abbreviation
exceptions rather than splitting on punctuation alone, so that abbreviations,
decimal numbers and enumerations do not produce spurious claim boundaries.

Segmentation SHALL be deterministic: the same answer always yields the same
claims.

#### Scenario: Abbreviation does not split a claim

- **GIVEN** the answer "Art. 5 applies to all tenants."
- **WHEN** the answer is segmented
- **THEN** exactly one claim is produced

#### Scenario: Decimal number does not split a claim

- **GIVEN** the answer "The dose is 500.00 milligrams daily."
- **WHEN** the answer is segmented
- **THEN** exactly one claim is produced

#### Scenario: Sentence boundary splits claims

- **GIVEN** an answer containing two terminated sentences
- **WHEN** the answer is segmented
- **THEN** two claims are produced

### Requirement: Per-claim verification with drop-not-fail

Each atomic claim SHALL be verified independently against its cited passage.
Unsupported claims SHALL be removed from the answer rather than failing the
answer as a whole. The returned answer SHALL consist only of surviving claims.

When no claim survives, the result SHALL be a refusal.

`Result.claims` SHALL carry one entry per atomic claim with its own verdict and
cited span, and `EvidenceSignals.unsupported_claims_removed` SHALL report the
count of removed claims.

#### Scenario: Partly supported answer degrades to its supported subset

- **GIVEN** a generated answer of two claims where the first is supported by the
  cited passage and the second is not
- **WHEN** the answer is verified
- **THEN** the result is answered
- **AND** the returned answer contains only the first claim
- **AND** `unsupported_claims_removed` is 1

#### Scenario: Wholly unsupported answer is refused

- **GIVEN** a generated answer in which no claim is supported
- **WHEN** the answer is verified
- **THEN** the result is refused
- **AND** no claim text is returned to the caller

#### Scenario: Every claim carries its own verdict

- **GIVEN** any answered result
- **WHEN** the caller inspects `Result.claims`
- **THEN** each entry names the claim, its verdict, and the span it was cited to

### Requirement: The frozen predicate remains available

`is_supported` SHALL remain exported and byte-identical so that existing
conformance vectors continue to pass unchanged. The ordered predicate SHALL be
additive and versioned alongside it.

#### Scenario: Existing conformance vectors pass unchanged

- **WHEN** the shipped conformance vectors for `is_supported` are run
- **THEN** every vector produces its recorded verdict
