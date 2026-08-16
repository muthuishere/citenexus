# Design — multilingual search fan-out

ADR: `docs/adr/0013-multilingual-search-fanout.md`. Spike + numbers:
`spikes/multilingual-search/`.

## The seam

```
ask(q, search_languages=("en","ta"))
  |
  +-- resolve_search_languages(("en","ta"))      lang/search.py — raises, or returns
  |                                              (SearchLanguage(en), SearchLanguage(ta))
  +-- _extra_queries(q, langs)                   one cached reformulation per language
  |     reformulator.reformulate(q, "en") -> "..."      cache key ("...", "en")
  |     reformulator.reformulate(q, "ta") -> "..."      cache key ("...", "ta")
  |
  +-- RetrievalEngine.retrieve(q, k, extra_queries=(...))   UNCHANGED
        queries = [q, *extra]        <- the original is always first
        lists   = [r.retrieve(qq, k) for qq in queries for r in retrievers]
        rrf_fuse(lists)              <- the single merge point (§4b)
        reranker.rerank(q, head)     <- always the ORIGINAL query
```

Everything below `RetrievalEngine.retrieve` is untouched. The change is *which
queries are issued*, and nothing else.

## Decisions

**Default `("en",)` must be byte-compatible, not merely equivalent.** The prompt
for `"en"` is produced by formatting the generalised template with the display
name `"English"`, giving the exact string `reformulate()` sends today. A test
pins that string.

**Ordering is the caller's.** `extra_queries` follows the `search_languages`
order, de-duplicated preserving first occurrence, with any reformulation equal to
the original dropped (today's rule). Deterministic and inspectable at the call
site — no set iteration anywhere in the path.

**Refuse before spending.** `resolve_search_languages` runs first, so an
unsupported language costs zero model calls. Three refusal causes, one exception
type (`UnsupportedSearchLanguageError`, a `ValueError` subclass so existing
`except ValueError` call sites still behave):

| cause | message names |
|---|---|
| script not in `SUPPORTED_SCRIPTS` | the language, the script, ADR-0011 |
| unknown ISO-639-1 code | the code, and that codes are never guessed |
| N>1 with no reformulator | that fan-out needs a reformulation endpoint |

Raising, not returning a refusing `Result`: `retrieve()` returns a list and has
nowhere to put a refusal, and a refusing `Result` is the *evidence-absent*
channel. `tokenize.py` states the rule directly — a capability gap must not be
reported as an evidence judgement.

**`answer_language`: `"auto"` is a sentinel, `None` is unchanged.** Normalized at
the top of `ask()`/`_deep_ask()` (`if answer_language == "auto": answer_language =
None`), so `resolve_answer_language` and its §11a chain are untouched and every
existing test keeps its verdict. The two spellings are the same code path by
construction, which is what makes "keep `None` working exactly as today" provable
rather than asserted.

**The reformulator stays a Protocol.** `reformulate(self, query: str, language:
str = "en") -> str | None`. Defaulted, so a single-argument implementation is a
0.x-tolerable break for injected reformulators only; the shipped
`QueryReformulator` and the in-repo fake move together.

## Why not

- *Translate the query and search once* — destroys names/IDs/clause numbers, and
  makes fan-out replacive so a translator regression becomes a results regression.
- *Translate the corpus at ingest* — a translated passage is not the source;
  citing it verbatim cites the translator. (Same lesson as commit 0697c41.)
- *A per-language fusion guaranteeing each language a share* — forks the one merge
  point §4b protects. Measured: RRF already ties each language's rank-1 at
  `1/(60+1)` with an `eu_id` tie-break and is input-order independent.
- *Add Telugu to the tokenizer here* — one line and a lie. ADR-0011 requires a
  golden fixture, and the range table is a cross-port contract.

## Known limitation, stated in the spec

Fan-out widens the evidence pool, so it can surface cross-lingual conflicts and
**raise** abstention (ADR-0007). Measured: fanning "What is the notice period?"
across en/ta/te returns a Tamil passage saying 60 days and a Telugu passage saying
90 days. More recall is not more answers.
