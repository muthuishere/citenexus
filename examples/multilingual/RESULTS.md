# CiteNexus on a MULTILINGUAL corpus — before and after the fan-out

**An English question. The answer exists only in Tamil or Telugu. Does
CiteNexus find it?**

**Before: 8 of 22 questions answered, and 2 of those 8 cited the wrong
document. After: 16 of 22 answered, 16 of 16 cited the right one.** Groundedness
and citation stayed at 100% throughout, and all four ungroundable questions were
refused in both runs. Nothing was traded away to buy the recall.

Two runs of the same script over the same 12-document corpus, same models, same
22 English questions. **One constant changed**, in `run.py`:

```python
SEARCH_LANGUAGES: tuple[str, ...] = ("en",)              # BEFORE
SEARCH_LANGUAGES: tuple[str, ...] = ("en", "ta", "te")   # AFTER
```

| | |
|---|---|
| **Date** | 2026-08-16 (both runs, same sitting) |
| **Command** | `cd python && ./.venv/bin/python ../examples/multilingual/run.py` |
| **Keys** | `JINA_API_KEY`, `GEMINI_API_KEY` (read by the application, never by the library) |
| **Embeddings** | `jina-embeddings-v3` (multilingual; covers Tamil and Telugu) |
| **Reranker** | `jina-reranker-v2-base-multilingual` |
| **Generation** | `gemini-2.5-flash`, temperature 0 |
| **Reformulation** | `gemini-2.5-flash-lite` (`ReformulationConfig(enabled=True, endpoint=…, model=…)`) |
| **Signals** | `embedding` + `text` (dense + BM25; no graph, no wiki) |
| **Raw output** | [`results.json`](results.json) — per question, machine-readable (holds the AFTER run) |

---

## The headline case — grounded, cited, 100% faithful, and wrong

```
Q: An employee at the Hyderabad office wants to carry unused earned leave
   into the next leave year. What is the maximum number of days they may
   carry forward?

BEFORE:  "a maximum of 10 days"   cited: 01-en-leave-policy               answer_language: te
AFTER:   "5 రోజులు"                cited: 09-te-hyderabad-leave-annexure   answer_language: en
```

The BEFORE answer was **verbatim, correctly cited, and passed every claim of the
faithfulness gate** — `groundedness_rate` for that run was 100%. It was also the
wrong answer for the person asking. The authoritative Telugu annexure (clause
2.12) caps Hyderabad carry-forward at 5, overriding the English handbook's
clause 2.4 for that office. It was written in a script the tokenizer did not
claim, so it could not be cited under any retrieval outcome, and a
reachable-but-superseded English clause answered in its place.

**This is the whole argument.** The failure mode a cite-or-abstain library has to
worry about is not fabrication — the gate stops that. It is a *true quotation of
a document that does not govern*, which is indistinguishable from a correct
answer at the point of use. Making the authoritative document reachable is the
only thing that fixes it.

