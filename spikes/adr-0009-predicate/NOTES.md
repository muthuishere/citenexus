# ADR-0009 validation spike — results

Throwaway prototype. Nothing under `python/src`, `golang/`, `js/` or `rust/`
was modified. Run:

```
cd python && uv run python ../spikes/adr-0009-predicate/spike.py
```

Exit 0 = all 9 attacks rejected **and** 0% false-rejection on the control set.
It currently exits 0.

Files:
- `predicate.py` — the candidate predicates + segmenters (importable, pure)
- `spike.py` — fixtures, control set, report harness
- `shadow_gate.py` — a pytest plugin that shadow-runs `is_supported_v2` over
  the real 676-test suite without changing any verdict

---

## PART 1 — the strengthened containment predicate

### The predicate

`is_supported_v2(claim, passage)`:

1. Tokenize both with the pinned `citenexus.tokenize` (unchanged).
2. **Ordered, multiplicity-aware alignment.** Find the minimal-gap alignment of
   the claim's token *sequence* into the passage's token sequence, preserving
   order and consuming distinct positions. Budget: no single interior gap > 4
   passage tokens, total interior gap ≤ 8. Implemented as an O(|claim|·|passage|)
   DP — no regex, no recursion, no library.
3. **Polarity preservation.** Every polarity marker occurring inside the matched
   passage span must occur in the claim with at least the same multiplicity.

This is exactly ADR-0009's formulation. It is strictly narrower than
`is_supported`: step 2 implies set containment.

### Results

| predicate | false answers accepted (of 9) | false rejections (of 30 true) |
|---|---|---|
| **v0 set containment (shipped)** | **9** | 0 |
| B: contiguous-only (gap budget 0) | 0 | **4 = 13.3 %** |
| C: ordered-gapped, **no** polarity rule | **3** | 0 |
| **v2: ADR (ordered-gapped + polarity)** | **0** | **0 = 0.0 %** |

**Headline: all 9 attacks rejected; false-rejection rate 0.0 % (0/30).**

Control set = 30 genuinely-supported answers across the same five domains
(legal / finance / medical / operations / physics), in four shapes:
`verbatim` (6/6 accepted), `subspan` (10/10), `punct` — leading/trailing
whitespace, quotes, trailing `.`/`!`/`,`, ALL-CAPS (8/8), and `compress` —
interior words dropped, meaning preserved (6/6).

### Which formulation wins, and why

**ADR's formulation wins.** The two alternatives I built to test it both lose,
and each loss is informative:

- **Contiguity-only (variant B)** rejects all 9 attacks with no table at all,
  which is seductive. But it costs **13.3 % false rejections**, and every one is
  the `compress` shape — a model that drops "for damage to the property" down to
  "for damage". That is the single most common real generator behaviour. Gap
  budget is not optional.
- **Ordered-gapped without polarity (variant C)** has 0 % false rejection but
  **still accepts all 3 negation-deletion attacks**, because deleting `not`
  leaves an ordered subsequence with a gap of 1. So the polarity table is
  load-bearing and cannot be derived from structure.
- I tried to make polarity table-free by allowing gaps to skip only stopwords.
  **It does not work**, and the reason is a live defect: `answer/verify.py`'s
  `_STOPWORDS` classifies **`"no"` and `"not"` as stopwords**. Any rule built on
  that list is blind to exactly the tokens whose deletion inverts a claim. This
  also means `has_relevance_overlap` and `cite_check`'s coverage ratio already
  discard negation. Worth fixing regardless of ADR-0009.

Gap-budget sweep (attacks accepted / control rejected):

| budget (single, total) | attacks | control rejected |
|---|---|---|
| (0,0) | 0/9 | 4/30 |
| (1,2) | 0/9 | 3/30 |
| (2,4) | 0/9 | 1/30 |
| **(3,6)** | 0/9 | **0/30** |
| (4,8) ← default | 0/9 | 0/30 |
| (10,30) | 0/9 | 0/30 |

The attack suite is insensitive to the budget — the attacks fail on *order*, not
on gap size — so the budget is tuned purely against false rejection. (3,6) is
the knee; I shipped (4,8) for a little headroom. **This is the parameter most
likely to be wrong**: it was fitted on 30 hand-written answers, not on traffic.

