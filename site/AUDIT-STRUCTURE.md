# Docs structure audit — CiteNexus site

Scope: structure, navigation, narrative. **Not** per-port coverage, **not** factual
verification against source (two other audits own those). Read on `main`,
2026-08-17. 36 content files, 35 sidebar entries + splash `index.mdx`.

---

## 0. The single worst structural problem

**The site is organised around the library's API surface, not around the five
failures the product exists to close — and as a result three of the five have no
page of their own, while the two that do are filed under "Scenarios", the group a
reader reads *last*.**

Concretely, mapped against the five failure classes:

| Failure class | Where a reader finds it today | Sidebar group |
|---|---|---|
| 1. Words came from the passage, claim doesn't follow (9/9 adversarial accepted) | **Nowhere.** One `<Aside>` on `index.mdx:118-123` titled "Parity status", plus two sentences: `scenarios/contract-review.mdx:67` and `scenarios/evaluate-a-corpus.mdx:56` | — |
| 2. Two sources disagree, rank picks one | `scenarios/conflicting-sources.mdx` | Scenarios |
| 3. Cited source has no authority (FL statute → TX question) | `authority.mdx` | Retrieve & answer (item 6 of 8) |
| 4. Authoritative doc in an unreadable script | `languages.mdx` + two scenario pages | Retrieve & answer (item 8 of 8) + Scenarios |
| 5. Model failed, corpus silently poisoned (Go zero vector) | **Buried.** `providers.mdx:264-292`, "Failure must be sayable", 264 lines into a 386-line page titled "Provider contracts — bring your own model" | Retrieve & answer |

Failure 1 is the product's headline claim and it is the *only* one with no page.
Worse: the two places that describe the gate describe the **broken** version of it
as if it were the guarantee —

- `concepts.mdx:17` — *"A per-claim grounding gate checks **every word** of the
  answer against its cited passage."*
- `index.mdx:136` — *"A per-claim grounding gate **drops any word not in** the
  cited passage."*

Word/token containment is precisely the predicate that accepted 9 of 9 adversarial
false answers. The page called "How it holds the line" — the second link in the
hero — teaches the reader the mechanism that fails, and the only correction on the
site is an Aside further down the homepage that frames it as a *port parity note*
rather than as a correction.

Failure 5 is the second-worst placed: an operator asking "can my index be silently
wrong?" has no reason to open a page about writing a custom provider.

---

## 1. Three reader journeys, with exact stuck points

### A. The evaluator — 5 minutes to decide "is this worth trying"

Path taken: `index.mdx` → hero → code tabs → `concepts.mdx`.

1. **`index.mdx:9` (hero tagline) undersells to the wrong buyer.** "A RAG library
   that answers only from your documents — with the exact quote and page." Every
   RAG vendor claims this. The differentiators — a gate that survives adversarial
   paraphrase, authority standing, conflict abstention, fail-closed ingest — are
   invisible above the fold. The evaluator's mental filing is "another RAG
   wrapper", and *nothing in the first screen contradicts it*.
2. **`index.mdx:106-124` — the "Same decision, different surface" Aside is the
   first thing after the code, and it is 19 lines of caveat.** It covers: Go/JS are
   core-only, there is no `CiteNexus` facade in Go/JS, the conformance suite, and a
   parity gap in the faithfulness gate. That is four different disclaimers before a
   single differentiating capability has been stated. **Stuck point: the evaluator
   learns what the library *cannot* do in two of three languages before learning
   what it does at all.**
3. **`index.mdx:130-155` "What you get" CardGrid restates generic RAG.** "Ground /
   Verify / Cite or abstain / Any document / Your models / Prove it". Only "Cite or
   abstain" is distinctive, and its card text is the same sentence as the hero.
   None of the five failure classes appear on the homepage — no authority, no
   conflict, no script coverage, no fail-closed ingest.
4. **`index.mdx:164-169` — the strongest evidence on the site (the live law
   benchmark, 100% groundedness, 0 fabricated) is the fifth section, below the
   fold, after "More than retrieval".** And the number it leads with (100%
   groundedness) is the *weaker* number; the striking one — out-of-jurisdiction
   citations 4 → 0, `abstain_when_no_evidence` 33% → 100% (`authority.mdx:198-202`)
   — never reaches the homepage at all.
