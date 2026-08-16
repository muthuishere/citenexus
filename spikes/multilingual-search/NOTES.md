# SPIKE — multilingual search fan-out (`search_languages`)

**Question.** The owner wants:

> "an english question, with search_languages (english, tamil, telugu) (default only
> english), should do a parallel question change on tamil, telugu and english and find,
> and then response language (usually english, auto -> find question language, or specific)"

Before building it: does the miss it is meant to fix actually exist, what does the fix
cost, and does the existing fusion survive N lists?

**What I did.** `spike.py` — offline, deterministic, no network, no keys. It builds a
9-EU trilingual corpus (three facts × en/ta/te) and runs the library's **own**
`tokenize_v2`, `unsupported_scripts`, `Bm25TextSearch`, `LexicalRetriever`, `rrf_fuse`,
`RetrievalEngine` and `QueryReformulator` over it. No model endpoint is contacted; the
reformulator runs against a scripted transport carrying **human** reference translations,
so the numbers isolate *retrieval* behaviour from translation quality.

```bash
cd python && ./.venv/bin/python ../spikes/multilingual-search/spike.py
```

---

## M1 — the miss is total, not partial

An English question over a corpus that contains the answer in Tamil and Telugu:

| EU | lang | shared query tokens | Jaccard |
|---|---|---|---|
| `en-1` | en | **5** | 0.278 |
| `en-2` | en | 1 | 0.048 |
| `en-3` | en | 0 | 0.000 |
| `ta-1` … `ta-3` | ta | **0** | 0.000 |
| `te-1` … `te-3` | te | **0** | 0.000 |

**Lexical cross-lingual recall = 0%** — 0 of 6 non-English EUs, and it is 0 by
*construction*, not by ranking: the token sets are disjoint, so BM25's `tf` is zero for
every query term in every non-English document. No amount of re-ranking, `k`-widening or
score tuning reaches them. The same English question in its Tamil phrasing retrieves
`ta-1`; in its Telugu phrasing, `te-1`. The evidence is there; the query cannot see it.

**The dense channel is NOT measured here** and that is the spike's main blind spot — see
"what would make this wrong". BGE-M3 is genuinely multilingual and does have some
cross-lingual alignment, so the *system* miss is smaller than 100%. But the lexical
channel — one of the three fused signals, and the only one with exact-token fidelity for
names, IDs and clause numbers — contributes exactly nothing across a script boundary.

## M2 — **Telugu is not supported.** This is the headline.

| lang | `scripts_in` | `unsupported_scripts` | `tokenize_v2` tokens | claimed? |
|---|---|---|---|---|
| en | `('latin',)` | `()` | 6 | **YES** |
| ta | `('tamil',)` | `()` | 5 | **YES** |
| te | `('unknown',)` | `('unknown',)` | 4 | **NO** |

Telugu is not merely absent from `SUPPORTED_SCRIPTS` (13 scripts: arabic, bengali,
cyrillic, devanagari, greek, han, hangul, hebrew, hiragana, katakana, latin, tamil, thai)
— **it is absent from the script range table entirely.** U+0C00–U+0C7F falls in the gap
between bengali (…U+09FF) and tamil (U+0B80…), so every Telugu character resolves to
script `"unknown"`. Tamil, checked directly: supported, tokenizes, 5 tokens. The task
brief's suspicion was right about Telugu and right to flag it as a blocker.

**The dangerous part is that it half-works.** `tokenize_v2` still emits 4 tokens for the
Telugu query, because unknown scripts fall through the *delimited* (non-bigram) path. So
BM25 over a Telugu corpus produces plausible-looking rankings while the library has made
no claim about them, and `unsupported_scripts` reports the useless label `"unknown"`
rather than `"telugu"` — the caller cannot even tell *which* capability is missing. That
is precisely the class of silent false capability claim ADR-0011 was written to end.

Consequence for this change: `search_languages=("te",)` must **refuse explicitly**, and
the refusal must name the script. Adding Telugu properly is a *separate* ADR-0011-governed
change — a range-table entry, a golden fixture proving tokens + gate-accepts-own-source +
gate-rejects-unrelated, and regenerated cross-port conformance vectors. Out of scope here;
doing it inside this change would smuggle a cross-port contract edit into a retrieval feature.

## M3 — cost is linear and the expensive half is cached

| | per distinct question | per repeat question |
|---|---|---|
| reformulation model calls | **N−1** (the original is never translated) | **0** (cache) |
| retrieval calls | **N × R** | N × R |

Measured: 3 reformulations of the same query → **1** model call. Fan-out to 3 languages →
**3** retriever invocations per retriever. The shipped wiring has R=3 (vector, lexical,
structure), so `search_languages=("en","ta","te")` costs **2 cached model calls + 9
retrieval calls** per new question, against 1 model call (none, at default) + 3 today.