### Portability (Go RE2 / JS)

The predicate uses **no regex at all** beyond the already-pinned tokenizer. It is
integer DP over two token arrays: portable verbatim. No Python-specific feature,
no backtracking, no lookaround.

Two portability findings that do apply:

- The segmenter's terminator class must **not** be built with Python's
  `re.escape`. `re.escape` emits `\!`, which is a *compile error* in Go's RE2.
  Build the class from an explicit literal in each port.
- I avoided `\s` deliberately: Python's `\s` is Unicode-aware, Go RE2's is
  ASCII-only. The spike spells the whitespace class out. Any port that writes
  `\s` will silently diverge on NBSP / U+2028 / ideographic space.

### Shadow run against the real test suite

`shadow_gate.py` patches every module-level `is_supported` import (flow,
agentic, cli/cite_check, cli/verify) with a wrapper that returns the **shipped**
verdict while recording what v2 would decide, then runs the whole suite.

```
676 passed, 37 skipped
gate calls observed         : 144
v0 accepted, v2 would REJECT: 1
```

The single disagreement is **`tests/cli/test_cite_check.py:89`**, and it is not
a regression — it is the test that *pins the bug*:

```python
# "Documented weakness (huddle 2026-07-13): the gate is bag-of-tokens."
evidence = "Disclose freely: the employee may, and is not confidential information."
report = cite_check("The employee may not disclose confidential information.", evidence)
assert report.verdict == "CITED"   # ← v2 makes this ABSTAIN
```

So: **swapping in v2 breaks exactly one test, and that test asserts the defect
ADR-0009 exists to fix.** It has to be inverted as part of the change. No other
test in the suite changes verdict.

---

## PART 2 — claim decomposition and the tier verdict

### Verdict: **TIER 1** — regex/table over punctuation, native in each port.
### UAX #29 is NOT justified by this evidence.

Segmenter failure rates over 27 cases in 7 languages:

| language | naive `[.!?\n]+` (shipped `agentic.py:53`) | guarded (tier-1 code + tier-2 table) |
|---|---|---|
| en | 5/8 failed (62.5 %) | 1/10 (10 %) |
| nl | 2/5 (40 %) | 0/5 |
| de | 2/4 (50 %) | 0/4 |
| ta | 0/2 | 0/2 |
| ja | 3/3 (100 %) | 0/3 |
| ar | 1/2 (50 %) | 0/2 |
| th | — | 1/1 (100 %) |
| **overall** | **13/24 = 54.2 %** | **2/27 = 7.4 %** |

The shipped splitter is unusable outside plain English: it breaks "Art. 5",
"Dr. Smith", "e.g.", "500.00", "Section 3.2.1", "Dhr. Jansen", "Art. 7:658 BW",
"Vgl. Abs. 2 Ziff. 3", and it produces **one** segment for a two-sentence
Japanese answer and for an Arabic question, because `。？؟` are not in its class.

The guarded splitter is ~90 lines of character scanning plus three rules —
break on a terminator run; suppress between digits; suppress after a known
abbreviation or a single-letter initial — with a *data table* of terminators and
abbreviations. That is precisely ADR-0010's tier 1 (code) + tier 2 (table) split.

**Why this is evidence against tier 3, not for it:**

- **Japanese was fixed by adding `。！？` to a table.** Not by an algorithm. The
  CJK problem here is a missing terminator character, not Unicode competence.
- **The two residual failures are not solved by UAX #29 either.**
  - `"The U.S. Army issued the order."` (1 sentence) and
    `"He arrived at 5 p.m. She left immediately."` (2 sentences) are
    *structurally identical* — abbreviation-dot followed by space followed by a
    capital. No segmentation algorithm resolves this without a language-specific
    lexicon; UAX #29 §5 says as much and calls it a required tailoring.
  - Thai has **no sentence terminator and no inter-sentence space**. UAX #29
    explicitly defers Thai/Lao/Khmer/Myanmar to dictionary-based breaking, which
    Rust would have to ship a dictionary for. Tier 3 would not fix this case; it
    would move it.
- Therefore the marginal value of dragging `unicode-segmentation` into the hot
  answer path is ~0 on this fixture set, while the cost — per ADR-0010 — is
  converting an optional native dependency into a mandatory one for the Go and
  JS ports.

