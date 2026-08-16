## Context

`Result` declares the shape of conflict surfacing and nothing fills it. SPEC-v6
§11 lists conflict surfacing as part of `answer-flow-strict`; the contract
shipped, the logic never did.

This is not the authority problem (ADR-0004). Authority asks *which source has
standing*; conflict asks *do these grounded sources disagree at all*. Authority
can only resolve a conflict once something has detected one, and in plenty of
corpora both sides carry equal authority, where the correct output is to surface
both rather than pick.

`spikes/adr-0007-conflict/` prototyped and measured the detector before any
production code was written. This design follows the spike; where the spike
contradicted ADR-0007, it follows the spike, and the two places where the
implementation goes beyond the spike are recorded below with their measurements.

Constraints: pure, deterministic, offline (the conformance suite must pin it); no
model on the answer path; RE2-clean so it ports to Go and JS unchanged.

## Goals / Non-Goals

**Goals:**

- Detect that two grounded passages disagree, at a false-conflict rate near zero.
- Surface both sides, and let TrustMode decide whether that is answerable.
- Stop `distinct_documents` from counting mirrors as independent corroboration.

**Non-Goals:**

- **Resolving conflicts.** Never. Picking a winner by recency, authority or score
  is a policy decision belonging to the caller and to ADR-0004. A library that
  silently picks is today's bug with more machinery.
- Cross-corpus contradiction. Only same-query candidates are compared.
- Model-judged semantic contradiction — non-deterministic, un-pinnable by the
  conformance suite, and it puts a model in the path of a guarantee. It stays
  available later behind the ADR-0009 judge seam.
- Measuring evidential *independence*. See the duplicate-collapse decision.
- Any change to `answer/verify.py`. The faithfulness gate stays byte-identical.

## Decisions

### The false-conflict rate is the only metric that matters

In strict mode a detected conflict abstains, so a **false conflict is a false
refusal**. A missed conflict costs nothing new — the library behaves exactly as
it does today. A detector at 100% recall and 20% false positives is unusable; one
at 60% recall and ~0% false positives is shippable. Every rule is therefore built
to decline rather than decide, and recall is reported, never optimised.

Measured on this implementation, over the spike's fixtures ported verbatim into
`tests/answer/test_conflict.py`:

