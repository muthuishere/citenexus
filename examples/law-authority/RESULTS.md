# CiteNexus on LAW — the authority gap, and what closing it actually bought

A real, runnable stress-test of CiteNexus on a high-stakes domain (California
landlord–tenant notice law). It was built to *demonstrate* a gap: ranking is
token-relevance only, so a low-authority source that repeats the query vocabulary
out-ranks the controlling statute. That gap is now closed by the ADR-0004
**authority floor**, and this file records the before and after — including the
part that did **not** get fixed.

All numbers are from actual runs against **live endpoints** — Jina embeddings +
reranker and Gemini generation. Nothing here is mocked. The committed
`results.json` is a post-floor run.

## The corpus (6 real docs, one topic, deliberately varied authority)

| # | document_id | source (real, public) | curator-declared tier |
|---|---|---|---|
| 01 | `01-ca-civ-1946_1-statute` | **Cal. Civ. Code § 1946.1** (leginfo.ca.gov) — *controlling* residential periodic-tenancy statute: **60 days'** notice if the tenant has resided ≥ 1 year, **30 days'** if < 1 year | `controlling-statute` |
| 02 | `02-mak-v-berkeley-2015-appellate` | **Mak v. City of Berkeley Rent Stab. Bd.** (Cal. Ct. App. 2015, courtlistener.com) — quotes and applies § 1946.1's 60-day rule | `binding-appellate` |
| 03 | `03-ca-civ-1946_2-justcause-statute` | **Cal. Civ. Code § 1946.2** (Tenant Protection Act) — just cause after 12 months | `statute` |
| 04 | `04-ca-civ-1946-general-statute` | **Cal. Civ. Code § 1946** — the *older, general* rule: month-to-month terminable on **30 days'** notice. § 1946.1 opens "**Notwithstanding Section 1946**," i.e. it controls residential | `general-statute` |
| 05 | `05-nolo-month-to-month-blog` | **Nolo** self-help article — "In most states, landlords must provide a **30-day** notice…" (omits CA's 60-day rule) | `secondary-blog` |
| 06 | `06-florida-83_57-statute` | **Fla. Stat. § 83.57** — month-to-month terminable on **30 days'** notice | `out-of-jurisdiction` |

The trap is built in: **four** of the six documents say "30 days" for a
month-to-month tenancy and repeat *month-to-month / notice / terminate / landlord*
densely. Only the two highest-authority California sources carry the correct
**60-day** rule for a long-term tenant — in denser, less repetitive prose.

Tiers are **curator assertions** supplied at ingest via `authority=` (see
`authority.csv`); the library never derives them from prose.

## The measured progression (11-question golden set)

| metric | v0.9.0 | v0.10.0, pre-floor | **post-floor (now)** |
|---|---|---|---|
| answered / refused | 5 / 6 | 8 / 3 | **6 / 5** |
| groundedness_rate | 100% | 100% | **100%** |
| citation_rate | 100% | 100% | **100%** |
| answer_when_grounded | 50% | 75% | **75%** |
| abstain_when_no_evidence | 67% | 33% | **100%** |
| out-of-jurisdiction citations | — | **4** | **0** |

Read the columns together, because each one on its own misleads:

- **The safety metric is what moved, and it moved all the way.** Four citations
  of a Florida statute against California and Texas questions → **zero**. Every
  question that should refuse now refuses (3/3).
- **v0.10.0 pre-floor is the cautionary column.** It looks like the best run —
  8 answered, `answer_when_grounded` up from 50% to 75%, groundedness still
  100% — and it is the *least trustworthy* of the three. Those extra answers
  include a Texas question answered from Florida law with
  `all_claims_verified: true`. **100% groundedness with 4 wrong-jurisdiction
  citations is the whole reason authority had to exist:** the gate proved the
  words came from the passage, which was true, and said nothing about whether the
  passage governed.
- **Recall did not regress to buy that.** `answer_when_grounded` held at 75%
  across the floor; what disappeared was the wrong-authority answers, not the
  right ones.
- The library's own `evaluate()` still reports `expected_support 45%` — see
  limitation 2 below; it cannot score a *correct* refusal.

### Caveat: Gemini is not deterministic at temperature 0

An earlier, **identical** post-floor run produced **5/6** answered/refused and
`answer_when_grounded` **62%**, not 6/5 and 75%. Same code, same corpus, same
prompts, same temperature.

What was stable across both runs: **out-of-jurisdiction citations = 0**,
groundedness 100%, citation rate 100%, `abstain_when_no_evidence` 100%. So treat
the rate metrics as ±1 question of wobble and the **safety** metrics as the
reproducible result. Any single-run rate quoted from this example is an
illustration, not a benchmark number.

## What the floor fixed

### 1. The Texas question (`SHOULD-ABSTAIN-BUT-ANSWERED` → refused)

> **Q:** "What is the notice period to end a month-to-month tenancy in **Texas**?"
> **Pre-floor:** "not less than 30 days' notice" — cited `06-florida-83_57-statute`,
> `all_claims_verified: true`.
> **Post-floor:** refused.

Texas is not in the corpus. The out-of-jurisdiction Florida statute token-matched
"month-to-month / notice" and answered a question about a *third* state, perfectly
grounded. The floor withholds it before generation, and the refusal reason is
deliberately distinct from "no relevant evidence found".

### 2. The 60-day authority probes stopped being suppressed

Both long-tenancy questions now answer **60 days** from the right sources:

| question | cited | tier |
|---|---|---|
| "> one year" | `02-mak-v-berkeley-2015-appellate` | `binding-appellate` |
| "three years, month-to-month" | `01-ca-civ-1946_1-statute` | `controlling-statute` |

Both are classified `CORRECT-AUTHORITY` in `results.json`. Pre-floor these
**refused**: the repetitive 30-day text (Florida × 3 + the Nolo blog) crowded
§ 1946.1(b) and the *Mak* opinion out of the top 6 entirely, so the extractive
faithfulness gate had no 60-day passage to verify against. Authority-blindness had
silently suppressed the controlling answer.

## Three things this run does not let us claim

### A. One golden question now refuses *by design*, and the golden set is wrong about it

> **Q:** "What minimum notice is required to terminate a month-to-month tenancy in
> **Florida**?" — `expect_decision=answer` → **refused**.

The curator declared Florida `out-of-jurisdiction` for this corpus. A floored
California corpus therefore *cannot* answer a Florida question, and refusing is
the correct behaviour of the configuration as written. This is **corpus scoping,
not a bug** — but it does mean the golden set now encodes an expectation the
configuration contradicts, and that counts against `answer_when_grounded`. Either
the question leaves the golden set or the corpus stops being California-only; the
current state is honest but inconsistent.

### B. The subject-scope gap is NOT fixed — the commercial-lease case passed by luck

> **Q:** "How much notice must a landlord give to terminate a fixed five-year
> **commercial** lease with a specified term in California?" — must **abstain**.

It refuses in this run. **That is luck, not authority.** Dropping the Florida
chunks changed which passages reached the generator; the floor did nothing here
and cannot. The source that produces the wrong answer is
`01-ca-civ-1946_1-statute` — tier `controlling-statute`, the **highest** tier in
the corpus. No ordering over sources can exclude the top of the ordering. It is
genuinely the right authority, about the wrong kind of tenancy.

The spike at `spikes/subject-scope/NOTES.md` found the real cause, and it is not a
scoring problem: **applicability severance**. `TxtExtractor` splits on blank lines
and `chunk_text` chunks each block independently, so one statutory subdivision is
one EvidenceUnit. The clause that decides whether § 1946.1 applies at all — "*for
a term not specified by the parties*" — is EU `::2::0`; the operative 60-day rule
is EU `::3::0`. Retrieval, the generator and the gate all saw `::3::0` and none of
them ever saw `::2::0`. Measured: **8 of 11** operative notice-period EUs are
citable in isolation from the precondition that governs them — a **73% severance
rate** on this corpus.

The scope information is *in the corpus* (5 of 6 documents state their term-scope
in plain prose). It is severed by chunking, and every downstream guard is
chunk-local by design. See **`docs/adr/0012-subject-scope-applicability.md`**.

### C. Over-refusal is still real

Two groundable questions refuse for gate-conservatism, not authority: § 1162
"manner of service", where the extractive gate (every answer token must appear
verbatim in one cited passage) could not verify a short cross-reference answer
even though the passage was present — plus the Florida question in (A). Safe for a
regulated domain; it costs recall.

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
authority tiers, evidence signals) next to `run.py`. Expect the rate metrics to
move by a question between runs; see the determinism caveat above.