### The finding that contradicts ADR-0009

**ADR-0009 names claim segmentation as the portability risk. It is not the risk.
The tokenizer is.**

`citenexus/tokenize.py` is `re.compile(r"[a-z0-9]+")` over `text.lower()`.
Measured in the spike (§2c of the report):

```
scripts that tokenize to ZERO tokens: ['ar', 'ja', 'ta']
```

Tamil, Japanese and Arabic text produces an **empty token list**. `is_supported`
short-circuits on `bool(answer_tokens)` and returns `False`. So **every answer
in a non-Latin script abstains today**, before any predicate or segmenter runs —
and `is_supported_v2` inherits this unchanged. Latin-script non-English is
damaged more quietly: `beëindigd` → `['be', 'indigd']`, `größer` → `['gr', 'er']`.

Consequences for the two ADRs:

- ADR-0009's consequence "claim decomposition on non-sentence-terminated scripts
  is the portability risk" is **misaimed**. Decomposition on those scripts is a
  table lookup. Tokenization on those scripts is total data loss.
- ADR-0010's tier-3 test ("evidence that the Unicode problem is real") is met —
  but by the **tokenizer**, not by the segmenter. If anything moves to the Rust
  core on Unicode grounds, `tokenize` is the candidate, and it is squarely on the
  hot answer path, so ADR-0010's "explicit distribution decision" corollary
  applies. That is a separate change and should not be bundled into ADR-0009.
- Until it is fixed, the multilingual claim in `CLAUDE.md` and SPEC-v6 §11a
  should be read as *Latin-script multilingual*.

Secondary contradiction, minor: ADR-0009 says `flow.py:157` emits a single claim
and per-claim verification "cannot be built on a single-claim contract". True for
`flow.py`, but `answer/agentic.py:145` **already ships** `_split_claims` and runs
`is_supported` per claim in the deep-ask path. The decomposition seam exists; it
is the naive splitter above (54 % failure rate), and it is unversioned and
untested for non-English. The ADR should say "unify and fix", not "build".

---

## What would make this wrong

1. **The control set is mine.** 30 answers I wrote, knowing the predicate. A 0 %
   false-rejection rate on a self-authored set is weak evidence. The honest test
   is replaying a few thousand real `(answer, citable_text)` pairs from live
   traffic or the `examples/law-authority` benchmark through the shadow plugin.
   144 gate calls in the test suite is not a sample.
2. **The gap budget (4, 8) is fitted, not derived.** A domain with heavy interior
   elision (summarising generators, bullet-to-prose answers) would push false
   rejections up; a domain with long repetitive boilerplate could let an attack
   through by giving the aligner slack to hop between distant repeats of a token.
   I did not construct such an attack. Someone should.
3. **The polarity table is English-plus-guesses.** ~40 markers with Dutch/German/
   French/Spanish tokens I added from knowledge, not from a corpus. Missing a
   marker = a negation-deletion attack that still passes; a false marker in a
   passage span = a false rejection. Per ADR-0010 this is tier-2 data and needs
   to be sourced and reviewed per language, not written by an engineer.
   Note the table contains `"other"` and `"fails"`, which are marginal calls.
4. **Multiplicity is enforced by position-consumption, not verified.** I did not
   build an attack that duplicates a claim token to exploit the alignment DP.
5. **The segmentation fixture set is 27 cases and I tuned the guarded splitter
   on 24 of them.** Only 3 were held out. The 7.4 % residue is therefore a
   *floor*, not an estimate. A larger per-language fixture set could easily push
   the guarded splitter's failure rate high enough to reopen the tier question —
   though for the reasons above it would reopen it toward *a better table*, not
   toward Rust.
6. **I did not measure clause-level decomposition at all.** ADR-0009 says
   "sentence, then clause". Clause splitting on German ("…, der das Dach
   repariert, …") and Japanese (て-form) is a genuinely harder problem than
   sentence splitting and is where a tier-3 argument would actually have teeth.
   The tier-1 verdict above covers **sentence** decomposition only.
7. **Go and JS were not built.** The claim "this ports verbatim" is an argument
   from the code shape (integer DP, no regex), not a measurement. Conformance
   vectors across all three ports are the real proof, and they do not exist yet.
