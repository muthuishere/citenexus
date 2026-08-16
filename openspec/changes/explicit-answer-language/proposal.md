## Why

**This is a BREAKING behavioural change to a PINNED algorithm (SPEC-v6 §11a) with
conformance vectors in `conformance/cases/language.json`. Go, JS and Rust ports
must follow.**

§11 says the answer comes back in the **query's** language. §11a's fallback chain
does not implement that — its fourth rung derives the answer language from the
**retrieved evidence**, which is a different corpus-shaped signal wearing §11's
name.

Measured 2026-08-16 on `examples/multilingual/` (22 questions):

- **8 English questions were stamped `answer_language="te"`**, **7 more `"ta"`**.
  15 of 22 answers claimed a language the asker never used and the generator was
  then instructed to write in.
- The concrete case: *"How many days of unused leave can I carry forward?"* —
  asked in English, answered from the English handbook, stamped `te`, because the
  pooled candidates happened to be Telugu-dominant.

The rung is also about to get worse, not better: `search_languages` fan-out
(ADR-0013) deliberately pulls foreign-language passages into the pool, so the
evidence-dominant language will drift further from the asker's on every fan-out.

The owner's ruling:

> *"i think its better let user send that which language they want rather than
> auto from answer language might not be useful i think unless specified — or try
> a better dumb way than smarter"*

**Explicit beats clever.** The caller states the response language; absent that,
a fixed, predictable default — never an inference from what retrieval happened to
return.

Two further defects measured in the same run, both in the same seam:

- **Refusals blame the wrong thing.** 11 of 14 refusals reported
  `unsupported script: unknown` — including for pure-English questions over an
  English-only pool — because `flow.py` computes a script gap over **every pooled
  candidate** and uses it as the refusal reason before falling through to "no
  sufficiently relevant evidence found". A caller debugging an English corpus is
  told their script is unsupported. That is precisely the conflation ADR-0011
  exists to end, running in the opposite direction.
- **Unreachable authority is answered around.** A Hyderabad employee asking about
  leave carry-forward got *"a maximum of 10 days"* — verbatim from the English
  handbook, correctly cited, 100% groundedness, faithfulness/authority/subject
  scope all passed — while the **Telugu annexure caps it at 5 days and states it
  overrides**. The authoritative document was simply in a script the tokenizer
  does not claim, so a reachable-but-superseded one answered. Nothing in the
  Result said "there is material here I cannot read."

## What Changes

### 1. Answer-language resolution: explicit, with a dumb default (BREAKING)

`resolve_answer_language` becomes a three-rung chain, and the evidence rung is
**removed outright**:

| # | Rung | Note |
|---|---|---|
| 1 | explicit `answer_language` | **now wins over everything, including a reliable detection** |
| 2 | reliable detection of the **question** | reached only via `answer_language="auto"` (or an explicit `detection=`) |
| 3 | established `conversation_language` | unchanged in position, now rung 3 |
| 4 | configured `default_answer_language` | the dumb default |

- `answer_language="ta"` → `"ta"`. Unchanged in effect, **changed in precedence**:
  it no longer loses to a reliable detection.
- `answer_language="auto"` → detect from the **question** via the injected
  detector; an unreliable or absent detection falls to the default, **not** to the
  evidence.
- `answer_language=None` (unspecified) → the configured default. No detection, no
  inference. **This is the breaking change most callers will see.**
- `languages_in_evidence` stays in the signature (ports and vectors keep their
  argument list) and is **ignored**. It remains a reported signal on
  `EvidenceSignals.languages_in_evidence`; it is no longer an input to the answer
  language.

`"auto"` stops being a client-side alias for `None`: `CiteNexus.ask` passes the
sentinel through to the flow, which detects. `AnswerFlow` / `AgenticAnswerFlow`
accept the client's `detector`.

`MultilingualConfig` gains `default_answer_language` (default `"en"`) as the
named knob; the existing `fallback_language` stays as a deprecated alias and
still wins when a caller set it.

**Citations are unaffected.** `SourceRef.passage` stays verbatim in its source
language and is never translated in place (§11, §16). Only the ANSWER language
changes.

### 2. Refusal reasons name the actual cause

`flow.py` stops using the whole-pool script gap as a blanket refusal reason.

- A question in an unclaimed script → still `unsupported script: <scripts>` (the
  gap genuinely explains it — the question cannot be read at all).
- Otherwise the pool is partitioned into **readable** and **script-excluded**
  candidates, and only the script-excluded ones can be blamed:
  - nothing readable was relevant, and candidates *were* script-excluded →
    `no readable evidence found; unsupported script: <scripts of the excluded>`
  - nothing readable was relevant and nothing was script-excluded →
    `no sufficiently relevant evidence found` (unchanged, and now reached in the
    11 cases that previously lied)
- The faithfulness-gate refusal stops borrowing the capability reason: an answer
  that failed the gate failed the gate, whatever else was in the pool.

### 3. Unreachable authority is surfaced, not silenced

`EvidenceSignals.unsupported_scripts` (already a CAPABILITY signal, additive,
empty by default) becomes precisely *"candidate documents in this partition that
I could not read"* on the ANSWERED path, and the answered Result additionally
carries a human-readable line in `missing_evidence` naming the excluded documents
and their scripts. No new Result field; no serialization change for any corpus
without an unclaimed script.

**The answer is NOT downgraded to a refusal.** See `design.md` for the argument
and the two rejected alternatives.

## Impact

- **Affected specs:** `answer-flow-strict` (MODIFIED), `language-detect`
  (MODIFIED).
- **Affected code (this change):** `python/src/citenexus/lang/fallback.py`,
  `answer/flow.py`, `answer/agentic.py`, `client.py`, `config/schema.py`.
- **Affected code (follow-on, other owners):** `conformance/cases/language.json`
  must be regenerated — **3 of the 6 vectors change verdict**, and 3 new ones
  should be added (see `design.md` §
  "Conformance impact"); `golang/` and `js/` port the new chain.
- **Not affected:** `tokenize.py` and `SUPPORTED_SCRIPTS` (a concurrent change
  adds Telugu — it shrinks this failure class but cannot eliminate it: any
  unclaimed script reproduces it), citation verbatimness, `search_languages`.
