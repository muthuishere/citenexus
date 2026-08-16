# 0012 — Subject scope: applicability travels with the evidence

Status: proposed · 2026-08-16

## Context

ADR-0004 closed **wrong jurisdiction**: on the live `examples/law-authority`
benchmark, out-of-jurisdiction citations went 4 → 0 and `abstain_when_no_evidence`
reached 100%. A second class of wrong-but-cited answer survives it untouched:

> **Q** "How much notice must a landlord give to terminate a fixed five-year
> commercial lease with a specified term in California?" — must **abstain**
> **A** "at least 60 days prior to the proposed date of termination"
> citing `01-ca-civ-1946_1-statute`, tier `controlling-statute`.

Every guard in the library is correct here and every one of them passes it. The
faithfulness gate (`answer/verify.py`) is right — the words are verbatim in that
passage. The authority floor (`answer/authority.py`) is right — nothing outranks a
controlling statute, so no floor can ever exclude it. The statute is simply about a
different **kind of tenancy**. Grounding proves *provenance*; ADR-0004 added
*standing*; neither is *applicability*.

Two content-derived fixes were measured and rejected before this ADR:

1. a query-term relevance floor — fixes 2, breaks 3;
2. a content-token coverage threshold — no separating value exists.

The spike at `spikes/subject-scope/` reproduces both against the real corpus using
the library's own `TxtExtractor`, `chunk_text`, `content_tokens`,
`has_relevance_overlap` and `is_supported`, and adds the finding that reframes the
problem.

**The scope information is not missing from the corpus. It is severed by chunking.**
`TxtExtractor` emits one paragraph per block and `chunk_text` chunks each block
independently, so one statutory subdivision is one EvidenceUnit. The clause that
decides whether § 1946.1 applies at all — "*for a term not specified by the
parties*" — is EU `::2::0`. The operative 60-day rule is EU `::3::0`. Retrieval,
the generator and the gate all saw `::3::0` and none of them ever saw `::2::0`.
Measured over the corpus: **8 of 11** operative (notice-period) EUs are citable in
isolation from the precondition that governs them — a **73% applicability-severance
rate**. Five of six documents state their term-scope in plain prose; Florida's is in
its title.

This also explains why no score threshold can work, and the spike measures it: the
wrong-scope passage is *genuinely the most topically relevant passage in the
corpus*. Coverage for the two known-bad pairings is 0.31 and 0.83 against a good
range of 0.29–0.80 — one inside the range, one **above every good pairing**. The
signal is not weak, it is anti-correlated. Any monotone function of topical
relevance is the wrong instrument by construction.

## Decision

Treat applicability the way ADR-0004 treated standing: as something asserted about
a source and applied **after** grounding, never derived from a relevance score and
never folded into the faithfulness gate. Three layers, in this order.

**1. Scope-context propagation (deterministic, default-on).** Carry a document's
or section's applicability clause onto every EvidenceUnit derived from it as a new
**additive** `scope_context` field, shown to the generator and to any scope check
and **excluded from the verbatim citation**. Measured feasible: 11/11 operative EUs
augment within the 450-token budget, 0 over.

This must be a new field, not the existing contextual-retrieval seam.
`evidence/chunked_builder.py`'s `Contextualizer` prefix lands in
`EvidenceUnit.text`, and `Candidate.citable_text` returns `passage`, not `text` —
so contextual retrieval reaches ranking only. The generator and the gate would
never see a scope prefix routed through it.

Propagation refuses nothing on its own; the gate is token containment and
containment only grows. It is the precondition for anything that could.

**2. Declared scope facets with a refusal-only floor (deterministic, opt-in).**
A facet is a curator-declared closed vocabulary carried as source metadata — values,
which values are mutually exclusive, and the surface forms by which a *query* may
assert a value. The gate withholds a source whose declared value is incompatible
with the value the query asserts. It can only ever remove already-grounded
candidates; it can never admit one. This is `AuthorityPolicy`'s seam with one more
dimension, and it inherits its properties: metadata in, no prose read, byte-stable,
port-conformable.

