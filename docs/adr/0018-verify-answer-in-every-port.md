# 0018 — VerifyAnswer in every port; the vectors are the contract

Status: accepted · 2026-09-26 · ships in 0.13.0

Supersedes the **"Go-only"** consequence of ADR-0016. Everything else in
ADR-0016 (the verb, the citation contract, admission order, what the model
cannot override, partial answers, wire additions) stands and now holds in all
three ports.

## Context

ADR-0016 shipped `VerifyAnswer` in Go only, on purpose: build fast in Go against
a real consumer (rag_go, Dutch HR corpus serving a legal client), and port only
once the consumer confirmed it. Between ADR-0016 (`c7b8de9`) and this ADR the Go
verb grew from four guards to the full set — condition, exclusion, hedge,
definition/subtype, role/relation/argument, party and value-row, qualifier and
verb pairs, conjunct presence, the list-union rule, the heading check, the
prepared glossary — and its vectors from 185 to 325. rag_go measured it round by
round (latest pin `verify-round7b/2026-09-25` = `9728d20`).

The ADR-0016 vectors lived in `golang/answer/testdata/`, "Go-owned until a
Python reference exists". Leaving the verb Go-only would leave the Python
facade — the reference — unable to check a caller-generated answer at all.

## Decision

1. **`VerifyAnswer` and the heading check ship in Python and JS**, ported from Go
   at `7936048`:
   - Python: `citenexus.verify_answer(answer, evidence, options=None) -> Result`
     (`python/src/citenexus/answer/verify_answer.py:578`, exported at
     `python/src/citenexus/__init__.py:18`); `VerifyOptions` (`:140`),
     `EvidenceUnit` (`:107`, reached as `citenexus.answer.EvidenceUnit` — the
     top-level `EvidenceUnit` name stays the ingestion type).
   - JS: `verifyAnswer(answer, evidence, options?) -> Promise<Result>`
     (`js/src/answer/verify-answer.ts:497`, exported from `js/src/index.ts:51`);
     the evidence type is exported as `VerifyEvidenceUnit`, because the root
     already exports vision's `EvidenceUnit`.
   - Go: unchanged, `answer.VerifyAnswer` (`golang/answer/verify_answer.go:610`).
2. **`SupportChecker` is a published contract in every port**: Go
   `contracts.SupportChecker` (`golang/contracts/support.go:23`), Python
   `citenexus.SupportChecker` (`python/src/citenexus/contracts.py:178`,
   synchronous like the other Protocols, returns `(entailed, contradicted)`), JS
   `SupportChecker` (`js/src/contracts.ts:122`, may return a promise).
3. **The vectors moved to `conformance/cases/verify_answer.json` (325) and
   `conformance/cases/heading_check.json` (14)** and are run by all three ports
   with the same count assertion: `golang/answer/verify_answer_conformance_test.go`,
   `python/tests/conformance/test_verify_answer_vectors.py`,
   `js/src/answer/verify-answer-conformance.test.ts`. A change to the verb in any
   port lands with vectors here, or it does not land.
4. **The workflow that produced this stays the rule for consumer-driven
   features:** build in Go against the consumer → the consumer confirms → ADR →
   port Python and JS against shared vectors → only then merge, version, publish.
5. **JS gains authority selection** (`js/src/authority/authority.ts`, ported from
   `golang/authority/`); ADR-0016 recorded that JS had none.

## Evidence of parity (beyond the vectors)

The vectors assert the decision and each claim's reason *prefix*. Both port
agents also ran the real Go `VerifyAnswer` and diffed the **full `Result` JSON**
(every field, full reason strings):

- Python: ~29,000 inputs (the vectors, each re-run with the model path forced,
  headings, randomly mixed answer/evidence/glossary pairs) — 0 mismatches.
- JS: the 339 vectors identical including field order, plus ~45,000 generated
  inputs (option combinations, mutated claims, Unicode spaces, İ/Σ, Markdown,
  dates, clock times, money) — identical after two JS-side fixes found by the
  fuzz and pinned as regression tests.

These were single scratchpad runs, not committed harnesses; the committed
guarantee is the 325 + 14 vectors.

## Consequences

- **Conflict detection reads numbers through the running-text reader in all three
  ports** (`numbers_in` / `numbersIn`), so `"€ 4 000"` is 4000 in the ADR-0007
  detector too, not only in the number guard. `conflict.json` is unchanged and
  green in every port. This is a behaviour change → minor version.
- **Go reads some tables in map order, which can vary between runs** (found by
  the ports; Python and JS pick a deterministic order, so on these inputs a port
  can differ from a given Go run):
  - verdict can differ: a term registered under two actor ids
    (`golang/answer/verify_roles.go:157-160`, `verify_parties.go:180`), e.g.
    `DefaultActorLexicon.With("employer", "manager")`;
  - reason text only: `verify_parties.go:486-499` (tied smallest value),
    `verify_qualifier_pairs.go:103,114`, `heading.go:193-203` (undeclared
    language). Open — fix in Go by sorting, with a vector, then re-run the ports.
- **Not ported:** Go's `ctx` cancellation (the Python/JS checker gets none); Go's
  cross-call glossary cache (Python and JS prepare per call unless
  `glossary_prepared` / `glossaryPrepared` is passed); Go benchmarks and the
  race-only allocation bound.
- **The gate path now runs the number guard** (`golang/answer/verify_answer.go:766`,
  `7936048`, ported): the tokenizer splits `"0,23"` into 0 and 23, so before it
  `"€ 23"` was admitted by "gate" over `"€ 0,23"`. rag_go replayed 2,187 recorded
  claims: 0 new refusals once its own probe stopped blanking decimal points
  (rag_go `4a7580680`); no recorded draft had the leak shape, so this closes a
  leak class the consumer has not yet hit.
- **Still open, unchanged by this ADR:** ADR-0015's cross-locale rule — an
  English-declared claim writing the Dutch `"€ 4.000"` reads as 4.0 and is
  refused (pinned by `golang/answer/verify_number_forms_test.go`). An amendment
  (a number copied verbatim from its cited unit keeps that unit's locale) is with
  the owner.
