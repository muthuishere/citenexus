# CiteNexus on LAW — cite-or-abstain baseline + the AUTHORITY gap

A real, runnable stress-test of CiteNexus on a high-stakes domain (California
landlord–tenant notice law). It establishes baseline evidence-quality numbers and
demonstrates, on real statute/case text, the **authority gap**: ranking is
token-relevance only, so a low-authority source that repeats the query vocabulary
out-ranks the controlling statute / binding case.

All numbers below are from an actual run against **live endpoints** — Jina
embeddings + reranker and Gemini generation. Nothing here is mocked.

## The corpus (6 real docs, one topic, deliberately varied authority)

| # | document_id | source (real, public) | authority |
|---|---|---|---|
| 01 | `01-ca-civ-1946_1-statute` | **Cal. Civ. Code § 1946.1** (leginfo.ca.gov) — *controlling* residential periodic-tenancy statute: **60 days'** notice if the tenant has resided ≥ 1 year, **30 days'** if < 1 year | HIGH (binding statute) |
| 02 | `02-mak-v-berkeley-2015-appellate` | **Mak v. City of Berkeley Rent Stab. Bd.** (Cal. Ct. App. 2015, courtlistener.com) — quotes and applies § 1946.1's 60-day rule | HIGH (binding appellate) |
| 03 | `03-ca-civ-1946_2-justcause-statute` | **Cal. Civ. Code § 1946.2** (Tenant Protection Act) — just cause after 12 months | HIGH (binding statute) |
| 04 | `04-ca-civ-1946-general-statute` | **Cal. Civ. Code § 1946** — the *older, general* rule: month-to-month terminable on **30 days'** notice. § 1946.1 opens "**Notwithstanding Section 1946**," i.e. it controls residential | MEDIUM (superseded for residential) |
| 05 | `05-nolo-month-to-month-blog` | **Nolo** self-help article — "In most states, landlords must provide a **30-day** notice to terminate a month-to-month tenancy" (omits CA's 60-day rule) | LOW (non-binding secondary) |
| 06 | `06-florida-83_57-statute` | **Fla. Stat. § 83.57** — month-to-month terminable on **30 days'** notice | WRONG JURISDICTION for a CA question |

The trap is built in: **four** of the six documents say "30 days" for a
month-to-month tenancy and repeat *month-to-month / notice / terminate / landlord*
densely. Only the two highest-authority California sources (§ 1946.1 and the Mak
opinion) carry the correct **60-day** rule for a long-term tenant — in denser,
less repetitive prose.

## Headline numbers (11-question golden set)

| metric | value | meaning |
|---|---|---|
| answered / refused | **5 / 6** | strict mode is the default |
| **groundedness_rate** | **100%** (5/5) | every answered question is fully verified against a cited passage |
| **citation_rate** | **100%** (5/5) | every answer carries a source citation |
| answer-when-grounded | 50% (4/8) | of the 8 questions the corpus *can* ground, 4 were answered |
| abstain-when-no-evidence | 67% (2/3) | of the 3 questions it *should* refuse, 2 were refused |
| library `evaluate()` | groundedness 100%, citation 100%, expected_support 45% | see note on `expected_support` below |

**The thesis holds on the metric that matters for a regulated domain: zero
ungrounded / fabricated answers.** Every claim CiteNexus emitted traced to a real
passage it cited — versus the **17–33% hallucination rate reported for generic
legal RAG** (Magesh et al., Stanford RegLab, *Hallucination-Free? Assessing the
Reliability of Leading AI Legal Research Tools*, 2024). We did **not** re-run a
generic-RAG baseline here; that range is cited as external context, not
reproduced. CiteNexus's failure mode is **not** hallucination — it is
**over-refusal** and **wrong-authority citation** (below).

## The AUTHORITY gap — demonstrated three ways

CiteNexus has **no authority / precedence / jurisdiction weighting** (confirmed in
the spec — see "Library finding" below). Retrieval fuses dense + lexical signals
and a Jina reranker; all of them score *token/semantic relevance*. Nothing in the
ranking knows that § 1946.1 outranks a blog. Three concrete outcomes from the run:

### 1. Wrong-authority source *wins the citation* (clearest example)

> **Q:** "How much notice is required to terminate a California residential
> month-to-month tenancy if the tenant has resided there **less than one year**?"
> **A:** "not less than 30 days' notice" — **cited `06-florida-83_57-statute`**
> (tier = out-of-jurisdiction).

The answer number is right (30 days), but the **cited authority is the Florida
statute**, not the controlling California § 1946.1(c) — which contains the exact
same rule. A lawyer who followed the citation would be reading the wrong state's
law. The script flags this automatically as `CITED-WRONG-AUTHORITY`.

### 2. A should-abstain question answered from a non-authority source

> **Q:** "What is the notice period to end a month-to-month tenancy in **Texas**?"
> **A:** "not less than 30 days' notice" — **cited `06-florida-83_57-statute`**.

Texas is **not in the corpus**; the correct behaviour is to refuse. Instead the
out-of-jurisdiction Florida statute token-matched "month-to-month / notice" and
answered a question about a *third* state. Flagged as
`SHOULD-ABSTAIN-BUT-ANSWERED`.

### 3. The high-authority answer is *suppressed*, causing a refusal

> **Q:** "How many days' notice must a California landlord give to end a
> month-to-month residential tenancy when the tenant has lived there for **more
> than one year**?" → **REFUSED.**

The correct answer (60 days, § 1946.1(b), reinforced by Mak) exists in the corpus,
but the retrieval ranking for this query is dominated by the low-authority 30-day
sources. Actual `retrieve(k=6)` output for this question:

```
06-florida-83_57-statute   score=0.0315   "(1) ... year to year ... not less than 60 ..."
06-florida-83_57-statute   score=0.0154   "(3) ... month to month ... not less than 3[0] ..."
05-nolo-month-to-month-blog score=0.0313  "In most states, landlords must provide a 30-day notice ..."
06-florida-83_57-statute   score=0.0152   "(2) ... quarter to quarter ..."
01-ca-civ-1946_1-statute   score=0.0323   "(c) ... 30 days ... resided ... less than one year"   <- wrong branch
```

The § 1946.1(**b**) "60-day" passage and the **Mak** binding appellate opinion do
**not** appear in the top 6 at all — out-competed by the repetitive 30-day text.
With the correct high-authority passage absent and the surfaced evidence uniformly
saying "30 days", the extractive faithfulness gate cannot verify a 60-day answer,
so the system refuses. **Authority-blindness silently suppressed the controlling
answer.** Both 60-day probe questions (>1 year, and a 3-year tenancy) refused for
this reason.

## Library finding: authority weighting does not exist (by design)

Grepping the source and spec: there is **no** authority / precedence / credibility /
jurisdiction field on an Evidence Unit, and no weighting of it in retrieval or the
answer flow. This is deliberate — `docs/SPEC-v6.md` lists **"in-loop conflict
weighing"** among the things "**deliberately *not* adopted**" (v3.1 note), and § 13
"Conflict Model" only *detects/reports* conflicts (`conflicts_detected` on the
result), it does not resolve them by source rank. The `acl` / partition hierarchy
is an *access* filter, not an *authority* ordering. So the authority gap shown here
is architectural, not a tuning miss — closing it needs a new per-document authority
signal fed into fusion/rerank (or a strict-mode "prefer the highest-authority
source among conflicting evidence" rule).

## Reproduce

```bash
# from repo root
cd python
python -m venv .venv && . .venv/bin/activate && pip install -e .   # if not already
export JINA_API_KEY=...          # referenced by NAME; never printed/committed
export GEMINI_API_KEY=...
# optional: point storage somewhere scratch (defaults to the example dir)
export CITENEXUS_BASE_URI=/tmp/law-data && rm -rf "$CITENEXUS_BASE_URI"
python ../examples/law-authority/run.py
```

Writes a machine-readable `results.json` (per-question decisions, cited docs,
authority tiers, evidence signals) next to `run.py`.

Refresh the raw source text from the public pages (not needed to run — the trimmed
corpus is committed):

```bash
export JINA_API_KEY=...
examples/law-authority/fetch_sources.sh    # -> examples/law-authority/raw/*.md
```

## How Jina was wired (and what is/ isn't real)

- **Jina embeddings** (`jina-embeddings-v3`) are wired as CiteNexus's embedding
  endpoint via `OpenAIHttpEndpoint(base_url="https://api.jina.ai/v1")` — the
  library's OpenAI-compatible embedding path. **Real, no shim.**
- **Jina reranker** (`jina-reranker-v2-base-multilingual`) is wired as the
  `RerankerConfig` endpoint (same Jina connection). **Real.**
- **Gemini** (`gemini-2.5-flash`, temperature 0) is the answer generator via
  `GeminiHttpEndpoint`. An answering LLM is required for `ask()`/`evaluate()`.
  **Real.** (`GEMINI_API_KEY` here; the library itself reads no env.)
- Storage is local filesystem + LanceDB (zero-infra default). **Real.**

No fake/hermetic provider was used anywhere in this example.

## Honest limitations

1. **No authority weighting exists** (the whole point above). The demonstration is
   of a *missing* capability, not a tuned one.
2. **`evaluate()` can't score abstention.** Its CSV is `question,expected`; an empty
   `expected` is scored "supported" only if the row was *answered*, so a *correct*
   refusal counts *against* `expected_support_rate` (that's why it reads 45% while
   groundedness/citation are 100%). This example therefore computes its own
   answer/abstain accuracy in `run.py`; the extra golden.csv columns
   (`expect_decision`, `probe`, `correct_docs`, `trap_docs`) are ignored by
   `evaluate()` and used only by our analysis.
3. **Over-refusal is real too.** 4/8 groundable questions refused: the two 60-day
   authority probes (authority suppression, above) **and** the § 1946.2 "12 months"
   and the § 1162 "manner of service" questions, where the conservative extractive
   faithfulness gate (every answer token must appear verbatim in one cited passage)
   couldn't verify a short numeric/cross-reference answer even though the passage
   was present. Safe for a regulated domain, but it lowers recall.
4. **The 17–33% hallucination baseline is cited, not reproduced.** It comes from the
   Stanford RegLab study of commercial legal-RAG tools; we did not run a generic RAG
   over this same corpus to produce a head-to-head number.
5. **Small set, single run.** 6 docs / 11 questions on one sub-topic; temperature 0
   makes it stable but this is an illustrative baseline, not a benchmark. LLM
   phrasing can still shift `expected`-token matches run to run.
6. **Corpus text is trimmed.** The `corpus/*.txt` files are faithful excerpts of the
   cited sources (headers + the substantive provisions), not the full pages, to keep
   the example light; `fetch_sources.sh` pulls the complete originals.
