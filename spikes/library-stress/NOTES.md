# Spike — library-level adversarial stress test

Date: 2026-08-11 · Feeds ADR-0007, ADR-0008, ADR-0009

## Why this shape

The prompt for these ADRs arrived as a client brief about one document set. That
is exactly the wrong frame for a library decision: fixtures drawn from one corpus
prove something about that corpus. So every probe here is synthetic and spans
**five unrelated domains** — legal, finance, medical, operations, physics. If a
probe fails identically in all five, the defect is in the library.

Everything is offline and deterministic: `FakeEmbedding` (hashing vectorizer),
`FakeLLM` (extractive — returns the passage, never invents). No network, no
model, no customer data. The generator *cannot* hallucinate, which matters:
every failure below is the library's, not a model's.

CiteNexus is Python (facade) + Go and JS (core), pinned byte-identical by the
ADR-0006 conformance vectors. Probe A is therefore run against **all three
ports**, because a defect in a pinned algorithm is a defect in the contract, not
in one implementation.

## Run

```
uv run python spikes/library-stress/stress.py                  # Python, all 4 probes
cd spikes/library-stress/ports/go && go run .                  # Go,  probe A
cd js && npm run build && node ../spikes/library-stress/ports/js/probe-a.mjs   # JS, probe A
```

## Results — all four probes FAIL

### Probe A — the faithfulness gate is vocabulary-sound, not meaning-sound

9 adversarial answers, each **false** with respect to its passage, each accepted
as grounded. Identically, in every port:

| Port | accepted false answers |
|---|---|
| Python (`answer/verify.py:73`) | **9 / 9** |
| Go (`golang/gate/gate.go:75`) | **9 / 9** |
| JS (`js/src/gate/gate.ts:32`) | **9 / 9** |

The mechanism is that `is_supported` is `set(answer) ⊆ set(passage)`, and set
containment is closed under two meaning-changing operations:

- **Reordering.** `{tenant, indemnify, landlord}` == `{landlord, indemnify,
  tenant}`. Inverting the parties to an obligation is a token-set identity.
  Caught: role inversion (3 domains), value swap (2), comparator inversion (1).
- **Deletion.** A subset is closed under dropping tokens, and `not` is a token.
  "The employee shall disclose confidential information." is a strict subset of
  "The employee shall **not** disclose confidential information." Caught:
  negation deletion (3 domains).

Every one of these produces an answer that is verbatim-sourced, correctly cited
to a real document, page and bbox — and asserts the opposite of its source. This
is a worse artifact than an ungrounded answer, because every visible signal says
it is trustworthy.

The port parity is the important part. This is not three bugs; it is one
contract that three implementations faithfully reproduce. Fixing Python alone
would *break* conformance. → ADR-0009.

### Probe B — nothing detects contradiction

Two documents asserting mutually exclusive facts (2019 vs 2026 policy; original
vs restated filing; EU vs US dosing guideline). In all three domains:

- `decision` = `answered`
- one side is answered and cited; the other is silently discarded
- `conflicts_detected` = **0**, `Result.conflicts` = **()**
- `distinct_documents` = 2 — the caller is told two documents support this

Which side wins is decided by fusion rank alone. The caller receives a confident,
correctly cited answer with no indication that an equally grounded source in the
same index says the opposite. The `conflicts` fields exist in the public contract
and are never written by any code path. → ADR-0007.

### Probe C — corroboration is inflated by duplicates

One sentence, ingested under five document IDs. Reported: `distinct_documents=5`,
`supporting_sources=5`. Independent facts actually indexed: **1**.

`distinct_documents` is the signal a caller reaches for to judge how well
corroborated an answer is. Five mirrors of one sentence read as five independent
confirmations. → ADR-0007 (same pairwise seam, inverted), ADR-0008 (the drifted
index that produces the mirrors in the first place).

### Probe D — faithfulness is all-or-nothing

Generator returns one faithful sentence plus one fabricated sentence. Result:
`decision=refused`, `claims=0`, `unsupported_claims_removed=0`.

The safe direction — nothing ungrounded escaped, so the headline guarantee holds.
But the supported half was discarded with the unsupported half, and there is no
representable state for "this claim held, that one didn't":
`flow.py:157` emits a single claim covering the whole answer. `Result.claims` and
`unsupported_claims_removed` are shaped for per-claim verdicts that the flow
cannot produce. → ADR-0009.

## What this changes about the ADRs

- **ADR-0009 is now the highest priority**, above conflict surfacing. Probe A is
  the only finding where the library returns a *confidently false, correctly
  cited* answer, and it reproduces in all three ports. Everything else is a
  missing signal; this is a wrong one.
- **ADR-0009 must ship as a versioned predicate across all three ports
  simultaneously**, with new conformance vectors. The existing vectors currently
  pin the hole in place — that is the honest reading of 27/27.
- **ADR-0007's near-duplicate collapse is confirmed as belonging with conflict
  detection**, not as a separate change: Probe B and Probe C are the same pairwise
  comparison over the same top-k, differing only in whether the polarity agrees.
- **The 27/27 does NOT argue for moving the gate to Rust.** All three ports
  agreed perfectly — there was no drift. This is a specification defect (set
  containment is the wrong predicate), and one shared implementation would have
  been exactly as wrong in one place instead of three. ADR-0010 records the
  placement rule that follows from this.
- **ADR-0008 is unvalidated by this spike** and should stay proposed. Probe C
  produces duplicates by ingesting them deliberately; it does not demonstrate
  that indexes drift from an agreed corpus on their own. That needs a different
  spike against real storage, not synthetic fixtures — do not let Probe C be
  cited as evidence for ADR-0008.

## Honest limits

- `FakeEmbedding` is a hashing vectorizer, so retrieval *ranking* here is not
  representative. Probes B and C depend only on what is retrieved and what the
  signals report, not on rank quality — but no conclusion about ranking should be
  drawn from this harness.
- Probe A tests the gate directly, which is the right level: it is a pure
  function and a pinned contract. It says nothing about how often a real model
  would produce these specific answers — only that if one did, nothing would stop
  it.
- Four probes is not coverage. There are almost certainly further meaning-preserving
  subset attacks (quantifier swaps, scope ambiguity, unit dropping) not tried here.