Refresh the raw source text from the public pages (not needed to run — the trimmed
corpus is committed):

```bash
export JINA_API_KEY=...
examples/law-authority/fetch_sources.sh    # -> examples/law-authority/raw/*.md
```

## How Jina was wired (and what is / isn't real)

- **Jina embeddings** (`jina-embeddings-v3`) wired as CiteNexus's embedding
  endpoint via `OpenAIHttpEndpoint(base_url="https://api.jina.ai/v1")` — the
  library's OpenAI-compatible embedding path. **Real, no shim.**
- **Jina reranker** (`jina-reranker-v2-base-multilingual`) wired as the
  `RerankerConfig` endpoint (same Jina connection). **Real.**
- **Gemini** (`gemini-2.5-flash`, temperature 0) is the answer generator via
  `GeminiHttpEndpoint`. **Real.** (`GEMINI_API_KEY` here; the library itself reads
  no env.)
- Storage is local filesystem + LanceDB (zero-infra default). **Real.**

No fake/hermetic provider was used anywhere in this example.

## Honest limitations

1. **Zero fabrication is the claim; zero wrong answers is not.** Every claim
   CiteNexus emitted traced to a real passage it cited — versus the **17–33%
   hallucination rate reported for generic legal RAG** (Magesh et al., Stanford
   RegLab, *Hallucination-Free? Assessing the Reliability of Leading AI Legal
   Research Tools*, 2024), which is **cited as external context, not reproduced**
   here. CiteNexus's failure modes are over-refusal and — until the floor —
   wrong-authority citation, with wrong-*subject* citation still open.
2. **`evaluate()` can't score abstention.** Its CSV is `question,expected`; an
   empty `expected` is scored "supported" only if the row was *answered*, so a
   *correct* refusal counts *against* `expected_support_rate` (why it reads 45%
   while groundedness/citation are 100%). This example computes its own
   answer/abstain accuracy in `run.py`; the extra `golden.csv` columns
   (`expect_decision`, `probe`, `correct_docs`, `trap_docs`) are ignored by
   `evaluate()` and used only by our analysis.
3. **Authority is curator-supplied, and a mis-declared tier is a real failure
   mode.** The floor is only as good as `authority.csv`. Nothing in the library
   validates that a document really is a controlling statute.
4. **Small set, few runs.** 6 docs / 11 questions on one sub-topic, and the
   generator is not reproducible at temperature 0 (above). Illustrative baseline,
   not a benchmark.
5. **Corpus text is trimmed.** The `corpus/*.txt` files are faithful excerpts
   (headers + the substantive provisions), not the full pages, to keep the example
   light; `fetch_sources.sh` pulls the complete originals. Severance rates depend
   on extractor granularity, so they are specific to plain-text ingest of *this*
   corpus.
