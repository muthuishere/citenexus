# 0011 — The tokenizer, and what "multilingual" is allowed to mean

Status: proposed · 2026-08-11

## Context

CiteNexus describes itself as multilingual — in the README, on the docs site, in
`SPEC-v6.md` §11a, and in the `languages` capability. Measured on 2026-08-11:

```
English   tokens=  7  is_supported(verbatim quote of its own source) = True
Dutch     tokens=  8  is_supported(verbatim quote of its own source) = True
Japanese  tokens=  0  is_supported(verbatim quote of its own source) = False
Chinese   tokens=  0  is_supported(verbatim quote of its own source) = False
Arabic    tokens=  0  is_supported(verbatim quote of its own source) = False
Tamil     tokens=  0  is_supported(verbatim quote of its own source) = False
```

The cause is one line. `python/src/citenexus/tokenize.py` is the pinned
SPEC-PORTS-v1 §4 tokenizer:

```python
_TOKEN_RE = re.compile(r"[a-z0-9]+")
def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())
```

`[a-z0-9]+` matches ASCII only. Any text with no Latin letters or digits produces
an empty token list. `answer/verify.py:73` short-circuits on
`bool(answer_tokens)` and returns `False`, so **a verbatim quote of its own
source is rejected as ungrounded**, and the flow abstains. The same tokenizer
feeds BM25 and the structure retriever, so lexical retrieval in those scripts
returns nothing either — the abstention is over-determined.

Every port reproduces this exactly, by design: the module docstring states it is
"a frozen contract — every port (Go, TS, Rust-bound) matches this exactly."

**Why this shipped.** The gate's multilingual test coverage is German. Every
language exercised anywhere in the gate test suite is Latin-script. The tests are
correct and they pass; they simply never asked the question. "Multilingual" was
implemented and verified as *Latin-script multilingual*, and the distinction was
never written down.

This is not the same failure as ADR-0009's. There the gate returns a confident
wrong answer; here it returns the pinned refusal — the *safe* direction, and the
no-ungrounded-claim guarantee technically holds. But a library that abstains on
100% of Japanese, Chinese, Arabic, Tamil, Thai, Hebrew, Greek, Korean and
Cyrillic input while advertising multilingual support is making a false claim
about its capability, and abstention is only honest when it means "the evidence
isn't there", not "I cannot read this script".

## Decision

**1. Correct the claim immediately, ahead of any code.** Until the tokenizer
ships, the README, docs site and spec say **Latin-script languages** and name the
scripts that abstain. Documentation accuracy is not gated on the fix; a false
capability claim in a library sold on defensibility is the more urgent defect.

**2. Replace `[a-z0-9]+` with Unicode-aware tokenization**, as a *versioned*
tokenizer (`tokenize.v2`) alongside the frozen v1, not an edit to v1:

- Word-forming characters become Unicode letter/number/mark classes rather than
  ASCII ranges, with case folding rather than `.lower()`.
- **Scripts without spaces (Chinese, Japanese, Thai, Khmer, Lao) need
  segmentation, not classification.** Whitespace splitting yields one token per
  sentence, which makes BM25 and any containment predicate degenerate. The
  minimum viable treatment is character-bigram indexing for CJK — the standard
  approach, deterministic, no dictionary, and adequate for both lexical retrieval
  and containment. Dictionary-based word breaking is explicitly deferred.
- v1 stays exported and byte-identical for existing conformance vectors and
  existing indexes. Corpora tokenized under v1 keep working; the tokenizer
  version is recorded per index so a mismatch is detectable rather than silent.

**3. Placement: tier 3 under ADR-0010 — Rust core — with one condition.**
This is the case ADR-0010's tier 3 was written for: Unicode segmentation where
Python `re`, Go RE2 and JS RegExp genuinely diverge, and where no practical
fixture set catches the divergence. Rust already owns language competence via
`detect.rs`.

The condition is that ADR-0010 also forbids moving hot-path work to tier 3
without an explicit distribution decision — and the tokenizer is the hottest path
there is. So tier 3 here means: **the Rust implementation is authoritative and
generates the conformance vectors; the ports keep a native implementation that
those vectors pin.** Go and JS do not gain a mandatory native dependency. This is
tier 3 for *authorship*, tier 1 for *delivery*, and it is a deliberate amendment
to ADR-0010's binary framing, which did not anticipate an algorithm that is both
Unicode-hard and hot-path.

**4. Ship the abstention as a real signal in the meantime.** Where the tokenizer
cannot process a script, the Result must say so — an explicit
`unsupported_script` reason, distinct from "no supporting evidence". Silently
returning the evidence-absent refusal for a capability gap is the specific thing
that let this hide.

## Consequences

- The public capability claim narrows before it widens. Some users will discover
  the library does less than they thought; that is the correct outcome of having
  claimed too much.
- Any corpus in an affected script must be re-tokenized and re-indexed to
  benefit. The ADR-0008 hashing and rebuild machinery makes this surgical rather
  than a full re-ingest, which is the first real payoff from that work.
- New conformance vectors are needed per script, and per ADR-0007's finding that
  a bad linguistic table degrades silently, no script may be *claimed* as
  supported until it has a golden fixture. Scripts ship one at a time.
- CJK bigram indexing will change BM25 scores in those languages. There is no
  regression risk against current behavior, because current behavior in those
  languages is to return nothing.
- The deeper process failure is that "multilingual" was never given a testable
  definition. The remedy is a per-script support matrix in the spec, with each
  cell backed by a fixture — so the claim and the evidence for it are the same
  artifact.
- **Explicitly out of scope:** dictionary-based word segmentation, stemming or
  lemmatization in any language (the tokenizer stays non-stemming per §4),
  script-specific stopword tables, and RTL rendering concerns.
