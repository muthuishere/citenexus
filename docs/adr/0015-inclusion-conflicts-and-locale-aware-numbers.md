# 0015 — Inclusion conflicts and locale-aware numbers

Status: accepted · 2026-09-24 (owner decision, relayed from the rag_go consumer)

Amends ADR-0007. Python is the reference
(`python/src/citenexus/answer/numbers.py`, `answer/conflict.py`); Go
(`golang/answer/numbers.go`, `conflict.go`) and JS port it, pinned by the
`inclusion`, `number_formats` and `number_readings` buckets of
`conformance/cases/conflict.json`.

## Context

Two gaps surfaced when the Dutch tables landed (`feat/nl-tables`), on a Dutch HR
corpus that serves a legal client, where the target error rate is near zero: no
wrong claim admitted, as few true claims dropped as possible.

1. **incl/excl was invisible.** R-119 (adopted HR-FAQ: "€ 25 exclusief btw per
   maand") and R-120 (a proposal note: "€ 25 inclusief btw per maand") disagree,
   and the detector said nothing. Admitting `inclusief`/`exclusief` as an
   ANTONYM pair was measured and rejected: the antonym rule ignores numbers, so
   the both-true pair "€ 100 exclusief btw" / "€ 121 inclusief btw" became a
   false conflict (Dutch hard-negative rate 0/12 → 2/12).
2. **Numbers were read as English.** `_NUMBER_RE` stripped every comma and read
   a dot as a decimal point, so "€ 1.500" read as 1.5 and "€ 25,00" as 2500. The
   same amount written two ways was a VALUE conflict, which in `VerifyAnswer`
   drops a true claim.

A blanket "numbers differ, so decline" rule was proposed in the harness and
would have fixed (1). It is rejected here: it fails open. "€ 100 exclusief btw"
vs "€ 150 inclusief btw" would stop being a conflict, and nothing would say so.

## Decision

### Inclusion rule

A new rule, `inclusion`, runs after the reported-speech guard and before the
antonym rule. It fires when one passage carries the inclusive and the other the
exclusive word of a tabled pair (`inclusion_pairs`: incl/excl,
inclusief/exclusief, including/excluding, inclusive/exclusive), on the same
subject, with the usual `MAX_RESIDUAL` bound on everything else. It owns its
verdict:

| Amounts | Verdict |
|---|---|
| equal (or none on either side) | **conflict** — the price cannot be both |
| different, a VAT marker (`btw`, `vat`) present, exactly one amount differs per side, both read to a single value, and `excl × rate` is within €0.01 of `incl` for a tabled rate (1.21, 1.09) | **no conflict** — one price quoted both ways |
| any other difference | **conflict** |

The decline is returned from the rule itself, so a VAT-consistent pair is not
then called a `value` conflict for carrying two amounts. VAT arithmetic is exact
(Python `Fraction`, Go `big.Rat`, JS scaled `BigInt`); rates are decimal strings
in the table, never floats.

### Locale-aware numbers

A number is read to a single value only when its form, or the passage's
DECLARED language, leaves one reading:

- plain digits; `25,-` (Dutch whole amount);
- both separators (the last is the decimal mark): `1.500,50` = `1,500.50`;
- a repeated separator (thousands): `1.000.000`;
- one separator not followed by exactly three digits, or with a leading part
  that cannot open a thousands group (`25,50`, `1,5`, `1.5`, `0.500`,
  `1234.567`): a decimal mark in every locale.

`1.500` / `1,500` is read only when the language is declared
(`decimal_comma_languages: ["nl"]`, `decimal_point_languages: ["en"]`).
Otherwise its key is its raw spelling prefixed `?`, equal to nothing but the same
spelling. **Ambiguity never declares two amounts equal**, because a false
"equal" hides a conflict (fails open) while a false "different" only costs an
abstention (fails closed).

`detect_conflict`, `is_near_duplicate`, `find_conflicts` and
`collapse_near_duplicates` take the passages' declared languages (keyword
arguments in Python, `…WithLanguages` variants in Go). The ask paths pass the
candidates' own languages; the one-argument forms read every passage as
undeclared.

## Consequences

- R-119/R-120 is a conflict. Untiered, the claim abstains citing both sides;
  tiered at ingest (the consumer's job, ADR-0004), the adopted FAQ outranks the
  proposal note (`golang/answer/verify_answer_test.go`
  `TestR119R120InclExclBtw`).
- The Dutch number false conflicts are gone **for declared passages**.
- **Regression, accepted:** an undeclared corpus that writes the same amount as
  `1,500` in one passage and `1500` in another now gets a value conflict (a
  false abstention). The old reader equated them by assuming English. Declare
  the language to get the equality back.
- A passage in a language in neither table (e.g. `de`) reads `1.500` as
  ambiguous. Adding a language is a table change that needs fixtures of its own.
- `1,5` and `1.5` are equal in every locale (neither can be a thousands group).
  The consumer's brief listed this pair as ambiguous; it is not, and it is
  fixtured as equal.
- Known gap, not addressed: negated relative clauses ("Medewerkers die (geen)
  lid zijn … ontvangen een toeslag") still produce a false `negation` conflict,
  in English and Dutch.
