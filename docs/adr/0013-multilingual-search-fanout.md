# 0013 — Multilingual search fan-out (`search_languages`)

Status: proposed · 2026-08-16 · spike: `spikes/multilingual-search/`

## Context

An English question over a corpus that holds the answer in Tamil retrieves
nothing from the Tamil half. Measured offline on 2026-08-16 with the library's own
`tokenize_v2` / `Bm25TextSearch` / `LexicalRetriever` (`spikes/multilingual-search/spike.py`):

```
query tokens: ['can','confidential','disclose','employee','information','the']

eu_id   lang   shared query tokens   jaccard
en-1    en                       5     0.278
ta-1    ta                       0     0.000     <- contains the answer
te-1    te                       0     0.000     <- contains the answer

BM25 top-5 for the English question: ['en-1', 'en-2']
lexical cross-lingual recall: 0 / 6 = 0%
```

The 0% is structural, not a ranking failure: the token sets are **disjoint**, so
BM25's `tf` is zero for every query term against every non-English document. No
`k`-widening, reranker or score tuning reaches those passages. ADR-0011 fixed the
*tokenizer* — Tamil now produces tokens and the gate accepts a verbatim Tamil
quote — but a tokenizer cannot bridge a vocabulary gap. The Tamil evidence is
indexed, citable and invisible.

`retrieve/reformulate.py` already contains most of the machinery: a small model
rewrites the query, the original is retained, and `RetrievalEngine.retrieve(...,
extra_queries=...)` RRF-fuses both lists. It is hardwired to exactly one target
— *English* — which fixes "French question, English corpus" and does nothing for
"English question, Tamil corpus". The owner's ask is the general case:

> "an english question, with search_languages (english, tamil, telugu) (default only
> english), should do a parallel question change on tamil, telugu and english and find,
> and then response language (usually english, auto -> find question language, or specific)"

**The response half already exists.** `ask(answer_language=...)` is the §11a
chain (`lang/fallback.py`): `None` = auto-detect the question's language,
an explicit string = force it. Nothing about the response side needs rebuilding;
it needs a name that says what it does.

**Telugu does not work, and this is the load-bearing finding.** Measured:

| lang | `scripts_in` | `unsupported_scripts` | tokens | claimed? |
|---|---|---|---|---|
| en | `('latin',)` | `()` | 6 | YES |
| ta | `('tamil',)` | `()` | 5 | YES |
| te | `('unknown',)` | `('unknown',)` | 4 | **NO** |

Telugu is not merely missing from `SUPPORTED_SCRIPTS`; U+0C00–U+0C7F is missing
from the script range table entirely, so every Telugu character resolves to
`"unknown"`. Worse, it **half-works**: `tokenize_v2` still emits four tokens
(unknown scripts take the delimited path), so BM25 returns plausible-looking
rankings for a script the library makes no claim about, and the capability signal
reports the useless label `"unknown"` instead of `"telugu"`. That is the exact
class of silent false capability claim ADR-0011 exists to end.

## Decision

**1. `search_languages` on `ask()` and `retrieve()`, defaulting to `("en",)`.**
Each requested language produces one reformulation of the question; the fan-out
runs through the *existing* `extra_queries` path and the *existing* `rrf_fuse`.
No second fusion is written. Default `("en",)` reproduces today's single-target
English reformulation exactly, including the prompt string, so the default path
is unchanged behaviour rather than a re-implementation of it.

**2. The original query is always retained, never replaced.** It is one of the
fanned-out queries by construction, not a configurable option. Translation is
lossy exactly where lexical retrieval is precise: party names, statute and clause
numbers, product IDs, docket references. A rewrite that renders "clause 14.2" as
"பிரிவு 14.2" has kept the number by luck, not by contract, and a rewrite that
transliterates a party name has destroyed the only exact-match token in the query.
Retaining the original makes fan-out **strictly additive at retrieval** — every
EU the single-language path found is still found. Measured (M6): recall@5 goes
`1/3 → 3/3` and the pre-existing hits keep their places.

**3. An unsupported search language raises; it never returns empty.** A language
whose script is outside `SUPPORTED_SCRIPTS` — Telugu today — raises
`UnsupportedSearchLanguageError` carrying the language code and the script name,
*before* any model call is made. Same for an unknown language code (no guessing),
and same for requesting more than one language with no reformulator configured,
which would otherwise fan out to nothing and look like a working search that
found nothing. This follows `tokenize.py`'s own rule verbatim: *"A non-empty
result is a capability signal, not an evidence judgement. Returning the
evidence-absent refusal for a capability gap is the specific thing that let the
ASCII-only tokenizer hide for as long as it did."* An abstention means *the
evidence does not support this*; a missing script means *we cannot look*. Those
must not share a channel. The error reuses ADR-0011's `unsupported_scripts`
vocabulary — the same script names, no parallel taxonomy.

