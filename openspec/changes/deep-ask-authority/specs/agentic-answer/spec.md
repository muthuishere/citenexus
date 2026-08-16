## ADDED Requirements

### Requirement: Deep-ask enforces the same authority policy as the strict flow

The deep-ask strategy SHALL apply the caller's `AuthorityPolicy`. A client
configured with an authority profile and a minimum tier SHALL apply it to
`strategy="deep"` with no additional caller configuration, using the same policy
object as `strategy="strict"`.

Authority SHALL remain a selection / minimum-bar signal derived from source
metadata, applied after the evidence exists and never as an input to the
faithfulness predicate. The per-claim single-EU gate SHALL be unchanged and
SHALL never receive a tier.

#### Scenario: A below-floor source cannot answer a deep-ask question

- **GIVEN** strict mode with a configured minimum tier
- **AND** the only evidence the loop can retrieve is below that tier
- **WHEN** the question is asked with the deep strategy
- **THEN** the result is a refusal
- **AND** no below-floor source is cited

#### Scenario: Deep-ask inherits the client's policy

- **GIVEN** a client configured with an authority profile and a minimum tier
- **WHEN** a question is asked with the deep strategy
- **THEN** the floor is enforced without any deep-specific configuration

#### Scenario: No policy configured leaves deep-ask unchanged

- **GIVEN** the default profile and no configured minimum tier
- **WHEN** a question is asked with the deep strategy
- **THEN** the result is exactly what it was before authority reached the loop

### Requirement: The floor is enforced at pool admission

Below-floor Evidence Units SHALL NOT enter the loop's evidence pool. A withheld
Evidence Unit SHALL NOT occupy an `max_evidence_units` budget slot, SHALL NOT be
presented to the decision model, SHALL NOT enter the conflict-detection window,
and SHALL NOT be available to support any claim.

#### Scenario: A withheld unit never reaches the decision model

- **GIVEN** strict mode with a configured minimum tier
- **WHEN** a hop returns a below-floor Evidence Unit
- **THEN** the decision model is not shown that unit's text

#### Scenario: A withheld unit consumes no budget

- **GIVEN** an evidence-unit budget and a hop returning below-floor units
- **WHEN** the loop pools evidence
- **THEN** the withheld units do not count toward the budget

#### Scenario: A withheld unit cannot support a claim

- **GIVEN** an answer claim whose only textual support is a below-floor unit
- **WHEN** the per-claim single-EU gate runs
- **THEN** the claim is not supported and is not emitted

### Requirement: The pool is ordered by authority before generation

After gathering, the pooled Evidence Units SHALL be ordered by descending
authority tier before the answer is generated, so that the strongest-standing
evidence leads the passage and a claim is attributed to the most authoritative
Evidence Unit that supports it. The ordering SHALL be stable: units of equal tier
keep their pooling order.

#### Scenario: The most authoritative supporting unit is cited

- **GIVEN** two pooled units of different tiers that both support a claim
- **WHEN** the answer is produced
- **THEN** the claim is cited to the higher-tier unit

#### Scenario: Equal tiers keep pooling order

- **GIVEN** pooled units of equal tier
- **WHEN** the pool is ordered
- **THEN** their relative order is unchanged

### Requirement: Withheld evidence is distinguishable from exhausted evidence

A hop that admits no new Evidence Unit **because every returned unit was withheld
for standing** SHALL NOT be treated as the `no_new_evidence` stop. The loop SHALL
be permitted to refine and continue searching for evidence that meets the floor,
bounded by the existing hop, tool-call and wall-clock budgets.

A hop that returns only already-pooled units SHALL continue to stop the loop with
`no_new_evidence`, unchanged.

#### Scenario: The loop keeps looking after a withheld-only hop

- **GIVEN** a first hop returning only below-floor units
- **AND** a later hop that can reach an at-or-above-floor unit
- **WHEN** the question is asked
- **THEN** the loop continues past the first hop
- **AND** the answer is grounded in the at-or-above-floor unit

#### Scenario: An already-seen-only hop still halts

- **GIVEN** a hop returning only Evidence Units already in the pool
- **WHEN** the loop evaluates the hop
- **THEN** it stops with `no_new_evidence`

### Requirement: Deep-ask reports authority in its signals

A deep-ask result SHALL set `authority_floor_applied` true when, and only when,
the floor actually withheld at least one Evidence Unit during the run.
`authority_tier` SHALL report the weakest tier among the cited Evidence Units, so
a multi-source answer never reports stronger standing than its weakest support.

A refusal caused by the floor emptying the pool SHALL name insufficient authority
as its reason, SHALL be distinguishable from a refusal for absent evidence, and
SHALL occur without calling the generator.

#### Scenario: An authority refusal is distinguishable and cheap

- **GIVEN** strict mode where every retrievable unit is below the floor
- **WHEN** the question is asked with the deep strategy
- **THEN** `authority_floor_applied` is true
- **AND** the stated reason names insufficient authority
- **AND** the generator is never called

#### Scenario: The weakest cited tier is reported

- **GIVEN** an answer citing units of two different tiers
- **WHEN** the caller inspects the result
- **THEN** `authority_tier` names the lower of the two

#### Scenario: A run that withheld nothing reports no floor application

- **GIVEN** a floor configured and every retrieved unit at or above it
- **WHEN** the question is asked
- **THEN** `authority_floor_applied` is false

### Requirement: TrustMode coupling in deep-ask matches the strict flow

`strict` SHALL withhold below-floor units from the pool or abstain. `normal`
SHALL use authority as a tie-break only — units are ordered by tier and none is
ever withheld. `exploratory` SHALL ignore authority entirely.

#### Scenario: Normal mode withholds nothing

- **GIVEN** normal mode with a configured minimum tier
- **AND** retrievable units both below and above that tier
- **WHEN** the question is asked with the deep strategy
- **THEN** every retrieved unit is pooled
- **AND** the higher-tier units are ordered first

#### Scenario: Exploratory mode ignores authority

- **GIVEN** exploratory mode with any profile and any floor
- **WHEN** the question is asked with the deep strategy
- **THEN** the pool and its order are what they would be with no policy at all
