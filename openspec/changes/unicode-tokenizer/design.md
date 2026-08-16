## Context

`tokenize.py` is `[a-z0-9]+` over `.lower()`. It is the pinned SPEC-PORTS-v1 §4
contract and every port reproduces it exactly, by design. It is also ASCII-only,
which means the library's central guarantee — a claim must appear in its cited
passage — is undefined for most of the world's writing systems, and resolves to
"reject" rather than "error".

Three consumers share it: the faithfulness/relevance gates, BM25, and the
structure retriever. All three return nothing for non-Latin input, so the
abstention is over-determined and fixing any one of them alone would change
nothing observable.

Constraints: pure and deterministic (the conformance suite must pin it); no model
and no network; portable to Go (RE2) and JS; and — per ADR-0011 §3 — tier 3 for
*authorship* but **tier 1 for delivery**, so the ports keep native
implementations pinned by vectors and gain no mandatory native dependency. This
Python change is the reference implementation and the vector source.

## Goals / Non-Goals

**Goals:**

- A verbatim quote of its own source is accepted by the gate in every claimed
  script.
- Lexical retrieval (BM25, structure) returns non-empty results in those scripts.
- A capability gap is reported as a capability gap, never as missing evidence.
- Every claimed script is backed by a golden fixture, mechanically enforced.
- Existing ASCII conformance vectors do not move.

**Non-Goals:**

- Dictionary-based word segmentation (Thai, Khmer, Lao, Japanese). Bigrams are
  the deliberate floor.
- Stemming or lemmatization in any language — the tokenizer stays non-stemming
  per §4.
- Script-specific stopword tables; RTL rendering; transliteration.
- The Go, JS and Rust ports. They follow these vectors.
- Semantic entailment. The gate stays extractive.

## Decisions

### Scanning code over regex, and an explicit script table

Python `re` has no `\p{L}`; Go RE2 and JS RegExp support Unicode property escapes
with different property sets and different treatment of marks. A regex would be
the single most likely place for the three ports to silently diverge, and no
practical fixture set catches it. `tokenize_v2` is therefore a character scan:
`unicodedata.category(ch)[0] in ("L", "N", "M")` decides word-forming, and a
sorted range table decides script by binary search.

The range table is carried explicitly because Python's stdlib has no Script
property. It is deliberately partial: it covers the scripts CiteNexus claims plus
the near neighbours it must be able to *name* when refusing. Anything outside it
is `unknown`, which is unsupported, which is reported.

### Bigrams within a script run, never across one

This is Lucene's `CJKBigramFilter` semantics. "従業員は" yields
`["従業", "業員", "は"]`, not `["従業", "業員", "員は"]` — the kana particle does
not glue itself onto the noun. It keeps a Han index and a Kana index from
polluting each other, and it makes the rule statable in one line for the ports.

Bigrams preserve the ordered-containment guarantee: a reordered CJK claim is
still rejected, because reordering the characters changes the bigram sequence.

### v2 == v1 on ASCII, which is what made the migration cheap

For any input whose word characters are all ASCII, `tokenize_v2` and `tokenize`
return identical lists. NFKC and casefold are identity on ASCII; the category
scan reproduces `[a-z0-9]+` runs exactly (underscore is `Pc`, hyphen is `Pd`,
both separate). That property is asserted directly, and it is why moving BM25,
the structure retriever and the gate to v2 left `tokenize.json`, `bm25.json`,
`faithful.json`, `structure.json` and `e2e_hermetic.json` byte-identical. Only
`multilingual.json` — the deliberately Unicode-edge corpus — moved.

### Unclaimed scripts abstain, even though the tokenizer can process them

The bigram path will happily tokenize Khmer, and the gate will then accept a
verbatim Khmer quote. That was the first behavior this change produced, and it is
worse than refusing: it is indistinguishable from a verified answer while resting
on a segmentation no fixture has ever checked. ADR-0007 measured that a bad
linguistic table degrades *silently*; this is the same failure one layer down.

So the rule is claim-based, not capability-based. A question in an unclaimed
script refuses. A passage in an unclaimed script is reported but never cited.

### The stamp defaults to v1, not to "current"

`TokenizerManifest.version` defaults to 1 when the manifest is absent. A
partition with no stamp was written before stamping existed, therefore by v1.
Defaulting to the running version would report every legacy index as fresh —
which is precisely the silent-success failure the stamp exists to prevent.

## Risks / Trade-offs

- **CJK and Thai BM25 scores are bigram-based**, not word-based, so they are
  noisier than a dictionary segmenter would give. There is no regression risk
  against current behavior, because current behavior in those languages is to
  return nothing.
- **Case folding diverges across runtimes.** Go's `strings.ToLower` and JS's
  `toLowerCase` are not full case folding. The `ß` and Turkish dotted-İ vectors
  exist to make that divergence fail loudly in the ports rather than pass on
  ASCII.
- **Arabic and Hebrew diacritics are not stripped.** Marks are word-forming, so
  a diacritized and an undiacritized spelling are different tokens. This is
  conservative — it can cause a false abstain, never a false accept — and it is
  the correct default for the abugidas (Devanagari, Tamil, Bengali) where marks
  carry vowels. Diacritic-insensitive matching is a separate change.
- **The support matrix will look narrow.** That is the intended direction: the
  claim narrows before it widens, one fixtured script at a time.

## Migration Plan

1. Documentation correction lands first and independently.
2. `tokenize_v2` ships additively; nothing changes for existing Latin corpora.
3. Consumers move to v2 in one step, verified by the unchanged ASCII vectors.
4. Ports follow the two moved vectors; until they do, parity is scoped to v1.
5. Non-Latin corpora are re-indexed through ADR-0008's rebuild machinery; the
   per-partition stamp tells operators which ones still need it.

## Open Questions

- Should diacritic folding for Arabic/Hebrew be a per-script option, or is
  conservative-by-default correct permanently?
- Khmer, Lao and Myanmar have a working bigram path and no fixture. Do they earn
  claims, or do they wait for dictionary segmentation?
- Does the Rust core take authorship (ADR-0011 §3) now, or after the Go and JS
  ports have reproduced these vectors natively?