5. **Dead end at `concepts.mdx`.** 87 lines, three sections, no link out except to
   the GitHub conformance dir. It does not link to `authority.mdx`,
   `scenarios/conflicting-sources.mdx`, `languages.mdx`, or the benchmark. The
   evaluator who clicks the hero's second button reaches the end of the argument in
   90 seconds with nowhere to go but the sidebar.

**Verdict: the evaluator never sees the product's actual claim.** Five minutes on
this site produces "grounded RAG with citations, Python-first, Go/JS partial".

### B. The engineer with a corpus who wants a working answer today

Path taken: `quickstart.mdx` → `ingest.mdx` / `s3.mdx` → `ask.mdx` → stuck.

1. **`quickstart.mdx:15-33` offers three install tabs, then step 2 and 3 are
   Python-only with no tab.** A reader who clicked the Go tab in step 1 gets Python
   code with no acknowledgement until they re-read the intro paragraph
   (`quickstart.mdx:8-11`). The `syncKey="lang"` tabs make this worse: their Go
   selection persists and then silently doesn't apply.
2. **The quickstart never mentions `signals`.** `signals.mdx` says omitting it
   builds **all six** indexes including the slow-path `graph`, `community` and
   `wiki` distillation. So the copy-paste quickstart is the slowest possible
   configuration, and the page that says so (`signals.mdx`) sits in the *Ingest*
   group four groups down, linked from exactly one page site-wide.
3. **`quickstart.mdx:72-77` "Next" links to s3 / models / ingest / evaluate — not
   to `ask.mdx`.** The reader has just run `ask()` and the natural next question
   ("what did I get back, and what do the fields mean?") routes nowhere.
   `result.mdx` is linked from one page in the whole site (`ask.mdx:35`).
4. **First real answer comes back `refused`. Now the journey breaks.** There is no
   troubleshooting page. The reader must know to guess between:
   `signals.mdx:44-50` (embedding signal without an embedder → lexical-only
   fallback), `languages.mdx:61-68` (cross-script zero BM25 overlap),
   `reranking.mdx:73` (`top_k`), `ask.mdx:38-51` (trust modes),
   `authority.mdx:164` (floor refusal). **These five causes emit five different
   signals and live on five pages in four sidebar groups, and no page enumerates
   them.** This is the site's most common real-world reader state and it is
   completely unserved.
5. **`result.mdx` — the page that should answer it — is stale and incomplete.**
   Its `EvidenceSignals` table (`result.mdx:53-64`) lists eight fields and omits
   `unsupported_scripts` (which `languages.mdx:13` and
   `scenarios/multilingual-desk.mdx:82` both tell the reader to read),
   `authority_tier` and `authority_floor_applied` (which `authority.mdx:180-183`
   tells the reader to read). Three of the five failure classes emit a signal the
   Result reference does not document.
6. **Flat contradiction the engineer will hit.** `result.mdx:88-94`: *"the current
   extractive flow does **not** populate them — today every result carries
   `conflicts = ()` and `conflicts_detected = 0`. Treat them as forward-compatible
   fields, not an active signal."* Versus
   `scenarios/conflicting-sources.mdx:26-38`, which prints
   `response.conflicts # ('value: filing-q1-restated vs filing-q1 (30 vs 12)',)`
   and states strict mode abstains with both sides cited. One of these is wrong;
   the reader cannot tell which, and the *reference* page is the one that reads as
   authoritative.

### C. The regulated reader who must defend an answer to an auditor

Path taken: `scenarios/index.mdx` → `scenarios/regulated-audit.mdx` →
`authority.mdx` → `domain-rag.mdx`.

1. **`scenarios/regulated-audit.mdx` is well-built and correctly cross-links
   authority (`:84-90`).** No complaint. But it is titled "Regulated audit" and is
   *only* about corpus reconciliation — it does not cover the audit trail this
   reader actually needs: provenance chain, per-claim verification record, the
   `evaluate()` artifact. `ProvenanceEntry` (`result.mdx:81-88`) is the single most
   audit-relevant type on the site and is mentioned on exactly one page, in a
   three-line paragraph, with no worked example.
