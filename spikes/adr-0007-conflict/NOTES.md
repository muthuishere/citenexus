# Spike — ADR-0007 deterministic conflict detection + near-duplicate collapse

Date: 2026-08-11 · Validates ADR-0007, placed per ADR-0010 · Feeds from
`spikes/library-stress/` probes B and C.

Run: `cd python && uv run python ../spikes/adr-0007-conflict/spike.py`
(exit 0 = hard-negative FP rate within budget and every near-duplicate case correct)

## Verdict

**Deterministic conflict detection is viable at a shippable false-positive rate —
but only because the rules are built to *decline*, not to *decide*.** ADR-0007
stands as written, with three amendments below.

| metric | result |
|---|---|
| **FP rate on hard negatives** | **0.000 (0/27)** ← the number that decides this |
| FP rate on unrelated pairs | 0.000 (0/22) |
| precision | 1.000 |
| recall | 0.889 (24/27) |
| **held-out** FP (10 hard negatives written after thresholds froze) | **0.000 (0/10)** |
| held-out recall (5 true conflicts) | 0.800 (4/5) |

Fixtures: 27 true conflicts / 27 hard negatives / 22 unrelated, spread over
legal, finance, medical, operations, physics. Hard-negative FP is 0 in **all
five domains** independently.

The model that ADR-0007 rejected for v1 is not needed for the *detection* the
ADR actually specifies. It would be needed for a detector aiming at high recall,
which this deliberately is not.

## Why the FP rate is the whole game, and what actually holds it down

Strict mode abstains on a detected conflict, so a false conflict is a false
refusal. Recall failures are free (the library behaves exactly as it does today);
precision failures are not.

The design that produces 0 FP is **one guard, not the marker table**:

> a conflict requires that after removing the polarity signal itself, the two
> passages have **≤ 1 remaining content-token of divergence** (`max_residual`).

Two passages that disagree genuinely are otherwise word-identical. Two passages
that merely *look* like they disagree differ in some other content word — the
scope (`adults`/`children`), the route (`oral`/`intravenous`), the environment
(`staging`/`production`), the condition (`heated`/`cooled`), the metric
(`p50`/`p99`). That residual word is what makes them complementary, and requiring
it to be absent kills the entire hard-negative class in one rule.

The sensitivity table is unambiguous about this:

```
residual  recall  FP-hard
  0        0.89    0.00
  1        0.89    0.00
  2        0.93    0.15     <- +4pp recall costs 15pp false abstention
  3        0.93    0.19
```

Relaxing the residual guard by one token buys 4 points of recall and costs
**15 points of false abstention**. That trade must never be taken. `max_residual`
belongs in the conformance vectors as a pinned constant, not as a tunable.

Secondary guards, in order of load-bearing-ness:

1. **residual ≤ 1** — does ~all the work (above).
2. **measurement vs identifier tokenization** — a digit-*leading* token (`500mg`,
   `2019`) is a value and goes to the numeric rule; a letter-leading token
   containing digits (`p50`, `ipv4`, `sec4`) is an **identifier and must stay in
   the content set**. Before this fix, `p50 latency budget is 200 ms` vs
   `p99 latency budget is 900 ms` was the spike's only false conflict — the digit
   filter had eaten the one word that distinguished them. This is a real trap for
   the Go/JS ports and needs its own conformance vector.
3. **unit-set equality** — a numeric conflict requires both sides to carry the
   same unit tokens, so `1 g` vs `1000 mg` and `2 hours` vs `120 minutes` are
   suppressed without the detector knowing any conversion factors.
4. **numeric subset ⇒ elaboration** — `500 mg` vs `between 250 mg and 500 mg`,
   `4.2 million` vs `4.2 million, up from 3.1 million`.
5. **report markers** — `The claim that the device is not compliant was rejected`
   vs `The device is compliant` (quoted negation).
6. **scope markers** — turned out to be **redundant** in this fixture set:
   deleting the entire scope table changed nothing, because the residual guard
   already caught every case. Reported honestly below; it may still earn its
   keep on longer passages.

## PART 1 — recall limits (all in the safe direction)

Three true conflicts are missed, and each names a real limitation:

