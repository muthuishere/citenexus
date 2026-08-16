# `examples/multilingual` — an English question over a Tamil/Telugu corpus

A runnable benchmark for the question the `search_languages` fan-out exists to
answer: **when the only grounded answer is written in Tamil or Telugu, and the
question is asked in English, does CiteNexus find it?**

**Baseline, measured 2026-08-16 against live endpoints: Tamil 1/6, Telugu 0/7,
English control 5/5, abstention on ungroundable questions 4/4.**
Full write-up and caveats: **[`RESULTS.md`](RESULTS.md)**.

## What is here

| path | what |
|---|---|
| `corpus/` | 12 documents — 4 English, 4 Tamil (2 as real PDFs), 4 Telugu |
| `corpus-src/` | the text sources the two Tamil PDFs are rendered from |
| `golden.csv` | 22 English questions: Tamil-only, Telugu-only, English, and must-abstain |
| `run.py` | the live baseline runner — reports the gap bucket by bucket |
| `test_corpus.py` | fully offline structural tests (CI-safe, no keys) |
| `tools/render_pdf.py` | renders the Tamil PDFs and measures extraction fidelity |
| `PROVENANCE.md` | the corpus is **authored fiction** — read this first |
| `RESULTS.md` | the baseline, why it fails, and what would make the after-comparison unfair |
| `results.json` | machine-readable per-question output of the last live run |

## Run it

```bash
# offline: structure, scripts, tokenization, golden set, PDF fidelity
cd python && ./.venv/bin/pytest ../examples/multilingual/test_corpus.py -q

# live: costs money (Jina + Gemini). One run is the baseline.
export JINA_API_KEY=...        # referenced by name; never printed
export GEMINI_API_KEY=...
./.venv/bin/python ../examples/multilingual/run.py
```

## The one line

`run.py` has a single constant that decides which languages a question is
searched in:

```python
SEARCH_LANGUAGES: tuple[str, ...] = ("en",)   # TODO(multilingual-fanout)
```

`("en",)` is the pre-fan-out behaviour and produced every number in
`RESULTS.md`. Changing it to `("en", "ta")` takes the after-measurement; nothing
else needs to change. `("en", "ta", "te")` will raise
`UnsupportedSearchLanguageError` until Telugu is added to ADR-0011's
`SUPPORTED_SCRIPTS` with a golden fixture — see `RESULTS.md` §2 for why that is
a separate fix that must be measured separately.

## The corpus is fiction

Twelve invented employment-policy documents for a company that does not exist.
Not real policy, not legal advice, nothing scraped. See
[`PROVENANCE.md`](PROVENANCE.md).