2. **`authority.mdx:8-11` blocks them with a false notice**: *"Requires 0.10.0 —
   not yet on PyPI or npm … Install from source until 0.10.0 ships."* 0.10.0 shipped
   (tags `v0.10.0`, `golang/v0.10.0` are in the repo). A compliance reader who
   reads that Aside literally concludes the jurisdiction guard is **unreleased** and
   drops it from evaluation. This is the highest-cost of the three stale notices.
3. **`authority.mdx` is 241 lines, 8 H2 sections, and the site has
   `tableOfContents: false` set globally (`astro.config.mjs:29`).** No in-page
   navigation on the site's longest, densest page. The reader who wants "what does
   the floor *not* fix" (`:208`) must scroll past the whole config reference.
4. **`domain-rag.mdx` — the page literally titled "Build a domain RAG (legal,
   medical)" — tells this reader the feature does not exist.** `domain-rag.mdx:63-71`:
   *"CiteNexus ranks by relevance, not **authority** — it has no jurisdiction /
   precedence / source-credibility weighting … This is architectural, not a tuning
   knob."* It does not link `authority.mdx`. This is the single most damaging stale
   page on the site: it is the on-ramp for exactly the buyer authority was built
   for, and it denies the feature.
5. **`benchmark-law.mdx` contradicts itself inside one page.**
   `:67-69` — "*no* authority, precedence, or jurisdiction weighting"; then
   `:87-94` — an Aside "This gap is now closed — opt in"; then `:96-101` — a second
   Aside re-asserting "*tracked as future work, not a knob you can turn today*".
   Three positions on one page, in that order. A reader stops at the last one.
6. **Dead end: no upgrade/migration note.** A 0.9.0 user has no page telling them
   what changed in 0.10.0, whether `authority=` on `ingest()` is additive, or
   whether the faithfulness-gate change alters existing answers. `authority.mdx:85-90`
   and `:189-190` scatter reassurances ("additive", "absence is not failure") across
   two Asides; nothing collects them.

---

## 2. Duplication map

Format: **canonical** (where the truth should live) vs **duplicate/drifted**.

### 2.1 Model wiring — three pages, one real split, one redundancy

| Page | Lines | Unique content |
|---|---|---|
| `models.mdx` | 57 | The four shipped clients + one constructor shape. **~90% of it is restated on the other two.** |
| `custom-endpoints.mdx` | 156 | `${ENV}` header templates, typed `HttpEndpoint`s, `from_config` wiring. Genuinely distinct. |
| `providers.mdx` | 386 | The five Protocol contracts, structural typing, failure semantics, per-port scope. Genuinely distinct. |

