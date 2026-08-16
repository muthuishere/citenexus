## Why

An English question over a corpus whose answer lives in Tamil retrieves nothing
from the Tamil half. Measured offline 2026-08-16 with the library's own
`tokenize_v2` / `Bm25TextSearch` / `LexicalRetriever`
(`spikes/multilingual-search/spike.py`):

```
BM25 top-5 for "Can the employee disclose confidential information?"
  -> ['en-1', 'en-2']            (the Tamil and Telugu answers are invisible)
lexical cross-lingual recall: 0 / 6 = 0%
```

The 0% is structural, not a ranking failure: the token sets are **disjoint**, so
BM25's `tf` is zero for every query term against every non-Latin document. No
`k`-widening, reranker or score tuning reaches those passages. ADR-0011 fixed the
tokenizer — Tamil produces tokens and the gate accepts a verbatim Tamil quote —
but a tokenizer cannot bridge a vocabulary gap.

`retrieve/reformulate.py` already has the machinery — a small model rewrites the
query, the original is retained, `RetrievalEngine` RRF-fuses both lists — hardwired
to exactly one target, **English**. That fixes "French question, English corpus"
and does nothing for "English question, Tamil corpus".

Two measured facts shape the change:

1. **Fan-out is strictly additive.** Retaining the original query means every EU
   the single-language path found is still found. recall@5 `1/3 -> 3/3`, with the
   pre-existing hits in their original places.
2. **Telugu does not work.** `scripts_in("<telugu>") == ('unknown',)`. U+0C00–U+0C7F
   is missing from the script range table entirely — and it *half*-works, because
   `tokenize_v2` still emits tokens for unknown scripts. A Telugu search would
   return plausible rankings for a script the library makes no claim about. Per the
   owner's standing rule — *we never want wrong at all, it's okay we can say don't
   know* — that must refuse out loud.

## What Changes

- **`search_languages` on `ask()` and `retrieve()`**, defaulting to `("en",)`.
  Each requested language yields one reformulation of the question; the fan-out
  runs through the **existing** `extra_queries` path and the **existing**
  `rrf_fuse`. No second fusion is written.
- **Generalise `Reformulator` from hardcoded-English to a target language.**
  `reformulate(query, language="en")`; the cache key becomes `(query, language)`.
  The `"en"` prompt string is byte-identical to today's, so the default path is
  unchanged behaviour, not a re-implementation of it.
- **A language table** (`lang/search.py`): ISO-639-1 code → display name + expected
  script, checked against `SUPPORTED_SCRIPTS`. Explicit, never guessed.
- **Explicit unsupported-capability refusal.** `UnsupportedSearchLanguageError`
  (carrying `.language` and `.script`) is raised **before any model call** when a
  requested language's script is outside `SUPPORTED_SCRIPTS` (Telugu today), when
  the code is unknown, or when more than one language is requested with no
  reformulator configured. Never an empty result. It reuses ADR-0011's
  `unsupported_scripts` script vocabulary rather than inventing a taxonomy.
- **`answer_language="auto"`** becomes an explicit sentinel meaning "detect the
  question's language", normalized to `None` at the boundary. `answer_language=None`
  keeps working **exactly** as today (the §11a chain in `lang/fallback.py`).
- **Not touched:** `answer/verify.py`, the per-claim faithfulness gate, citations,
  `rrf_fuse`, `tokenize_v2`, the conformance vectors, and every non-Python port.
  Telugu is **not** added to the tokenizer here — that is an ADR-0011-governed
  change with a golden fixture and a cross-port contract, owned elsewhere.

Backward compatibility is provable: `search_languages=("en",)` produces the same
reformulation prompt, the same cache behaviour, the same `extra_queries` tuple and
the same fused ordering as today.

## Capabilities

### New Capabilities
- `multilingual-search`: the `search_languages` fan-out on `ask`/`retrieve`, the
  per-language reformulation cache, the language/script capability table, the
  explicit unsupported-language refusal, and the `answer_language="auto"` sentinel.

### Modified Capabilities
- `retrieve-engine`: retrieval may be issued for N language variants of one
  question, fused through the single existing RRF merge point.

## Impact

- **Code:** new `python/src/citenexus/lang/search.py`;
  `retrieve/reformulate.py` (target language + cache key),
  `client.py` (`search_languages` on `ask`/`retrieve`, `_extra_queries`,
  `answer_language` normalization).
- **Data:** none. No row column, no index change, no fixture change.
- **Behavioural:** default unchanged. With N>1 languages, N−1 extra cached model
  calls and N×R retrievals per distinct question; a wider candidate pool feeding
  the unchanged gate; and — per ADR-0007 — potentially **more** abstention, because
  a wider pool surfaces cross-lingual conflicts a single-language query never saw.
- **Ports:** `golang/`, `js/`, `rust/` are out of scope. ADR-0013 specifies that a
  port on tokenizer v1 MUST reject any `search_languages` other than `("en",)` with
  an unsupported-capability error rather than returning nothing.