**4. `answer_language="auto"` becomes an explicit sentinel; `None` keeps working
identically.** Both mean "detect the question's language and answer in it" and
both take the same code path (`"auto"` is normalized to `None` at the boundary,
before `resolve_answer_language`). `None` is ambiguous between "I did not set
this" and "I want auto", and the owner's model of the feature has three states —
`auto`, `"en"`, `"ta"` — that should be three writable values. This is additive:
no existing caller changes, and no serialized field changes.

**5. Telugu is NOT added to the tokenizer in this change.** Adding it is one line
plus a lie. Under ADR-0011 a script enters `SUPPORTED_SCRIPTS` only with a golden
fixture proving tokens produced, the gate accepting a verbatim quote of its own
source, and the gate still rejecting unrelated text — and the range table is
tier-2 shared data whose conformance vectors are a cross-port contract. That is
its own ADR-0011-governed change, owned by whoever holds `rust/`, `golang/` and
`js/`. Smuggling a cross-port contract edit inside a retrieval feature is how
false claims ship. Until then `search_languages=("te",)` raises, loudly, naming
Telugu.

### Why this cannot admit an ungrounded claim

Fan-out changes **which passages are retrieved** and nothing else. Downstream of
retrieval, every invariant is untouched:

- The per-claim faithfulness gate still verifies each atomic claim against a
  **single** cited passage (ADR-0009). A passage that arrived via a Tamil query is
  verified by the identical predicate as one that arrived via the English query.
- Citations remain **verbatim in the source language**. The reformulation is a
  retrieval key, never text; it never enters the answer, the citation, or the
  gate's input. The quoted span is a byte range of the EU as stored.
- The generator sees the original question and the retrieved EUs — the widened
  candidate pool, not the widened *query* — so it cannot cite a translation.

The only thing fan-out can do is put a passage in front of the gate that would
not otherwise have been there. The gate's verdict on that passage is independent
of how it arrived. Hence: more evidence considered, identical strictness applied.
More recall is **not** more answers.

### Interaction with the ADR-0004 authority floor and ADR-0007 conflicts

Fan-out feeds the same fused list into the same authority selection, so the
strict-mode floor still applies: a Tamil blog surfaced by a Tamil query cannot
outrank an English controlling statute, because `select_by_authority` reads
`authority_meta` and has no idea which query found the row. Authority tiers are
per-document metadata, so a corpus that assigns tiers only to its English
documents will see minority-language passages float in at the default tier and
be filtered by the floor — correct, and worth stating: **fan-out does not confer
authority.**

Conflict surfacing (ADR-0007) is where fan-out visibly *costs* something.
Measured (M6): fanning "What is the notice period?" across en/ta/te returns a
Tamil passage saying 60 days and a Telugu passage saying 90 days — a conflict the
English-only query never saw. Surfacing it is correct. The consequence is that
**abstention can rise, not only fall**: a wider evidence pool contains more
disagreement. This feature must not be sold as "fewer refusals".

### Cost

Per **distinct** question: `N-1` reformulation model calls (the original is never
translated) and `N × R` retrieval calls, where R is the number of configured
retrievers. With the shipped R=3 (vector, lexical, structure),
`search_languages=("en","ta")` costs 1 model call + 6 retrievals against 1 + 3
today. Model calls are cached per `(query, language)`, so `ask` / `retrieve` /
`evaluate` on the same question pay once — measured: 3 reformulations of one
query → **1** transport hit. Failures are cached too, so a dead endpoint costs one
attempt per distinct query and degrades to single-query retrieval. The N×R
retrievals are independent, so the latency floor is one retrieval round, not N;
the serial cost is the N−1 model calls, amortised to zero on repeats.

### Port impact — Go and JS must refuse the whole feature

Go and JS still ship tokenizer **v1** (`[a-z0-9]+`, ASCII only). There,
`search_languages=("ta",)` would tokenize the Tamil reformulation to **zero
tokens**, retrieve nothing, fuse nothing, and return an ordinary empty result
that is indistinguishable from "the corpus does not contain this". Per the
standing rule — *we never want wrong at all, it's okay we can say don't know* —
that is the one outcome this change may not produce. Specified:

- Until a port carries tokenizer v2, it MUST reject **any** `search_languages`
  value other than `("en",)` with an unsupported-capability error naming the
  language and the reason (`tokenizer v1 is ASCII-only`). Not a warning, not an
  empty list, not a silent downgrade to single-query.
- The default `("en",)` remains fully supported on every port, so this is a
  capability the ports lack, not a contract they violate.