Latency shape: the N×R retrievals are independent and embarrassingly parallel — the wall
clock floor is one retrieval round, not N. The N−1 model calls are the real serial cost
and they amortise to zero across `ask`/`retrieve`/`evaluate` on the same question, which
matters because `evaluate(csv)` asks once per row.

## M4 — RRF across N language lists is well-behaved, with one caveat

```
en list (2): ['en-1', 'en-2']      ta list (1): ['ta-1']      te list (1): ['te-1']
fused (4):   en-1 0.01639 | ta-1 0.01639 | te-1 0.01639 | en-2 0.01613
top-5 share by language: {'en': 2, 'ta': 1, 'te': 1}
input-order independent: True
an empty per-language list is inert: True
```

Each language's rank-1 hit ties at exactly `1/(60+1)`, broken deterministically by `eu_id`
— no language buys rank with a bigger score scale, because RRF discards scores. Re-fusing
in a different input order gives a byte-identical ordering, and a language that returns
nothing contributes nothing (no perturbation).

**The caveat is list *length*, not score.** A 20-hit list fused against two 3-hit lists
takes **8 of the fused top-10**. RRF bounds per-*rank* influence, not per-*list* volume:
a language with a large corpus fills every slot the short lists leave empty. In this
design that is acceptable — the fan-out queries are the same question, so a language with
more matching evidence *should* contribute more passages — but it means fan-out is not a
round-robin and must not be described as one. If a future caller wants guaranteed
per-language representation, that is a different (unbuilt) fusion, not this one.

## M5 — a dead reformulation endpoint degrades, it does not explode

5 calls against a transport that raises → `[None, None, None, None, None]` with **1**
transport hit. Failures are cached with the same key as successes, so a dead endpoint
costs one attempt per distinct query and retrieval proceeds single-query — bit-for-bit
today's behaviour. This is the existing `QueryReformulator` contract and generalising the
target language does not change it.

## M6 — the fix works, and it is strictly additive

Same English question, same corpus, gold = `{en-1, ta-1, te-1}`:

```
before: ['en-1', 'en-2']                    recall@5 = 1/3
after : ['en-1', 'ta-1', 'te-1', 'en-2']    recall@5 = 3/3
```

**recall@5: 1/3 → 3/3.** Because the original query is always retained as one of the
fanned-out queries, every EU the single-language path found is still found — fan-out can
only add candidates to the fused pool, never remove them. That is the property that makes
`search_languages=("en",)` provably identical to today.

### The honest cost of M6

Fan-out on *"What is the notice period?"* returns `['en-2', 'ta-2', 'te-2', 'en-3', 'en-1']`
— and **`ta-2` says 60 days while `te-2` says 90 days.** The single-language query never
saw the conflict. Per ADR-0007 surfacing it is correct, but the consequence must be stated
plainly: **fan-out can raise the abstention rate, not only lower it.** It widens the
evidence pool, and a wider pool contains more disagreement. "More recall" is not the same
claim as "more answers", and this feature must not be sold as the latter.

---

## What would make this wrong

1. **The dense channel is unmeasured.** No embedding endpoint was available offline, and a
   hash-based fake embedder would have produced a meaningless zero by construction. BGE-M3
   *does* align across languages; if that alignment is strong on real corpora, the true
   end-to-end miss is well below the 100% lexical miss measured in M1, and the recall lift
   from fan-out is correspondingly smaller. **M1 bounds the lexical channel exactly and the
   system only qualitatively.** Re-run against live bge-m3 + a real bilingual corpus before
   quoting a system-level recall number anywhere public.
2. **Translations here are human, not machine.** A real reformulator run by a small model
   at temperature 0 will sometimes mangle exactly the tokens that matter — names, statute
   numbers, party identifiers. The spike therefore measures the *ceiling* of the technique,
   not what ships. Retaining the original query is the mitigation, and it is why retaining
   it is non-negotiable rather than a nicety.
3. **The corpus is 9 EUs.** BM25 IDF, RRF tie density and the flood asymmetry all behave
   differently at 10⁴ EUs. The *directional* findings (disjoint token sets, cache counts,
   order-independence) are structural and will hold; the specific scores will not.
4. **One EU per language per fact.** Real corpora are lopsided — 10⁴ English EUs and 40
   Tamil ones. Combined with the M4 flood result, the majority language will dominate the
   fused head even when the minority-language passage is the better answer. Not fatal
   (fusion feeds a reranker and then the per-claim gate), but it means fan-out helps most
   where the *only* answer is in the other language, and least where both exist.
5. **Telugu could be "fixed" by accident.** Because Telugu already tokenizes as `unknown`,
   someone could add `(0x0C00, 0x0C7F, "telugu")` to `SUPPORTED_SCRIPTS` in one line and
   watch the tests pass. That would be a false claim without the golden fixture ADR-0011
   requires, and it would silently move a cross-port contract. The refusal is the correct
   ship for this change.