- **`models.mdx` has almost no unique content.** Its opening ("bundles no models…
  injected by you") repeats `providers.mdx`'s thesis; its two Asides
  (`models.mdx:38-45` "an endpoint is one option, not the requirement";
  `:47-52` vision is host-fulfilled) are compressed restatements of
  `providers.mdx` and `vision.mdx`. Its closing line is four links to the pages
  that say it better.
- All three open by re-establishing the same premise. `custom-endpoints.mdx:8-11`
  spends its opening paragraph disclaiming itself against `providers.mdx`;
  `providers.mdx:380-386` closes by pointing back at both. The three pages spend
  ~30 lines negotiating their own boundary with each other — a symptom of the
  boundary being wrong, not of the reader needing it explained.
- **Drift:** `models.mdx:26-31` constructs `CiteNexus(...)` with positional store +
  kwargs; `custom-endpoints.mdx:100-111` uses `CiteNexus.from_config(config)`.
  Neither says when to use which. `providers.mdx` uses neither.

**Fix:** delete `models.mdx`; fold its 15 unique lines (the four importable
clients, the Ollama example) into the top of `custom-endpoints.mdx`, retitled
"Models & endpoints". Keep `providers.mdx` as the contract reference. 3 pages → 2.

### 2.2 Multilingual — three pages, heavy restatement

| Content | `languages.mdx` | `multilingual-desk.mdx` | `multilingual-corpus.mdx` |
|---|---|---|---|
| Script support list | `:19-35` (full table) | `:72-79` (prose restatement of the same 14) | — |
| Khmer/Lao/Myanmar deliberately unclaimed | `:41-44` | `:91-96` (Aside, same argument) | — |
| Go/JS ASCII-only | `:49-54` (Aside) | `:98-102` (Aside) | — |
| Answer-language ladder (4 rungs) | `:130-149` | `:50-59` (same 4 rungs, prose) | — |
| Verbatim-beats-answer-language caveat | `:151-160` (Aside) | `:61-68` (Aside) | `:150+` (full section) |
| `search_languages` fan-out | `:108-128` | `:112-119` (pointer) | full page |
| The 44% → 89% number | `:125-127` | — | `:107+` |

**Three separate statements of the answer-language rule and three of the
verbatim-conflict caveat.** They currently agree, but each is worded differently
and they will not stay in sync — `languages.mdx:8` says "14 scripts", `index.mdx:53`
says "13 of them in Python", and the table at `languages.mdx:19-35` lists 14 rows
of claimed scripts (Hiragana/Katakana share a row). The drift has already started.

**Fix:** `languages.mdx` owns the script matrix, the answer-language ladder and
the verbatim rule — once. `multilingual-desk.mdx` keeps only the worked build and
links up. `multilingual-corpus.mdx` is genuinely distinct (retrieval reach across
scripts, measured) — keep it, but it is a *retrieval* story, not a language one.

### 2.3 Authority / scope — drift, not duplication

- `authority.mdx` (canonical, 241 lines) vs `domain-rag.mdx:63-71` (denies the
  feature) vs `benchmark-law.mdx:67-101` (three positions in one page). See journey
  C, points 4–5. **This is the worst factual drift in the set and it is structural
  in origin: three pages were each written as the "legal reader" entry point, days
  apart, and none was retired when the next was written.**
- `authority.mdx:208-229` (the "wrong subject" Aside, 20 lines) is a compressed
  restatement of `scenarios/subject-scope.mdx`, which it then links. The Aside is
  long enough that a reader may not click through — and `subject-scope.mdx` is the
  page with the actual root-cause analysis (applicability severance).
- `scenarios/regulated-audit.mdx` vs `authority.mdx`: **no duplication.** The
  "In-scope is not the same as authoritative" section (`:84-90`) is the cleanest
  cross-link on the site. Use it as the model.

### 2.4 Storage — near-duplicate pair

`file-based.mdx` (25 lines) and `s3.mdx` (35 lines) are the same page with a
different first argument. Both re-explain "the store is where the index is
written, not a folder that gets auto-scanned" in near-identical words
(`file-based.mdx:18-22`, `s3.mdx:30-35`). Two sidebar slots for one 40-line page.

### 2.5 Evaluation — split by accident

`evaluate.mdx` (API reference) and `scenarios/evaluate-a-corpus.mdx` (the
argument for why abstention rows matter) are in **different sidebar groups**
("Scenarios & benchmarks" and "Scenarios — full builds"), 20 entries apart. Both
explain the golden CSV's empty-`expected` convention.

---

## 3. Gaps, ranked by reader harm

| # | Gap | Harm | Evidence it's missing |
|---|---|---|---|
| **1** | **"Why did it abstain?"** — no troubleshooting page | **Highest.** Abstention is the product's most frequent output and its most confusing. Five distinct causes, five distinct signals, five pages, four sidebar groups, zero index. A reader whose first `ask()` refuses has no path forward and concludes the library doesn't work. | Grep for `troubleshoot` across `site/src/content/docs`: 0 hits. Causes scattered across `signals.mdx:44-50`, `languages.mdx:13`, `reranking.mdx:73`, `ask.mdx:38-51`, `authority.mdx:164`, `scenarios/conflicting-sources.mdx:34-38`. |
| **2** | **No page for failure class 1 — the faithfulness gate itself** | **Highest.** The product's headline result (gate accepted 9/9 adversarial false answers; now per-atomic-claim, order-aware; identical across three ports) exists only as an Aside on the homepage. Meanwhile `concepts.mdx:17` and `index.mdx:136` describe the superseded token-containment predicate as the guarantee. | No file mentions "adversarial". "atomic claim" appears 3×, all in passing (`index.mdx:119`, `contract-review.mdx:67`, `evaluate-a-corpus.mdx:56`). |
| **3** | **No architecture / "how it works" page** | High. There is no diagram or pipeline description anywhere. The closest is a 6-line code block inside `authority.mdx:147-152` showing `retrieve → fuse → rerank → grounded → select_by_authority → generate → gate` — buried on a feature page. A reader cannot form a mental model of where extraction, chunking, embedding, fusion, the gate and the ports sit. | `concepts.mdx` is 87 lines and describes only the 3-step decision, not the system. |
| **4** | **Failure class 5 (silent corpus poisoning) has no discoverable home** | High for operators. The zero-vector bug, fail-closed ingest, "a model failure is not an abstention" — all real, all excellent — sit at `providers.mdx:264-292`, under a heading about writing providers. | Only occurrence of "zero vector" in the docs set. |
| **5** | **No 0.9.0 → 0.10.0 migration note** | High, time-boxed. Three pages still say 0.10.0 is unreleased; nothing says what changed or whether anything breaks. | See §5. |
| **6** | **No API reference** | Medium-high. Signatures are scattered: `ask()` at `ask.mdx:27`, `ingest()` partly at `authority.mdx:94`, `reconcile()`/`remediate()` only inside a Steps block at `regulated-audit.mdx:43-58`, `crawl()` at `bulk-ingest.mdx:38`, `evaluate()` at `evaluate.mdx:12`. No page lists the public surface. | `result.mdx` is the closest and covers only return types — and is stale (§1.B.5–6). |
| **7** | **No comparison against a plain RAG stack** | Medium. The product's whole pitch is "five things a normal stack gets confidently wrong". The site never draws that contrast explicitly. The only comparative number on the site is a parenthetical in `domain-rag.mdx:57-58` (Stanford RegLab 17–33% hallucination). | — |
| **8** | **No "deep" answer strategy page** | Medium. `strategy="deep"` is referenced as an existing capability in `authority.mdx:236`, `providers.mdx:160`, `providers.mdx:321`, and `multilingual-corpus.mdx:101-103` — four pages assume a feature no page documents. | — |
| **9** | **No conformance / parity page** | Medium. The conformance suite is the proof behind "three ports at parity" and is only ever a GitHub link (5 occurrences). The one place parity status is stated (`index.mdx:118-123`) is an Aside on a splash page. | — |
| **10** | **`Result` reference incomplete** | Medium. Missing `unsupported_scripts`, `authority_tier`, `authority_floor_applied`; `conflicts` documented as never-emitted while a scenario page prints it. | `result.mdx:53-64`, `:88-94`. |

---

## 4. Orphans and reachability

**No file orphans.** All 35 non-splash pages appear in the sidebar. But
*link* reachability is poor — inbound internal links, counted across the set:

| Page | Inbound links | Note |
|---|---|---|
| `file-based.mdx` | **0** | Sidebar-only |
| `scope.mdx` | **0** | Sidebar-only. Last item, last group. |
| `domain-rag.mdx` | **0** | Sidebar-only — and it's the legal/medical on-ramp |
| `access.mdx` | 1 | |
| `install.mdx` | 1 | Only from `index.mdx:175` — the quickstart never links it |
| `result.mdx` | 1 | Only from `ask.mdx:35`. The type reference for the whole library. |
| `signals.mdx` | 1 | Governs ingest cost; quickstart doesn't mention it |
| `bulk-ingest.mdx` | 1 | |
| `authority.mdx` | 8 | Best-connected page — correctly so |

Structural consequence: three pages are reachable **only** by scanning a 35-item
sidebar, and one of them (`domain-rag.mdx`) is a stale on-ramp that contradicts a
shipped feature. Nobody links to it, so nobody noticed.

Also: `tableOfContents: false` at `astro.config.mjs:29` removes in-page navigation
site-wide. That is defensible for `quickstart.mdx` (77 lines) and actively harmful
for `providers.mdx` (386 lines, 10 H2s), `authority.mdx` (241/8),
`scenarios/multilingual-corpus.mdx` (202/6) and `languages.mdx` (196/6). Four
pages carry a quarter of the site's content with no way to navigate within them.

---

## 5. The 0.10.0 skew — every occurrence

Identical `<Aside type="caution" title="Requires 0.10.0 — not yet on PyPI or npm">`
blocks, each 4 lines:

1. `site/src/content/docs/authority.mdx:8-11`
2. `site/src/content/docs/providers.mdx:8-11`
3. `site/src/content/docs/scenarios/multilingual-corpus.mdx:8-11`

All three say *"the published packages are still **0.9.0**. Install from source
until 0.10.0 ships."* Tags `v0.10.0` and `golang/v0.10.0` are in the repo. All
three are now false and all three sit **above the fold** on the page that carries
the feature — they are the first thing a reader sees on the authority page, the
provider-contracts page, and the cross-lingual page. No other page carries a
version notice, so there is no established pattern to replace them with.

Related staleness in the same class (structural, not covered by the factual audit's
brief since it's about page *role*):

- `domain-rag.mdx:63-71` — Aside "Know the authority gap before you ship" asserts
  the feature doesn't exist.
- `benchmark-law.mdx:67-69` and `:96-101` — same, twice, on either side of an
  Aside that says the opposite.
- `result.mdx:88-94` — conflicts "not yet emitted", contradicted by
  `scenarios/conflicting-sources.mdx:26-38`.

---

## 6. Titles and descriptions

`description` is what search results and social cards show. Overall quality is
**high** — better than most docs sets. Specific problems:

**Good, keep as-is** (say what the page is *for*, and name the failure):
`authority.mdx` ("A perfectly grounded quote can still come from the wrong law"),
`scenarios/conflicting-sources.mdx`, `scenarios/subject-scope.mdx`,
`scenarios/regulated-audit.mdx`, `providers.mdx`.

**Problems:**

| Page | Issue |
|---|---|
| `languages.mdx` | **72 words.** Truncates in every search result and social card. It is four sentences of specification, not a description. The distinctive fact (14 scripts, citations stay verbatim) is buried behind the port caveat. |
| `custom-endpoints.mdx` | 51 words, two sentences, the second of which is a security argument. Half will be cut. |
| `models.mdx` | Describes a page that shouldn't exist (§2.1); its description overlaps `providers.mdx`'s almost word-for-word on "the seam is a published contract". |
| `scenarios/multilingual-corpus.mdx` | 47 words, opens mid-argument ("The authoritative clause is written in a script the query shares no token with") — no context for a reader arriving cold from search. |
| `scenarios/index.mdx` | Lists all eight scenarios by name — a table of contents, not a description. Says nothing about what the group is *for*. |
| `evaluate.mdx` | "Returns an in-memory `EvaluationReport`" is an implementation detail in the sentence a search engine shows. |
| `scope.mdx` | Says what the page contains, but the page has 0 inbound links and no reason to exist separately from `concepts.mdx`. |
| `file-based.mdx` / `s3.mdx` | Both fine individually; together they describe the same page twice. |

**Titles:** mostly good. Two are wrong for what the page does:
- **"Bring your own models"** (`models.mdx`) and **"Provider contracts — bring your
  own model"** (`providers.mdx`) are the same title. Adjacent in the sidebar.
- **"Regulated audit"** (`scenarios/regulated-audit.mdx`) promises audit trail /
  defensibility; the page is corpus reconciliation only. Retitle "Prove the index
  matches the agreed corpus" or broaden the page.
- **"How it holds the line"** (`concepts.mdx`) is good copy but tells a searcher
  nothing. It is the site's second-most-important page and it is unfindable by
  search intent ("how does citenexus work", "citenexus architecture").

---

## 7. Proposed sidebar

Principle: **lead with the five failures, because that is the product.** Reference
material moves behind them, not in front. 8 groups → 6.

```
Start here
  Quickstart                                    quickstart
  Install — Go, JS, Python                      install            (was: Reference, last group)
  How it works                                  architecture       ★ NEW — pipeline + where each guard sits
  The guarantee, and its limits                 concepts           (rewritten: fix the token-containment framing)

What it stops getting wrong                     ★ NEW GROUP — the product, one page per failure
  1 · The claim that doesn't follow             faithfulness       ★ NEW — the gate, 9/9 adversarial, per-port
  2 · Two sources disagree                      scenarios/conflicting-sources
  3 · The wrong law, quoted correctly           authority
  4 · The document it cannot read               languages          (promoted from "Retrieve & answer")
  5 · A model failed and nobody said so         fail-closed        ★ NEW — extracted from providers.mdx:264-292
  Open gap · Wrong subject, right source        scenarios/subject-scope

Build it
  Ingest anything                               ingest
  Bulk & batch ingest                           bulk-ingest
  Storage — local & S3                          storage            (merge file-based + s3)
  Signals & capabilities                        signals
  Vision — figures as evidence                  vision
  Models & endpoints                            custom-endpoints   (absorb models.mdx, retitled)
  Provider contracts                            providers          (minus the fail-closed section)
  Retrieval & reranking                         reranking
  Graph (GraphRAG)                              graph
  Wiki (navigate-not-cite)                      wiki

Read the answer
  Ask & abstain                                 ask
  The Result object                             result             (+ the 3 missing signals, un-stale conflicts)
  Why did it abstain?                           abstention         ★ NEW — the five causes, keyed to signals
  Evaluate                                      evaluate           (merge scenarios/evaluate-a-corpus)

Operate it
  Access & partitions                           access
  Revoke a document                             revoke
  Corpus reconciliation                         scenarios/regulated-audit  (retitled)
  Right to erasure                              scenarios/right-to-erasure
  Upgrading to 0.10.0                           upgrading          ★ NEW

Worked builds & proof
  Which build?                                  scenarios          (trimmed — 9 cards → 4)
  Contract review                               scenarios/contract-review
  Multilingual desk                             scenarios/multilingual-desk   (dedup against languages)
  Cross-lingual corpus                          scenarios/multilingual-corpus
  Support assistant                             scenarios/support-assistant
  Build a domain RAG                            domain-rag         (rewrite — currently denies authority)
  Worked example: law                           benchmark-law      (resolve the 3-way self-contradiction)
  Conformance & port parity                     conformance        ★ NEW
  Scope — is / is not                           scope              (or fold into concepts and delete)
```

Answering the brief's two probe questions against this shape:

- *"How do I stop it citing the wrong jurisdiction?"* → group 2, item 3, titled
  **"The wrong law, quoted correctly"**. Today: group 5, item 6 of 8, titled
  "Authority — source standing", behind a false unreleased notice.
- *"Can it read Tamil?"* → group 2, item 4, **"The document it cannot read"**, and
  the script matrix is the first section. Today: group 5, item 8 of 8, titled
  "Languages & multilingual", competing with two scenario pages that restate it.

---

## 8. Prioritised plan

### Tier 0 — actively misleading, fix today (≈2 hours, no new pages)

| # | Action | Files |
|---|---|---|
| 0.1 | Delete the three "Requires 0.10.0 — not yet on PyPI" Asides | `authority.mdx:8-11`, `providers.mdx:8-11`, `scenarios/multilingual-corpus.mdx:8-11` |
| 0.2 | Rewrite the authority-gap Aside in `domain-rag.mdx` to point at the shipped floor, and add the missing `authority.mdx` link | `domain-rag.mdx:63-71` |
| 0.3 | Resolve `benchmark-law.mdx`'s three-way self-contradiction — one position, stated once | `benchmark-law.mdx:67-101` |
| 0.4 | Reconcile `result.mdx` conflicts-are-reserved against `scenarios/conflicting-sources.mdx`; add `unsupported_scripts`, `authority_tier`, `authority_floor_applied` to the `EvidenceSignals` table | `result.mdx:53-64`, `:88-94` |
| 0.5 | Fix the token-containment framing of the gate in the two places it appears | `concepts.mdx:17`, `index.mdx:136` |

### Tier 1 — restructure existing pages (≈1 day, no new prose to research)

| # | Action | Effect |
|---|---|---|
| 1.1 | **Apply the proposed sidebar.** Pure config change plus 4 retitles. | Moves authority + languages from buried to primary. Single highest ratio of value to effort on this list. |
| 1.2 | Extract `providers.mdx:264-292` ("Failure must be sayable" + the fail-closed write path) into its own page. | Closes gap #4; failure class 5 becomes discoverable. |
| 1.3 | Merge `file-based.mdx` + `s3.mdx` → `storage.mdx`; delete `models.mdx` into `custom-endpoints.mdx`; merge `scenarios/evaluate-a-corpus.mdx` into `evaluate.mdx`. | 36 → 32 pages, three duplication clusters closed. |
| 1.4 | Dedup the multilingual trio: `languages.mdx` owns the script matrix, the answer-language ladder and the verbatim rule; the two scenario pages link up instead of restating. | Removes ~60 duplicated lines that are already drifting (13 vs 14 scripts). |
| 1.5 | Re-enable `tableOfContents` (globally, or per-page on the four >150-line pages). | One line in `astro.config.mjs`. |
| 1.6 | Rewrite `index.mdx` above the fold around the five failures + the 4→0 / 33%→100% authority numbers; move the four-part parity Aside below "What you get". | Fixes journey A entirely. *(Coordinate — another agent is editing this file.)* |
| 1.7 | Trim descriptions >35 words: `languages.mdx`, `custom-endpoints.mdx`, `scenarios/multilingual-corpus.mdx`, `scenarios/index.mdx`. | Search/social cards stop truncating. |

### Tier 2 — new pages, in value order

| # | New page | Why it's worth writing |
|---|---|---|
| 2.1 | **"Why did it abstain?"** — five causes, the signal each emits, the fix for each | Serves the site's most common unserved reader state. Assembles existing content; needs no new research. |
| 2.2 | **The faithfulness gate** — 9/9 adversarial, per-atomic-claim order-aware predicate, per-port status | The headline claim currently has no page. |
| 2.3 | **How it works** — one pipeline diagram; where extraction, chunking, fusion, gate, authority floor, conflict detection sit | Every other page assumes this mental model; nothing supplies it. `authority.mdx:147-152` is the seed. |
| 2.4 | **Upgrading to 0.10.0** | Time-boxed value; worth doing while 0.10.0 is fresh. Short. |
| 2.5 | **vs. a plain RAG stack** | Highest marketing value, lowest correctness risk — the five failures *are* the comparison. |
| 2.6 | **Conformance & port parity** | Turns 5 raw GitHub links into an argument. |
| 2.7 | **API reference** | Real value but the largest effort and the highest maintenance cost; consider generating it rather than writing it. |
| 2.8 | **`strategy="deep"`** | Four pages already reference it. Low urgency, but it is currently a phantom feature. |

### Honest assessment: which few changes deliver most of the value

Roughly 80% of the improvement is in **five** items:

1. **Tier 0 entirely (2 hours).** Five edits remove every place the docs actively
   mislead a reader — a false "unreleased" banner on the flagship feature, a page
   denying that feature exists, and a reference page contradicting a scenario page.
   Nothing else on this list matters while these are true.
2. **1.1 — the sidebar.** One config file. Converts a sidebar that describes an API
   into one that describes a product, and makes both probe questions ("wrong
   jurisdiction", "can it read Tamil") one click from the top.
3. **2.1 — "Why did it abstain?"** One page, assembled from content that already
   exists, serving the single most common reader failure. Highest value per hour of
   any new page.
4. **1.6 — the homepage.** The evaluator journey currently fails completely; the
   material to fix it (the 4→0 authority numbers, the five failure classes, the
   9/9 adversarial result) is all in the repo and none of it is on the homepage.
5. **2.2 — the faithfulness gate page.** Without it, the product's central claim
   remains an Aside, and two pages continue teaching the superseded predicate as
   the guarantee.

Everything else — the merges, the dedup, the API reference, the comparison page —
is real but incremental. **Do not start Tier 2 before Tier 0 is done**: writing new
pages onto a base where three pages say the flagship feature is unreleased just
adds surface area to the contradiction.