**3. A model scope verdict as a recorded INPUT to a deterministic rule (opt-in).**
The judge does not gate. It emits a discrete `scope_verdict` per candidate through
the existing two-phase emit-request / host-fulfiller path, the verdict is recorded
on the `Result`, and a deterministic rule consumes it: `verdict == out-of-scope ⇒
withhold`. The decision function stays a pure function of (candidates, verdicts,
policy), conformance vectors pin the verdicts, every port agrees byte-for-byte, and
the refusal is attributable in the audit trail. ADR-0009's rule survives intact:
the judge still never gates — it produces evidence, and a deterministic rule gates.

**4. Document the residue.** Until (3) ships, CiteNexus guarantees *no ungrounded
claim*; it does **not** guarantee that a grounded, top-tier citation is *on-scope*
for the question. That sentence ships in the docs, not only in this ADR.

### Alternatives considered and rejected

- **A cross-encoder / NLI entailment check at the selection point.** Rejected on
  direction and on form. Direction: NLI tests whether the passage entails the
  answer, which is what the faithfulness gate already tests and already passes; the
  needed test is the reverse — whether the *query's* preconditions hold in the
  passage's scope — which is not the relation an off-the-shelf NLI model is trained
  on. Form: it yields a continuous score, and the spike shows the wrong-scope
  pairings sitting at *both* ends of the score distribution, so a threshold is not
  untuned but wrong in kind. It also means bundling a model, which the library
  forbids. A model's scope opinion belongs in layer 3 as a discrete verdict.
- **An abstention-only judge that gates directly** ("it can only refuse more, so it
  is safe"). Right about safety, wrong about the contract. Cross-language
  conformance is a claim about *agreement between implementations*, not about
  direction of failure; a refusal-only judge still moves the ANSWER/REFUSE boundary
  as a function of a model call, so two ports — or the same port on two days —
  disagree. A system that intermittently refuses what it answered yesterday is not
  auditable, and auditability is the product. Layer 3 is the same capability with
  the nondeterminism moved out of the decision and into its inputs, which is exactly
  the move ADR-0004 made when it turned a human's assertion about standing into a
  tier in a metadata column.
- **Deriving scope from the document's `SOURCE:` header.** It works on this corpus —
  `"california"` really is in EU `::0::0` for all four CA documents — and it is a
  trap: that header is prose the example's author typed, not something a PDF of the
  statute carries. It would produce a spike that passes and a product that fails.
- **Any further threshold on any existing score** (rerank, fusion, coverage,
  distinct-document count). See the anti-correlation measurement above.

## Consequences

- **The class is narrowed, not closed, and the ADR says so.** Layer 2 catches 1/1
  subject-scope failures on the benchmark with **0/8 regressions** — and fires on
  **0/6** adversarial paraphrases of the same question that avoid the declared
  surface forms. A declared vocabulary protects the phrasings the curator
  anticipated and only those, and it is per-language, which matters for a library
  that answers in the query's language. Layer 2 must be priced as a floor. Anyone
  who describes it as closing the class is misdescribing it.
- Layer 1 is a new EU field, a new row column and a builder change: additive, so
  `ports-v2` readers written before it stay correct with an empty `scope_context`.
  Layers 2 and 3 add one selection point each, both after grounding, both
  removal-only — the same proof shape ADR-0004 used, so neither can weaken the
  no-ungrounded-claim guarantee.
- The faithfulness gate stays byte-identical and is not called by any code in this
  ADR, exactly as in ADR-0004.
- Severance is a function of extractor granularity. A PDF extractor emitting
  page-level blocks would put the precondition and the rule in one EU and the 73%
  would fall — and rise again the moment a section exceeds 450 tokens. Layer 1 is
  therefore worth doing even where severance is currently low, because it is the
  chunker, not the corpus, that decides.
- Whether the applicability clause is *structurally* recoverable — first subdivision
  of a section, a `StructureType` node, a heading — is unmeasured and decides
  whether layer 1 is cheap or expensive. The spike hand-identified the predicates
  and claims nothing about finding them automatically. That measurement gates
  implementation.
- Evidence base is small: 6 documents, 11 questions, one sub-topic, one legal
  system, and one reconstructed (not re-observed) failing answer — the committed
  `results.json` is post-authority-floor and refuses this question, by luck. The
  numbers here are existence proofs about shape, not rates. If a scope-relevance
  signal that separates on real data is ever produced, the "no deterministic method
  closes this" premise collapses and this ADR should be revisited; the spike claims
  only that lexical overlap, token coverage, authority tier, and any monotone
  function of topical relevance provably do not.