- **`The claim for indemnity is valid` / `... is not valid`** — suppressed by the
  `report_markers` guard, because legal English uses "claim" as a noun of art. The
  quoted-negation guard and legal vocabulary collide head-on. Amendment: `claim`
  must come out of the English `report_markers` list and the guard must be
  narrowed to *complementizer* forms (`claim that`, `allegation that`) — a bigram,
  not a unigram. That is still tier-1 regex work, no Unicode required.
- **`Like charges attract` / `... repel`** — the table has `attracts`/`repels`,
  not the bare forms. There is **no stemmer** in the pinned tokenizer, so every
  antonym must be listed in every inflection. This is a permanent maintenance
  cost of tier 2 and the honest reason the table stays English-only for a while.
- **`The reaction conserves momentum` / `does not conserve momentum`** — negation
  asymmetry is correct, but `conserves` vs `conserve` is a residual divergence of
  1... plus the auxiliary shift, and morphology defeats the guard. Same root cause.
- Held-out: **`The recall was issued in 2022` / `... in 2024`** is missed because
  the content set (`recall`, `issued`) is below `min_content=3`. Very short
  passages are not comparable. Acceptable; EUs are usually longer.

None of these produce a wrong answer. They produce today's behaviour.

## PART 2 — near-duplicate collapse

All nine cases behave correctly. Probe C's scenario resolves: one sentence under
five document IDs collapses `distinct_documents` **5 → 1**, and a set of four
mirrors plus one genuinely independent restatement collapses to **2**.

| case | collapses | correct |
|---|---|---|
| exact duplicate | yes | ✅ |
| whitespace / punctuation / case variant | yes | ✅ |
| one word changed (synonym: shall→must) | yes | ✅ |
| one word changed (**value**: 30→60 days) | no — routed to conflict | ✅ |
| one word changed (**negation** inserted) | no — routed to conflict | ✅ |
| genuine independent restatement | no | ✅ |
| word-order paraphrase of the same source | no | ⚠️ see below |

Order matters and is not arbitrary: **conflict is checked first**. A one-word
change is a duplicate only if that word is not a value and not a polarity marker.
Getting this backwards would collapse a contradiction into a corroboration —
the worst possible outcome of this change.

### The undecidable part, stated plainly

**"Same fact restated in different words" cannot be separated from "the same
source paraphrased" deterministically, and no amount of table work fixes it.**
Both are semantic equivalence with lexical divergence; a token-overlap detector
sees one signal and there are two causes. Worse, the distinction the caller
actually wants — *independent* corroboration — is a fact about **provenance, not
text**. Two genuinely independent auditors can write the same sentence; one
source can be quoted in twenty documents in twenty phrasings.

So the collapse rule is deliberately biased to **under-collapse**: it fires only
on surface clones (identical token sequence, or Jaccard ≥ 0.80 with equal length,
equal numbers, equal negation parity). The word-order paraphrase above is *not*
collapsed, and that is recorded as a known miss rather than chased. Under-collapse
leaves `distinct_documents` merely as inflated as it is today; over-collapse would
under-report real corroboration, which is a new wrong signal.

**Recommendation for ADR-0007:** state that near-duplicate collapse is a
*surface-clone* collapse and does not claim to measure evidential independence.
The honest long-term fix is provenance-level (checksum / same source artifact /
ADR-0008 manifest lineage), not textual.

## PART 3 — the polarity marker table (tier 2) and what a bad one costs

Draft at `spikes/adr-0007-conflict/polarity.draft.json`, shaped as
`conformance/polarity.json` would be: `{languages: {en: {negations, antonyms,
report_markers, scope_markers}}}`, tokens in post-`tokenize()` form. Dutch is
drafted and explicitly marked **must not ship** — I can write plausible Dutch
markers, I cannot validate them, and the ADR already requires a golden fixture
per language before that language's markers ship. That requirement is correct and
this spike is evidence for it.

Measured by deliberately corrupting the table and re-running:

