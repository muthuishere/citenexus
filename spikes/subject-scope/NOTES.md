# SPIKE — the subject-scope gap

**Question.** The ADR-0004 authority floor closed *wrong jurisdiction* (4 → 0 on the
live `examples/law-authority` benchmark). It cannot close *wrong subject scope*:

> **Q** "How much notice must a landlord give to terminate a fixed five-year
> commercial lease with a specified term in California?" — must **abstain**
> **A** "at least 60 days prior to the proposed date of termination"
> cited `01-ca-civ-1946_1-statute`, tier `controlling-statute` — the **highest** tier.

Every existing guard is *correct* here and every one of them passes it. The
faithfulness gate is right: those words are verbatim in that passage. The
authority floor is right: nothing outranks a controlling statute. The statute is
simply about a different **kind** of tenancy.

**What I did.** `spike.py` — offline, deterministic, no network, no keys. It reads
`examples/law-authority/{corpus,golden.csv,authority.csv,results.json}` and rebuilds
the retrieval grid using the library's *own* `TxtExtractor`, `chunk_text`,
`content_tokens`, `has_relevance_overlap` and `is_supported`. It does **not** re-run
the live benchmark.

```bash
cd python && ./.venv/bin/python ../spikes/subject-scope/spike.py   # project env; citenexus needs pydantic
```

---

## M1 — the root cause is measurable, and it is not a scoring problem

`TxtExtractor` splits a `.txt` on blank lines, one paragraph per block; `chunk_text`
then chunks each block *independently*. Every paragraph in this corpus is well under
450 tokens, so **one statutory subdivision = one EvidenceUnit**. 6 documents → 41 EUs.

The precondition that decides whether § 1946.1 applies at all —

> "(a) … a hiring of residential real property **or commercial real property by a
> qualified commercial tenant for a term not specified by the parties** …"

— lives in EU `01-ca-civ-1946_1-statute::2::0`. The operative 60-day rule lives in
`::3::0`. **They are different EvidenceUnits.** Retrieval selected `::3::0`; the
gate saw `::3::0`; the generator saw `::3::0`. Nothing in the pipeline ever saw the
sentence that says this rule does not apply to a lease with a specified term.

| | operative EUs | of which carry their own scope precondition |
|---|---|---|
| `01-ca-civ-1946_1` | 4 | 0 |
| `02-mak-v-berkeley` | 1 | 1 |
| `04-ca-civ-1946` | 1 | 1 |
| `05-nolo-blog` | 1 | 1 |
| `06-florida-83_57` | 4 | 0 |
| **total** | **11** | **3** |

**Applicability severance rate: 8/11 = 73%** of the passages a "how much notice"
question can be answered from are citable in isolation from the clause that governs
whether they apply.

This is the finding that reframes the problem. The scope information *is in the
corpus* — 5 of 6 documents state their term-scope precondition in plain text, and
Florida's is even in its title ("Termination of tenancy without specific term").
It is not missing. It is **severed by chunking**, and every downstream guard is
chunk-local by design.

## M2 — the two rejected approaches, reproduced and confirmed dead

**(2a) query-term relevance floor.** `has_relevance_overlap(BAD_QUESTION, passage)`
→ `True`. The floor is blind to it. Also confirmed: `"california"` does **not**
appear in the statute's body text — only in the corpus author's hand-written
`SOURCE:` header line (which *is* ingested as EU `::0::0`, an accident of this
example, not a property of statutes).

**(2b) content-token coverage.** Computed with the library's own `content_tokens`
over all 12 (answerable question × correct document) pairings, best EU per document:

```
GOOD pairings (n=12):  min 0.29   max 0.80
BAD  commercial-fixed-term × § 1946.1(b) : 0.31   <- inside the good range
BAD  Texas × Florida 83.57               : 0.83   <- ABOVE every good pairing
```

A threshold high enough to block the first loses **2/12** good pairings. A threshold
high enough to block both loses **12/12**. Coverage is not merely non-separating —
on this data it is **anti-correlated**: the single worst answer in the set is the
*best-covered* pairing in the set, because a wrong-jurisdiction statute about the
same topic repeats the query's vocabulary more densely than the right one does.

(My numbers differ from the 0.69/0.83 previously reported — 0.83 reproduces exactly;
0.31 vs 0.69 is a different (answer, EU) pairing for the commercial case. The
conclusion is the same and is if anything stronger: the two bad cases land on
*opposite ends* of the distribution, so no single-sided threshold exists at all.)

## M3 — the candidate: declared scope facets, refusal-only

The shape that worked for authority should work for scope: **curator-declared
metadata, never derived from prose, applied strictly after grounding, able only to
withhold.** A facet is a closed vocabulary declared alongside the corpus — values,
which values are mutually exclusive, and the surface forms by which a *query* may
assert a value. All data. No model. Byte-deterministic.