Note the second change on that line: BEFORE, an English question came back
stamped `answer_language: te`, because the old §11a chain let the retrieved
evidence vote on the answer language. AFTER, **all 22 questions stamp
`answer_language: en`** — the evidence no longer votes. See
[the known limitation](#known-limitation-verbatim-vs-answer-language) below,
because that field and the text it describes are now visibly in tension.

---

## The corpus — 12 documents, 3 languages, one company

An invented employment handbook for "Vaanam Technologies Private Limited", with
regional annexures for its Chennai and Hyderabad offices. **Authored, not
scraped** — see [`PROVENANCE.md`](PROVENANCE.md). Not real policy, not legal
advice, not a template.

| # | document | lang | format | carries |
|---|---|---|---|---|
| 01 | `01-en-leave-policy` | en | txt | 18 days earned leave, 10-day carry-forward, 12 days sick leave |
| 02 | `02-en-notice-period-policy` | en | txt | 60-day notice; **explicitly declines to state a buy-out amount** |
| 03 | `03-en-probation-policy` | en | txt | 180-day probation; **explicitly declines to state the extension length** |
| 04 | `04-en-confidentiality-policy` | en | txt | the obligation; **explicitly declines to state its duration or penalty** |
| 05 | `05-ta-chennai-leave-annexure` | **ta** | txt | clause 2.9A: **4** extra festival days; apply **15** days ahead |
| 06 | `06-ta-notice-buyout-annexure` | **ta** | txt | clause 7.2: **INR 45,000** per unserved month; cap **2** months |
| 07 | `07-ta-maternity-creche-annexure` | **ta** | **PDF** | clause 5.4: **26** weeks; creche **INR 6,000**/month to age 6 |
| 08 | `08-ta-termination-appeal-annexure` | **ta** | **PDF** | clause 8.3: appeal within **21** days; decide within **45** |
| 09 | `09-te-hyderabad-leave-annexure` | **te** | txt | clause 2.9C: **3** extra days; clause 2.12: **carry-forward capped at 5, not 10** |
| 10 | `10-te-probation-extension-annexure` | **te** | txt | clause 4.3: **90**-day extension, once; stipend **INR 12,500** |
| 11 | `11-te-confidentiality-annexure` | **te** | txt | clause 9.1: **24** months; clause 9.4: **INR 2,00,000** damages |
| 12 | `12-te-shift-allowance-annexure` | **te** | txt | clause 6.2: **INR 850** per night shift; max **10** a month |

The design is load-bearing and machine-enforced: each of those figures exists in
**exactly one place**, in a script the English query shares no token with.
`test_corpus.py` fails the build if any of them leaks into an English document.

**Golden set:** 22 questions, all asked in **English** — 6 answerable only from
Tamil, 7 only from Telugu, 5 from English (the control), 4 answerable from
nothing at all (must abstain).

---

## Results — by bucket

Answered, out of the bucket's n. "Exact token" rows are the probes that turn on a
clause number or an amount, because those are what query translation destroys.

| bucket | n | answered BEFORE | answered AFTER |
|---|---:|---:|---:|
| Tamil-only | 3 | 1 | **2** |
| Tamil-only (exact token) | 1 | 0 | **1** |
| Tamil-only (PDF) | 2 | 0 | **1** |
| **Tamil-only, all** | **6** | **1** | **4** |
| Telugu-only | 5 | 2 | **5** |
| Telugu-only (exact token) | 2 | 0 | **2** |
| **Telugu-only, all** | **7** | **2** | **7** |
| English control | 5 | 5 | 5 |
| Ungroundable (must abstain) | 4 | 0 | 0 |

## Results — evidence-quality metrics

| metric | BEFORE | AFTER |
|---|---|---|
| answered / abstained | 8 / 14 | **16 / 6** |
| `groundedness_rate` | 100% | 100% |
| `citation_rate` | 100% | 100% |
| `cited_right_document_rate` | 75% | **100%** |
| `answer_when_groundable` | 44% | **89%** |
| `abstain_when_ungroundable` | 100% | 100% |

The two rows that must never move did not move. `abstain_when_ungroundable`
stayed at 4/4: the fan-out bought recall on questions the corpus can ground, and
zero of it came out of the abstention guarantee. `cited_right_document_rate`
going from 75% to 100% is the headline case and its sibling disappearing — the
two BEFORE answers that were grounded in a genuine passage of the wrong document.

The six remaining abstentions are the four ungroundable probes plus two Tamil
questions. One of those two is an ordinary retrieval miss; the other, on
`08-ta-termination-appeal-annexure`, refuses with *"the available evidence
disagrees"* — the conflict path fired rather than the evidence-absent path. Both
are honest refusals, and both are still misses against a corpus that contains the
answer.

---

## Honesty requirement 1 — two changes shipped, and only one of them is the fan-out

**Do not read the Telugu column as a measurement of the fan-out.** Telugu could
not be cited *at all* in the baseline, for a reason that has nothing to do with
search language: U+0C00–U+0C7F was a hole in the script range table in
`tokenize.py`, between Bengali and Tamil, so every Telugu character classified as
`"unknown"` and `answer/flow.py` filtered every Telugu candidate out of the
grounding set. That was a **capability gap**, and it was fixed — `telugu` is now
in `SUPPORTED_SCRIPTS`, backed by a golden fixture per ADR-0011 — in the same
sitting as the fan-out landed.

So the Telugu 2 → 7 is the **sum of two independent changes**, and this benchmark
cannot separate them. Some of it is the tokenizer fix making Telugu citable at
all; some of it is the fan-out making Telugu reachable by an English query. We
did not run the intermediate configuration that would tell you the split.

**The Tamil buckets are the cleaner read on what the fan-out itself buys.** Tamil
was already a claimed script, already tokenized, already citable in the baseline
— nothing about Tamil changed except the search languages. That bucket went
**1/6 → 4/6**, and every one of those four is a correct-token answer. The two
exact-token and PDF sub-buckets went 0 → 1 each, which is the part that matters
most: the fan-out reaches facts that live behind a clause number in a script the
query shares no token with.

n = 6. Treat "the fan-out roughly triples Tamil recall" as a direction, not a
rate you can plan against.

## Honesty requirement 2 — verbatim vs answer language {#known-limitation-verbatim-vs-answer-language}

Look at the AFTER answer again:

```
answer:           "5 రోజులు"        ← Telugu script
answer_language:  "en"
```

That is a real inconsistency and it is not solved. It falls out of two rules that
are individually correct and genuinely conflict:

1. **The strict flow is extractive.** The generated answer has to survive
   `is_supported_v2()` against the passage it cites — it *is*, in practice, the
   cited span. That is what makes "no ungrounded claim" checkable.
2. **Citations stay verbatim in their source language.** A translated quote is no
   longer the evidence; nobody can diff it against the source.

When the only support for an English question is a Telugu clause, "answer in the
query's language" and "quote verbatim" cannot both hold, and **verbatim wins** —
correctly. `answer_language` then reports the language the answer was *requested*
in (the §11a chain resolved `en`), while the answer text is in the source's
script. The field is not lying about the chain; it is describing something other
than the text.

Two candidate resolutions, neither implemented:

- **Make `answer_language` descriptive of the returned text** rather than of the
  resolution chain. Cheap, and honest about what actually came back — but it
  changes a pinned field's meaning and there are conformance vectors on the
  chain.
- **Generate an answer *alongside* the verbatim citation** — an English sentence
  in `answer`, the Telugu span in `sources[0].passage`, with the gate run against
  the span. This is a real design change to the strict flow's shape, not a patch;
  it introduces a generated sentence that the gate must be re-specified to bound.

Until one of them lands: **read `sources[*].passage_language`, not
`answer_language`, if you need to know what script the text in front of you is
written in.**

## Honesty requirement 3 — these are single-run numbers

Gemini is **not deterministic at temperature 0.** On the law benchmark
(`examples/law-authority/`) we observed rate metrics move by ±1 question between
two identical runs, while the safety metrics — groundedness, citation, abstention
on ungroundable questions — reproduced exactly.

Every number on this page is from **one run per configuration**. A ±1 movement in
any bucket would not surprise us and would not change the conclusion; the Tamil
1 → 4 and the wrong-document 2 → 0 are larger than that noise. Do not quote a
bucket count as a reproducible constant, and re-run both configurations in the
same sitting rather than comparing against this file months later.

## Honesty requirement 4 — the corpus is authored fiction

Twelve invented employment-policy documents for a company that does not exist.
Every figure — the 60-day notice, the INR 45,000 buy-out, the 26 weeks of
maternity leave — was chosen to make the measurement work, not because it
reflects Indian employment law or any employer's practice. Nothing was scraped
or adapted. **Not legal advice.** Full account: [`PROVENANCE.md`](PROVENANCE.md).

---

## Smaller caveats worth carrying

- **`evaluate()` does not fan out.** `rag.evaluate(csv)` calls `ask()` with the
  default `search_languages=("en",)`, so its report in the AFTER run still reads
  9 answered / 13 refused, `expected_support_rate` 23%. That is the *baseline*
  behaviour showing through the eval front door, not a contradiction of the
  bucket table above — the bucket table comes from the harness in `run.py`, which
  passes `search_languages` explicitly. If you need a fanned-out evaluation
  today, drive `ask()` yourself.
- **`expected_support_rate` is a weak metric here** and should never be the
  headline. It checks that the expected token appears in the answer text, so a
  correct Telugu answer phrased in Telugu numerals scores as a miss.
- **The fan-out costs model calls.** One reformulation per requested language per
  question, cached per `(question, language)`. Three languages is two extra
  small-model calls per question, before retrieval.
- **The fan-out is refused on `strategy="deep"`.** The agentic loop writes its
  own queries; passing `search_languages` there raises
  `UnsupportedSearchLanguageError` rather than silently searching fewer
  languages.
- **A reformulator is mandatory for more than one language.** Without a
  configured reformulation endpoint, `search_languages` with 2+ languages raises
  — a fan-out that issues no extra queries looks exactly like a search that found
  nothing.
- **Tamil PDF extraction still loses word forms.** Left-side Tamil vowel signs
  come back in visual order, so ~36% of Tamil words extracted from the two PDFs
  will not string-match the same word from a `.txt`. Exact-match-critical tokens
  (clause numbers, amounts) survive untouched because they are Latin digits.
  `tools/render_pdf.py verify` measures it; the deterministic reorder repair is
  in that script and deliberately **not** in the library, pending a conformance
  vector.

---

## Reproducing

```bash
# offline — no keys, no network, runs in CI
cd python && ./.venv/bin/pytest ../examples/multilingual/test_corpus.py -q

# the PDFs and their extraction fidelity — offline, needs headless Chrome
./.venv/bin/python ../examples/multilingual/tools/render_pdf.py verify

# the live runs — COST MONEY. Run BOTH in one sitting, editing SEARCH_LANGUAGES
# in run.py between them.
export JINA_API_KEY=...        # referenced by name; never printed or logged
export GEMINI_API_KEY=...
./.venv/bin/python ../examples/multilingual/run.py
```

Search languages are refused **by name** before a single model call is spent:

```python
rag.ask(q, search_languages=("en", "ta", "te"))   # all three claimed — runs
rag.ask(q, search_languages=("en", "kn"))         # UnsupportedSearchLanguageError:
                                                  #   kannada is not claimed (ADR-0011)
```

Kannada, Malayalam, Gujarati, Gurmukhi, Oriya and Sinhala are **named in the
table and deliberately not claimed** — they are refusable by name, which is a
better answer than "unknown language code". The Go and JavaScript ports run the
frozen ASCII tokenizer and are Latin-script only; this benchmark is Python.