| table | recall | **FP-hard (= false abstention)** |
|---|---|---|
| clean (shipped) | 0.89 | **0.00** |
| + hedges as negations (`except`, `unless`, `however`, `although`) | 0.89 | **0.04** |
| + plausible-but-wrong antonyms (`oral`/`intravenous`, `staging`/`production`, `heated`/`cooled`) | 0.89 | **0.07** |
| − scope markers removed entirely | 0.89 | 0.00 |
| − report markers removed | 0.93 | 0.00 |
| all of the above | 0.93 | **0.11** |

Findings:

- **A bad marker table raises false abstention and never lowers it, and it costs
  nothing in recall** — so the failure is silent. There is no metric inside the
  detector that gets worse when the table gets worse; only refusals go up.
- **The dangerous corruption is over-inclusion, and specifically wrong
  *antonyms*.** Four plausible-looking pairs an author might genuinely add took FP
  from 0% to 7%. `oral`/`intravenous` and `staging`/`production` look like
  opposites and are actually *scope distinctions* — exactly the class the residual
  guard exists to protect, defeated by promoting them into the polarity table.
- **Scope-restrictors are not negations.** `except`/`exempt` were kept out of the
  shipped `negations` list on purpose; putting them back costs 4pp of false
  abstention on one fixture (`All employees except contractors receive the
  allowance` vs `All employees receive the allowance`). Any per-language table
  will face this same category error.
- The `scope_markers` list is currently **inert** — deleting it changes nothing,
  because the residual guard subsumes it on short passages. Keep it (cheap
  insurance for multi-clause EUs) but do not credit it with the FP rate.

**Governance consequence:** `conformance/polarity.json` needs a rule that a
marker table change ships with hard-negative fixtures *for that language*, and
that CI reports the hard-negative FP rate as a first-class number. A table is not
a word list; it is a false-abstention budget.

## Placement (ADR-0010)

Confirms the ADR-0010 table with no changes:

- **Pairwise conflict scoring → tier 1**, native in each port. Every operation is
  set arithmetic plus `[0-9][0-9,]*(\.[0-9]+)?` — no lookaround, no
  backreferences, RE2-clean. The one non-regex step (rejecting a digit run glued
  to preceding letters) is a character check in code precisely so the regex stays
  RE2-portable. No Unicode competence required; **no tier-3 case**.
- **Polarity markers → tier 2**, canonical JSON generated into each port.
- Note the spike reads `conformance/stopwords.json` directly rather than the
  hardcoded `answer/verify.py` frozenset, per ADR-0010's pending conversion.

## Amendments ADR-0007 should absorb

1. **Name `max_residual ≤ 1` in the Decision**, not just "high content-token
   overlap". Overlap alone does not produce this FP rate; the residual guard does,
   and the sensitivity data shows relaxing it is a 15pp mistake.
2. **`report_markers` must be bigram-scoped** (`claim that`), not unigram —
   otherwise the guard silently disables conflict detection across most legal
   text, which is a headline domain for this library.
3. **Near-duplicate collapse claims surface clones only**, and does not claim to
   measure evidential independence. That is a provenance question (ADR-0008),
   stated as a known limit rather than left to be discovered.

## Honest limits of this spike

- 91 fixtures is not coverage. It is enough to reject a design (it did not) and
  not enough to certify one.
- Three parameters (`subject_overlap`, the measurement/identifier tokenization
  rule, the duplicate Jaccard threshold) were changed in response to failures on
  the main fixture sets, so those sets are training data. The 15 held-out pairs
  were written afterwards and never tuned against — 0/10 FP, 4/5 recall — which is
  a real but small generalisation signal, not a guarantee.
- All fixtures are single-sentence, English, and synthetic. Real EUs are longer
  and multi-clause, where content-token overlap is a weaker subject proxy and the
  residual guard will fire far less often — the likely real-world effect is
  **lower recall**, i.e. the safe direction, but this is untested and should be
  re-measured against `examples/law-authority` before ADR-0007 is applied.
- No multilingual evidence at all. The Dutch table in the draft is unvalidated
  and is included to show the shape, not to be shipped.
- Only pairs were scored. The ADR's O(k²) over top-k also needs a decision on how
  *many* detected pairs constitute "the conflict touches the answer's own claim" —
  out of scope here.