```
facet tenancy_term : unspecified | specified | any(wildcard)
facet jurisdiction : CA | FL | generic(wildcard)
01-ca-civ-1946_1  -> tenancy_term=unspecified  jurisdiction=CA
06-florida-83_57  -> tenancy_term=unspecified  jurisdiction=FL
```

Gate: if the query asserts value *v* for facet *F* and the source declares an
incompatible *w*, withhold that source. Never admits anything.

Across all 11 golden questions:

| | |
|---|---|
| subject-scope failures caught | **1 / 1** (the commercial fixed-term case) |
| jurisdiction failures caught | 1 (redundant — ADR-0004 already has it) |
| out of reach (missing topic entirely) | 1 (security deposit — no on-topic source exists) |
| **answerable questions lost (regressions)** | **0 / 8** |

So it works, on this corpus, with zero cost to recall. That is the good news.

## M4 — and here is why that number is not the whole truth

Six paraphrases of the same commercial-lease question, none using a declared surface
form:

```
SILENT  The lease runs from 1 January 2026 to 31 December 2030. What notice ends it early?
SILENT  Our shop lease has five years left to run. How long a notice must the landlord serve?
SILENT  How much warning does a landlord owe a business tenant on a lease that expires in 2030?
SILENT  A commercial tenancy was granted for a definite period of 60 months. Notice required?
SILENT  What notice period applies where the parties agreed the tenancy would end on a set date?
SILENT  Le bail commercial de cinq ans se termine le 31 décembre 2030. Quel préavis ?
```

**Fired on 0/6. Fail-open rate 100%.**

I wrote those paraphrases to evade the lexicon, and I say so plainly — this is an
adversarial measurement, not a sampled one. But it is the *right* adversary: in a
legal product the question is phrased by a client, not by the curator who wrote the
vocabulary. A phrase like "expires in 2030" asserts a specified term as clearly as
"fixed-term" does, and no closed vocabulary anticipates all of them. The last line
also shows the multilingual failure: the vocabulary is per-language, and CiteNexus
answers in the query's language.

**A declared-facet gate is a floor, not a guarantee.** It raises the cost of a
wrong-scope answer; it does not make one impossible. Anyone who ships it must not
describe it as closing the class.

## M5 — scope-context propagation

If the root cause is severance, un-sever it: attach the document's applicability
clause to every EU derived from that document.

- 11 operative EUs augmented, **0 over the 450-token chunk budget**.
- `is_supported(answer, passage)` before: `True`; after augmentation: `True`.

Propagation **does not itself refuse anything** — the faithfulness gate is token
containment and containment only grows. What it changes is that
`"not specified by the parties"` becomes *visible* in the passage a scope check, a
judge, or a human reviewer is looking at. Today it is invisible to all three.

**One concrete implementation finding.** `evidence/chunked_builder.py` already has
the seam (`Contextualizer`), but its prefix lands in `EvidenceUnit.text`, and
`Candidate.citable_text` returns `passage`, not `text` — so the generator and the
gate never see it. Contextual retrieval helps *ranking* only. Propagating scope
therefore needs a **new additive field** (`scope_context`) that the generator and a
scope check read and the citation excludes — not a reuse of the contextualizer.

---

## RECOMMENDATION

**No deterministic method closes this class. One deterministic method makes it
visible, and one deterministic method raises a floor over the anticipated cases.
Ship both; document the residue as a known limitation.**

Concretely, in order:

1. **Scope-context propagation (deterministic, always on, ship first).** Carry the
   document/section applicability clause onto every derived EU as an additive
   `scope_context`, shown to the generator and to any scope check, excluded from the
   verbatim citation. Zero vocabulary, zero model, fits the budget, no recall cost.
   It closes nothing on its own — it is the precondition for anything that could.
2. **Declared scope facets + refusal-only floor (deterministic, opt-in).** Exactly
   ADR-0004's seam, one facet dimension further. Measured: 1/1 caught, 0/8
   regressions, 0/6 under paraphrase. Ship it as an opt-in floor, priced honestly.
3. **A scope verdict from a model, as a recorded INPUT to a deterministic rule
   (opt-in).** See the conformance argument below. This is the only thing with a
   chance of catching the M4 paraphrases, and it must not be sold as deterministic.
4. **Document the limitation.** Until (3), CiteNexus guarantees *no ungrounded
   claim*; it does **not** guarantee that a grounded, high-authority citation is
   *on-scope* for the question. That sentence belongs in the docs verbatim.

### On (b) — the ADR-0009 judge as an abstention-only advisory

The tempting argument is: a judge that can only ever *increase* refusals is safe,
because the failure direction is "don't know", which the owner has already ruled
acceptable. **That argument is wrong on the conformance point and right on the
safety point, and the two are different properties.**