- Nothing about fan-out enters SPEC-PORTS or the conformance vectors. Fan-out is
  **orchestration** (which queries to issue), not a pinned algorithm. The pinned
  algorithms it touches — `tokenize_v2`, `rrf_fuse` — are called unchanged, with
  unchanged inputs per call.

  **One correction, found by implementation.** "No conformance fixture moves" was
  not free: `conformance/prompts.json` pins the reformulation prompt, and the
  obvious generalisation (turn the constant into a `{language}` template) moved it
  immediately. The prompt *sent for English* had not changed at all — only the
  constant the generator happened to read. Resolution: `_PROMPT` stays the rendered
  English string and a separate `_PROMPT_TEMPLATE` is what the runtime formats, so
  the pinned artefact keeps meaning "the English prompt". The general lesson is
  worth recording: a fixture that pins a *template* silently pins the
  implementation's shape, not its behaviour, and generalising any templated prompt
  will trip it.

## Alternatives considered and rejected

1. **Translate the query and search once in the corpus language.** Rejected: it
   destroys the exact tokens lexical retrieval depends on, and it requires knowing
   the corpus language before retrieving — which is the thing retrieval is
   supposed to find out. It also makes fan-out *replacive*, so a regression in the
   translator is a regression in results the system used to get right.
2. **Translate the corpus at ingest and index both.** Genuinely fixes recall and
   is rejected on the guarantee: a translated passage is not the source, and
   citing it verbatim would cite the *translator*, not the document. The recent
   "cite the source's words, not the context model's blurb" fix (commit 0697c41)
   is this same lesson. Storing translations as retrieval-only aliases that resolve
   down to the original EU is a defensible future design — it is a different,
   larger change (index schema, rebuild matrix, cost per document rather than per
   query) and it does not block this one.
3. **A per-language fusion that guarantees each language a share of the top-k.**
   Rejected as unmotivated. Measured (M4), RRF already ties each language's rank-1
   hit at exactly `1/(60+1)` with a deterministic `eu_id` tie-break, and is
   independent of input order. It is *not* round-robin — a 20-hit list takes 8 of
   the fused top-10 against two 3-hit lists — but that asymmetry is by list length,
   which is a real signal (more matching evidence), not a scoring artefact.
   Writing a second fusion to correct it would fork the one merge point §4b says
   no third-party retriever may bypass.
4. **Auto-detect the corpus languages and fan out to all of them.** Rejected for
   this version: cost scales with corpus diversity rather than user intent, and it
   makes the model-call count unpredictable from the call site. `search_languages`
   is explicit; a `search_languages="auto"` fed by the corpus language histogram
   is a plausible later addition on top of it.
5. **Return a refusing `Result` instead of raising for an unsupported script.**
   Rejected: `retrieve()` returns a list and has nowhere to put a refusal, so the
   two front doors would signal the same fault differently, and a refusing
   `Result` is the evidence-absent channel — the precise conflation ADR-0011
   named as the reason the ASCII tokenizer hid.
6. **Put `search_languages` only in config.** Rejected: the language a question
   should be searched in is a property of the question, not of the deployment.
   Config-level *defaults* (`ReformulationConfig.languages`) are a reasonable
   follow-up; the per-call parameter is the primitive.

## Consequences

- Two front doors gain one keyword argument each. Every existing call site is
  unchanged and takes the unchanged code path; `answer_language=None` behaves
  exactly as before.
- `Reformulator` grows a `language` parameter (defaulted), and its cache key
  becomes `(query, language)`. This is a protocol change for anyone who injected
  a custom reformulator — a 0.x-acceptable break, and the default keeps
  single-argument call sites working.
- **The library now has a language whose support it must decline out loud.**
  `search_languages=("te",)` raises. Users who want Telugu get a precise reason
  and a named blocker instead of an empty list. This is the intended user
  experience of "we never want wrong at all", and it is also a standing
  advertisement for the missing ADR-0011 fixture.
- Cost becomes user-controllable and linear in N. A caller who passes five
  languages to `evaluate()` over a 500-row CSV pays 4 × 500 model calls on first
  run. The cache bounds repeats, not the first pass; nothing here rate-limits, and
  that is left to the endpoint layer.
- Abstention rate may rise on multilingual corpora that disagree with themselves.
  That is ADR-0007 working, and it should be measured before anyone quotes a
  refusal-rate number for a multilingual deployment.
- The dense retrieval channel is **not** characterised. The 0% figure bounds the
  lexical channel exactly; BGE-M3 has real cross-lingual alignment, so the
  end-to-end miss this change closes is smaller than 100% and currently unmeasured.
  No system-level recall number should be published until that is run against a
  live embedder (`spikes/multilingual-search/NOTES.md`, "what would make this wrong").
