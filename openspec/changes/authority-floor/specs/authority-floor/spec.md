## ADDED Requirements

### Requirement: Authority metadata is carried, never derived

The library SHALL accept caller-supplied authority metadata at ingest time and
persist it on the Evidence Unit rows. The metadata SHALL be opaque key/value
data that the library carries but never interprets as content.

Authority SHALL NEVER be derived from passage text. No authority code path may
read a candidate's `text`, `passage`, or `citable_text`.

The metadata SHALL be additive: a corpus ingested without it reads back as empty
and is treated as unranked.

#### Scenario: Metadata supplied at ingest reaches the candidate

- **GIVEN** a document ingested with authority metadata
- **WHEN** that document's Evidence Unit is retrieved
- **THEN** the candidate carries the same metadata that was supplied

#### Scenario: A corpus ingested without authority metadata is unranked

- **GIVEN** a document ingested with no authority metadata
- **WHEN** that document's Evidence Unit is retrieved
- **THEN** the candidate's authority metadata is empty
- **AND** the default profile assigns it the same tier as every other source

#### Scenario: Authority never reads passage text

- **WHEN** an authority profile assigns a tier
- **THEN** it is a pure function of the candidate's authority metadata alone

### Requirement: Pluggable authority profile with a total order

An `AuthorityProfile` SHALL map authority metadata to an `AuthorityTier` that is
totally ordered, with a higher rank meaning more authoritative. Profiles SHALL be
pluggable and deterministic: the same metadata always yields the same tier.

The `default.v1` profile SHALL assign every source the same tier, reproducing
today's behaviour exactly.

An `ordered.v1` profile SHALL be constructed from a caller-supplied ordering of
tier names, least-authoritative first. Metadata naming a tier absent from that
ordering SHALL be ranked below every named tier.

#### Scenario: default.v1 ranks everything equal

- **GIVEN** any two sources with any authority metadata
- **WHEN** `default.v1` assigns their tiers
- **THEN** the two tiers compare equal

#### Scenario: ordered.v1 respects the caller's ordering

- **GIVEN** an ordering of tier names, least-authoritative first
- **WHEN** two sources carry different named tiers
- **THEN** the source whose tier appears later in the ordering ranks higher

#### Scenario: An unknown tier ranks below every named tier

- **GIVEN** a source whose metadata names a tier absent from the ordering
- **WHEN** its tier is compared to any named tier
- **THEN** the unknown tier ranks lower

### Requirement: Authority is applied strictly after grounding

Authority selection SHALL be applied to candidates that have already passed
grounding. Authority SHALL NOT be an input to the faithfulness predicate, and the
faithfulness predicate SHALL remain byte-identical.

Authority SHALL NOT promote any candidate that grounding rejected.

#### Scenario: The faithfulness gate is unchanged

- **WHEN** the authority feature is enabled with any profile and any floor
- **THEN** the faithfulness predicate receives exactly the claim and the passage
- **AND** its verdict for a given claim/passage pair is unchanged

#### Scenario: Authority cannot resurrect ungrounded evidence

- **GIVEN** a candidate that grounding excluded
- **WHEN** authority selection runs
- **THEN** that candidate is not a selection input at any tier

### Requirement: Strict-mode authority floor

In `strict` trust mode, when the caller has set a minimum tier, every candidate
below that tier SHALL be excluded from selection. When no candidate at or above
the minimum tier supports an answer, the result SHALL be a refusal.

The library SHALL NOT fall back to a lower-tier source under any circumstances.

#### Scenario: A below-floor source is never cited in strict mode

- **GIVEN** strict mode with a configured minimum tier
- **AND** the only grounded candidate is below that tier
- **WHEN** the question is asked
- **THEN** the result is a refusal
- **AND** no source is cited from below the floor

#### Scenario: An at-or-above-floor source answers

- **GIVEN** strict mode with a configured minimum tier
- **AND** a grounded candidate at or above that tier
- **WHEN** the question is asked
- **THEN** that candidate may be cited

#### Scenario: No floor configured leaves strict mode unchanged

- **GIVEN** strict mode with no minimum tier configured
- **WHEN** the question is asked
- **THEN** the same candidates are available as before the feature existed

### Requirement: TrustMode coupling

`strict` SHALL enforce the minimum tier or abstain. `normal` SHALL use authority
as a tie-break only — candidates are reordered by tier and none is ever dropped.
`exploratory` SHALL ignore authority entirely, leaving candidate order untouched.

Reordering SHALL be stable: candidates of equal tier keep their fusion order.

#### Scenario: Normal mode drops nothing

- **GIVEN** normal mode with a configured minimum tier
- **AND** grounded candidates both below and above the floor
- **WHEN** authority selection runs
- **THEN** every grounded candidate is still available
- **AND** the higher-tier candidates are ordered first

#### Scenario: Exploratory mode ignores authority

- **GIVEN** exploratory mode with any profile and any floor
- **WHEN** authority selection runs
- **THEN** the candidate order is identical to the input order

#### Scenario: Equal tiers keep fusion order

- **GIVEN** several grounded candidates of equal tier
- **WHEN** authority selection runs
- **THEN** their relative order is unchanged

### Requirement: Authority is a distinguishable signal on the Result

`EvidenceSignals` SHALL carry the cited source's authority tier name and whether
the authority floor actually WITHHELD grounded evidence. The latter SHALL be true
only when the floor excluded at least one candidate — not merely because a floor
was configured, since a signal true on every strict call carries no information.

A refusal caused by insufficient authority SHALL
be distinguishable from a refusal caused by absent evidence, both by these
signals and by the refusal's stated reason.

These fields SHALL be additive and default to their empty values, so results
produced without authority metadata are unchanged.

#### Scenario: Insufficient authority is distinguishable from no evidence

- **GIVEN** a refusal because every grounded candidate is below the floor
- **WHEN** the caller inspects the result
- **THEN** `authority_floor_applied` is true
- **AND** the stated missing-evidence reason names insufficient authority
- **AND** it differs from the reason given when no relevant evidence was found

#### Scenario: An answered result reports the cited tier

- **GIVEN** an answered result whose cited source carries authority metadata
- **WHEN** the caller inspects the result
- **THEN** `authority_tier` names the cited source's tier

#### Scenario: Results without authority metadata are unchanged

- **GIVEN** a corpus ingested without authority metadata and no floor configured
- **WHEN** any question is asked
- **THEN** `authority_tier` is empty and `authority_floor_applied` is false