| set | n | result |
|---|---|---|
| **hard negatives (look like conflicts, aren't)** | 27 | **0 false conflicts** |
| unrelated pairs | 22 | 0 false conflicts |
| **held-out negatives** (written after thresholds froze) | 10 | **0 false conflicts** |
| true conflicts | 27 | 27 detected |
| held-out true conflicts | 5 | 4 detected |

Hard-negative false conflicts are 0 in all five domains independently.

### `max_residual ≤ 1` is the guard that holds the rate down — not token overlap

High content-token overlap says "same subject". It does not separate a
contradiction from a complement. The guard that does is:

> after removing the polarity signal itself, the two passages may differ by at
> most **one** remaining content token.

Two passages that genuinely disagree are otherwise word-identical. Two that
merely look like they disagree differ by exactly one further content word — the
scope (`adults`/`children`), the route (`oral`/`intravenous`), the environment
(`staging`/`production`), the metric (`p50`/`p99`) — and that word is what makes
them complementary. The spike's sweep:

```
residual  recall  false-conflict rate
  0        0.89   0.00
  1        0.89   0.00
  2        0.93   0.15   <- +4pp recall costs 15pp FALSE ABSTENTION
  3        0.93   0.19
```

`MAX_RESIDUAL` is a pinned module constant, not a caller parameter, and it is
emitted into `conformance/conflict.json` as data so a port cannot quietly relax
it.

### Digit-LEADING is a value; letter-leading-with-digits is an identifier

`500mg` and `2019` are measurements and belong to the numeric rule. `p50`, `ipv4`
and `sec4` are **identifiers** and must stay in the content set — they are
frequently the only word distinguishing two passages. Getting this backwards
produced the spike's single false conflict. It has its own conformance vector and
its own test, because it is the trap most likely to be re-introduced by a port.

The boundary check (a digit run glued to preceding letters) is done in code, not
regex, precisely so the pattern stays RE2-portable.

### Report markers are BIGRAMS

`The claim that the device is not compliant was rejected` carries a negation that
belongs to a third party. But as a *unigram*, `claim` silently disables conflict
detection across most legal text, where it is a noun of art — the spike lost a
true conflict (`The claim for indemnity is / is not valid`) to exactly that. Only
the complementizer form (`claim that`, `allegation that`) introduces reported
speech, so the table stores bigrams and the scan walks adjacent token pairs.

### One polarity asset, used twice

`CONFLICT_NEGATIONS` is *derived* from `POLARITY_MARKERS` — the ADR-0009 table —
minus four scope restrictors (`except`, `excluding`, `unless`, `other`), plus a
handful of forms the faithfulness gate has no use for. There is no second
polarity table to drift.

The subtraction is measured, not stylistic. Those four restrict a claim's SCOPE;
they do not flip its polarity. For the faithfulness gate the distinction does not
matter (deleting them still changes meaning). For conflict detection, treating
them as negations takes the hard-negative false-conflict rate from 0.00 to 0.04 —
`All employees except contractors receive the allowance` does not contradict
`All employees receive the allowance`.

The dangerous corruption is over-inclusion, and specifically wrong *antonyms*:
four plausible-looking additions (`oral`/`intravenous`, `staging`/`production`,
`heated`/`cooled`, `backups`/`snapshots`) took the rate from 0.00 to 0.07, because
they are scope distinctions wearing an antonym's clothes.

### A bad table fails SILENTLY, so the golden-fixture rule is load-bearing

Corrupting the tables raises false abstention and leaves recall flat. **No metric
inside the detector degrades when the data gets worse — only refusals go up.** A
language may not be claimed until it has hard-negative fixtures of its own, and
CI must report the hard-negative false-conflict rate as a first-class number. A
marker table is not a word list; it is a false-abstention budget. English only.

### Two amendments beyond the spike, each measured

1. **A plural fold inside the comparison.** The spike missed three true conflicts
   to morphology alone (`conserves`/`conserve`, `attract`/`attracts`,
   `requires`/`require`), where a token pair that is *not* a divergence counted as
   one and blew the residual guard. A single rule — drop one trailing `s`, never
   on short tokens, never after `s`/`u`/`i` — fixes all three. It runs inside
   `conflict.py` only: the pinned SPEC-PORTS-v1 tokenizer still does no stemming
   and no other gate sees the fold. Re-measured: recall 0.926 → 1.000 on the
   training set with the hard-negative rate unchanged at **0.000**. It is
   deliberately not a stemmer — a stemmer merges genuinely different words, and
   every such merge is a false conflict.
2. **Bigram report markers** (above), which recovered the legal true conflict the
   spike listed as a known miss.

Both amendments move recall up and leave the false-conflict rate at zero on all
three negative sets, including the held-out one.

### Conflict is checked BEFORE duplicate collapse

A one-word change is a duplicate only when that word is neither a value nor a
polarity marker. Reversing the order would collapse a contradiction into a
corroboration — the worst outcome this change could produce. `is_near_duplicate`
calls `detect_conflict` first and returns `None` on any hit.

### Near-duplicate collapse claims surface clones, and says so

"The same fact restated" and "the same source paraphrased" cannot be separated
deterministically: both are semantic equivalence with lexical divergence, so a
textual detector sees one signal with two causes. Worse, what a caller wants from
`distinct_documents` — *independent* corroboration — is a fact about **provenance,
not text**. Two independent auditors can write the same sentence; one source can
be quoted in twenty documents in twenty phrasings.

So collapse fires only on surface clones (identical token sequence, or Jaccard
≥ 0.80 at equal length with equal numbers and equal negation parity), and is
biased to **under**-collapse. A word-order paraphrase is left standing and
recorded as a known miss. Under-collapsing leaves `distinct_documents` as
inflated as it is today; over-collapsing would under-report real corroboration,
which is a *new* wrong signal. The honest long-term fix is provenance-level
(checksum, same source artifact, ADR-0008 manifest lineage), not textual.

### "Touching the answer's own claim" = the cited passage is one side of the pair

The spike left this open. The definition chosen is the crispest deterministic
one: strict mode abstains when a detected pair contains the passage the answer
cites (on the deep path, any EU cited by a surviving claim). A conflict elsewhere
in the candidate pool is counted and reported but does not block an answer that
does not depend on it.

Detection itself runs before generation, as ADR-0007 specifies; only the
trust-mode coupling is applied afterwards, because "touches the answer's claim"
is not knowable until the answer exists.

### The strict abstention cites both sides

A refusal that hides the evidence is only marginally better than a confident
pick: the caller can neither check the reasoning nor resolve the conflict
themselves. The abstention Result carries both passages verbatim as `sources`,
the conflict description in `conflicts`, and `decision=refused`.

## Risks / Trade-offs

- **Strict mode refuses where it previously answered.** Intended. Stronger
  abstention, never weaker, and a defensible "these disagree, here are both"
  beats an indefensible confident pick.
- **All fixtures are single-sentence, English and synthetic.** 91 fixtures is
  enough to reject a design and not enough to certify one. Real Evidence Units are
  longer and multi-clause, where content-token overlap is a weaker subject proxy
  and the residual guard fires far less often. The likely real-world effect is
  **lower recall** — the safe direction — but it is untested and should be
  re-measured against `examples/law-authority`.
- **No multilingual evidence at all.** The tables are English-only and the
  golden-fixture rule is the only thing preventing an unvalidated language from
  shipping false abstention.
- **`CONFLICT_SCOPE_MARKERS` is currently inert.** Deleting it changed no verdict;
  the residual guard subsumes it on short passages. Kept as cheap insurance for
  multi-clause EUs and explicitly not credited with the measured rate.
- O(k²) over the post-fusion top-k with k = 6 is negligible. Duplicate collapse is
  O(n²) over the grounded set, which is retrieval's top-k.

## Migration Plan

Additive. No `Result` shape change, no API change, no data migration. Callers on
`strict` may see new refusals on corpora containing contradictions, and lower
`distinct_documents` on corpora containing mirrors; both are corrections of
signals that were previously wrong.

## Open Questions

- Should `conflicts` be structured (both EU ids, rule, both values) rather than a
  string tuple? That is a `Result` shape change and is deliberately deferred.
- Should a conflict *within* the collapse window feed authority (ADR-0004) once
  that lands, so a caller can opt into "prefer the later document"?
- Does the residual guard survive multi-clause Evidence Units, or does recall
  collapse to near zero on real corpora?
