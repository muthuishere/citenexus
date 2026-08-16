## 1. Domain: tier + profile

- [x] 1.1 Red: tests for `AuthorityTier` total order (rank only, name never compared)
- [x] 1.2 Red: tests for `default.v1` — every metadata maps to one equal tier
- [x] 1.3 Red: tests for `ordered.v1` — caller ordering respected, unknown tier below all
- [x] 1.4 Implement `domain/authority.py`: `AuthorityTier`, `AuthorityProfile`
      protocol, `DefaultAuthorityProfile`, `OrderedTierProfile`, `AuthorityPolicy`,
      and the `authority_meta` encode/decode helpers
- [x] 1.5 Assert the profile seam takes `Mapping[str, str]` only — it structurally
      cannot read passage text

## 2. Selection point

- [x] 2.1 Red: `select_by_authority` — strict drops below-floor, normal reorders
      only, exploratory is the identity
- [x] 2.2 Red: stability — equal tiers keep fusion order
- [x] 2.3 Implement `answer/authority.py`
- [x] 2.4 Confirm no import of `answer/verify.py` from either authority module

## 3. Carry the metadata

- [x] 3.1 Red: ingest with authority metadata → the retrieved candidate carries it
- [x] 3.2 Red: ingest without it → candidate metadata empty (unranked)
- [x] 3.3 Add `authority=` to `CiteNexus.ingest` / `_ingest_url` / `crawl` and
      `IngestPipeline.ingest`; write the `authority_meta` row column
- [x] 3.4 Add `Candidate.authority_meta` and carry the column in the vector,
      lexical and structure retrievers (decoding a missing value to `{}`)

## 4. Wire the flow

- [x] 4.1 Red: strict + floor + only below-floor grounded evidence ⇒ refusal, no
      generator call, reason names insufficient authority
- [x] 4.2 Red: strict + floor + an at-or-above-floor candidate ⇒ that one answers
- [x] 4.3 Red: `authority_tier` / `authority_floor_applied` signals
- [x] 4.4 Add the two additive `EvidenceSignals` fields
- [x] 4.5 Insert the single selection point in `AnswerFlow.ask` between grounding
      and conflict detection; refuse on an empty selection
- [x] 4.6 Add `AuthorityConfig` to the config schema + an `authority=`
      (`AuthorityPolicy`) client injection point, defaulting to `default.v1`
      with no floor
- [x] 4.7 KNOWN NON-COVERAGE: `strategy="deep"` (`AgenticAnswerFlow`) does not
      yet take the policy. The floor covers the strict flow -- the guarantee
      path and the default -- only. Deep-ask follows in its own change.

## 5. Prove compatibility

- [x] 5.1 Full suite green with no test changed for unrelated reasons
- [x] 5.2 `task check` (lint + mypy over src AND tests + pytest)
- [x] 5.3 `spikes/library-stress/stress.py` — all four probes still PASS

## 6. The acceptance test (the point of the work)

- [x] 6.1 Wire `examples/law-authority/authority.csv` into `run.py`'s ingest calls
      and configure the floor
- [x] 6.2 Re-run the live benchmark (real Jina + Gemini) on a clean data dir
- [x] 6.3 Report the before/after table and the out-of-jurisdiction citation count
      (target: zero)
- [x] 6.4 Confirm the known residual: the subject-scope mismatch survives.
      MEASURED: it did NOT survive as a wrong answer in the post-change run --
      but not because authority caught it. `01-ca-civ-1946_1-statute` is
      `controlling-statute`, the TOP tier, so no floor can exclude it. The floor
      removed the Florida/blog chunks from the candidate pool, which changed
      which passages reached the generator, and the faithfulness gate happened to
      reject the result. That is luck, not a fix; the subject-scope gap is
      unchanged and needs its own applicability signal.


## 7. Contradictions found against ADR-0004

- [x] 7.1 ADR-0004 claims "Every existing Result serializes byte-for-byte
      unchanged" while ALSO specifying "additive Result/EvidenceSignals fields".
      Those cannot both hold: two additive fields necessarily appear in the JSON
      dump. Measured: `conformance/cases/result_roundtrip.json` moved by exactly
      +4 lines (the two new fields, at their empty defaults, in both cases).
      Behaviour is unchanged; SERIALIZATION is not. The ADR wording needs the
      correction.
- [x] 7.2 That fixture is a cross-port contract (`golang/result/result_test.go`,
      `js/src/result/result.test.ts` load it). The two additive fields are a
      port follow-up -- out of scope here, as this change is Python-only.