The cross-language conformance contract is not "the system is safe." It is
"Python, Rust, Go and JS produce the *same* decision on the same input." A
refusal-only judge still moves the ANSWER/REFUSE boundary as a function of a model
call, so two ports with two model endpoints — or the same port on two days — disagree.
Monotonicity does not rescue that: a contract about *agreement* is broken by any
nondeterminism, in either direction. And a nondeterministic refusal is a real user
harm in this domain, just a quieter one — an evidence system that intermittently
refuses a question it answered yesterday is not auditable, and auditability is the
product.

**The reconciliation is to move the nondeterminism out of the decision function and
into its inputs.** Do not let the judge gate. Let it emit a *scope verdict* — via the
existing two-phase emit-request / host-fulfiller pattern — that is recorded on the
Result, and let a **deterministic** rule consume it: `verdict == out-of-scope ⇒
withhold this candidate`. Then

- the core decision function stays a pure function of (candidates, verdicts, policy),
  so conformance vectors pin the verdicts and every port agrees byte-for-byte;
- the model call stays in the host, where ADR-0006 already puts it, and the key never
  crosses the FFI boundary;
- the refusal is *attributable* — the audit trail says which verdict caused it,
  which "the judge felt uneasy" never could;
- and ADR-0009's rule survives intact, because the judge still never gates. It
  produces evidence; the deterministic rule gates.

This is the same move ADR-0004 made: authority is nondeterministic *knowledge* (a
human's assertion about standing) turned into a deterministic *input* (a tier in a
metadata column). Scope should follow it.

### Rejected

- **(c) cross-encoder / NLI entailment at the selection point** — rejected on two
  grounds. First, direction: NLI would test whether the passage entails the answer,
  which is what the faithfulness gate already tests and already passes. The needed
  test is the reverse — whether the *query's* preconditions are satisfied by the
  passage's scope — and that is not the relation an off-the-shelf NLI model is
  trained on. Second, form: it yields a continuous score, and M2 shows that on this
  data the wrong-scope pairings sit on *both* ends of the score distribution, so a
  threshold is not merely untuned, it is the wrong instrument. A cross-encoder also
  means bundling a model, which the library forbids. If a scope verdict is wanted
  from a model, take it as a discrete verdict through (3), not as a score.
- **Deriving scope from the document's `SOURCE:` header.** It works on this corpus
  (`"california"` is in EU `::0::0` for all four CA documents) and it is a trap: the
  header is prose the example's author typed, not something a PDF of the statute
  would carry. Building on it would produce a spike that passes and a product that
  fails on real inputs.
- **Any further threshold on any existing score** (rerank score, fusion score,
  coverage, distinct-document count). M2 is the general argument, not a tuning
  result: the wrong-scope passage is *genuinely the most topically relevant passage
  in the corpus*. It is supposed to score high. That is what makes this class
  different from noise, and why no monotone function of relevance separates it.

---

## What would make this wrong

- **The corpus is 6 documents, 11 questions, one sub-topic, one legal system.** M3's
  "0 regressions" is 8 questions. It is an existence proof that the shape can work,
  not evidence that it generalises. Nothing here should be quoted as a rate.
- **M4 is adversarial by construction.** I wrote the paraphrases to evade my own
  lexicon. A realistic distribution of client questions would fire somewhere above
  0/6 — I do not know where, and I did not sample one. The honest claim is "a
  lexicon is evadable", not "a lexicon fails 100% of the time".
- **The bad answer is reconstructed, not re-observed.** The committed `results.json`
  is a post-authority-floor run in which this question *refused* — by luck, per the
  brief, because dropping the Florida chunks changed which passages reached the
  generator. I pair `BAD_QUESTION` with the EU and the answer string the live run
  produced for the *sibling* question against the same passage. If the real failing
  run cited a different EU, M1's specific EU ids change; the severance rate (a
  property of the corpus and the chunker) does not.
- **M1 depends on `TxtExtractor`'s paragraph blocking.** A PDF extractor emitting
  page-level blocks would put subdivisions (a) and (b) in the *same* EU and the
  severance would vanish for that document — and reappear the moment a section runs
  past 450 tokens. Severance is a function of extractor granularity, so the 73% is
  specific to plain-text ingest of this corpus.
- **`is_operative` is a regex** (`\d+ days` near `notice|terminat`). It is a proxy
  for "a passage an answer to a notice-period question could be extracted from". It
  will over- and under-count on any other topic.
- **The scope predicates in M1/M5 are hand-identified.** I located them by reading;
  the spike does not claim they can be found automatically. Whether the applicability
  clause is structurally recoverable (first subdivision of a section, a
  `StructureType` node, a heading) is the open engineering question that decides
  whether recommendation (1) is cheap or expensive. I did not measure it.
- **If someone produces a scope-relevance signal that separates on real data**, the
  whole "no deterministic method closes this" conclusion collapses. I claim only
  that lexical overlap, token coverage, authority tier, and any monotone function of
  topical relevance provably do not — measured above.
