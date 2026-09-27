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

## Amendment 2026-09-27 (owner-approved): verbatim numbers, CLDR locales, grouping forms

### Why

An English-declared answer that copies the Dutch amount "€ 4.000" from its
cited Dutch unit was refused: the claim side read "4.000" as English 4.0, the
unit side as Dutch 4000 (rag_go Lex5 L-R20). Reading each side only in its own
declared language is right for a number the writer *formats*; it is wrong for a
number the writer *copies*.

### The rule

1. **A number the claim copies VERBATIM from its cited unit keeps the UNIT's
   locale.** An English claim "€ 4.000" over a Dutch unit containing "€ 4.000"
   is 4000. The match is on the **whole** matched number: the claim number's
   spelling (after the same normalisation `numbersIn` applies — lowering,
   space/apostrophe group joining) must equal the spelling of one of the unit's
   number matches, and the number pattern always takes every digit group, so
   "12" never takes the reading of "12.75" and never of "0,12"; "€ 23" over
   "€ 0,23" stays refused. A spelling the unit itself reads two ways is dropped
   (falls back to rule 2). A dashed amount ("4.000,-") reads the same in every
   locale and is not looked up.
2. **A number the writer formats itself follows the CLAIM's language.** English
   "€4,000" = 4000; English "4.000" that is not in the unit = 4.
3. Values are compared after each side is normalised in its own locale. Units,
   cents, ordinals, dates and clock times are unchanged.

Implementation: `verbatimIn` / `readWith` — Go `golang/answer/numbers.go:220-249`,
Python `python/src/citenexus/answer/numbers.py:316-341` (`verbatim_in`,
`read_with`), JS `js/src/answer/numbers.ts:282-307`. Applied on the **claim side
only**, wherever a claim number is compared to a unit number by key: the number
guard (`golang/answer/verify_guards.go:79`), the unit guard's money rates and
quantities (`verify_guards_model.go:308`), the hedge guard's number anchor
(`verify_hedges.go:248`), the value-row guard (`verify_parties.go:442`), the
pair-value binding (`verify_parties.go:301`), the qualifier-pair guard
(`verify_qualifier_pairs.go:89`), the role guard (`verify_roles.go:321`) and the
conjunct guard's language-free anchor (`verify_conjuncts.go:131`); the Python
and JS guards mirror these one for one. **ADR-0007 conflict detection is not
given the verbatim rule** (two units have no "copied from" direction); it does
see the widened tables and grouping forms below, because it reads numbers
through the same `numbersIn`.

### Locale table (CLDR)

Each entry is the language's decimal separator in CLDR
(`common/main/<locale>.xml`, `numbers/symbols[@numberSystem="latn"]/decimal`),
canonical in `conformance/conflict.json:342-404` and generated for every port by
`python/scripts/gen_conflict_tables.py`.

- **Decimal comma:** bg, cs, da, de, el, es, fi, fr, hr, hu, id, it, nb, nl, nn,
  no, pl, pt, ro, ru, sk, sl, sv, tr, uk, vi — and the region `en-za`.
- **Decimal point:** bn, en, gu, he, hi, ja, kn, ko, ml, mr, ms, ta, te, th,
  zh — and the regions `de-ch`, `de-li`, `it-ch`, `es-mx`, `es-us`, `es-419`,
  whose CLDR decimal differs from their language's.
- A full tag in a table wins over its primary language (`de-CH` reads a point,
  `de` a comma); lookup is `decimalMarkOf` (`golang/answer/numbers.go:96`).
  Nothing was dropped from the owner's list. A language in neither table still
  reads "1.500" as ambiguous (`?1.500`).
- **Indian lakh grouping** ("1,00,000", "12,34,567.89") is read only for
  `lakh_grouping_languages` = bn, en, gu, hi, kn, ml, mr, ta, te
  (`conformance/conflict.json:394`, `golang/answer/numbers.go:84,112`). In any
  other language it stays unread.

### Grouping forms (`joinSpacedThousands`, `golang/answer/numbers.go:383-431`)

- Space grouping (plain, U+00A0, U+202F) of **any** digit run — "1 234,56" —
  only when the declared language is a decimal-comma language; money-only
  otherwise, as before.
- Apostrophe grouping (' or U+2019) — "1'234.50" — in every language: an
  apostrophe is a decimal mark nowhere.
- Both require 1-3 leading digits and exact three-digit groups; a run touching a
  digit, letter or number mark, or followed by a further separator and digit
  ("1 234 56"), is left as written — several numbers, never a guess.

### Flipped vectors and tests

No existing `conformance/cases/verify_answer.json` case flipped (325 → 346; the
21 new cases are `verbatim/*` and `locale/*`, each admit paired with a
must-refuse control). Flipped, deliberately:

- `conformance/cases/conflict.json` `number_readings`: `("1.500", "de")`
  `?1.500` → `1500` (de is now declared); an unknown-language vector
  `("1.500", "xx")` → `?1.500` keeps the old point. 30 → 46 readings.
- `TestNumberFormsInRunningText` (Go) and its Python/JS mirrors: "en claim
  writes the dutch amount", "… before euro", "nl claim writes the english
  amount" — refused → **admitted**; "en-declared 4.000 outside money stays
  ambiguous" — refused → **admitted** (the "4.000" is copied from the unit, so
  it keeps the Dutch reading), with a new control where the unit writes "4000"
  and the claim's "4.000" is refused.
- `TestNumberGuardReadsEachSideInItsLanguage` and mirrors: "The budget is
  €1.500." (en) over "Het budget is € 1.500." (nl) — refused → **admitted**; a
  new control over "€ 1500" stays refused.
