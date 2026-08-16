## 1. Structured single-decision output (NOT provider tool-calling)

- [ ] 1.1 Add a structured JSON decision parse on the EXISTING completion/`answer()`
      path of `answer/generator.py` (OpenAI-compatible) — relevance / next-query
      decisions; `${ENV}` headers as today, no new transport.
- [ ] 1.2 Same on `answer/anthropic.py` behind one seam. No provider function/
      tool-calling machinery; the model does not own control flow.
- [ ] 1.3 Add `FakeToolLLM` returning canned structured decisions deterministically.
- [ ] 1.4 Red→green: a decision is parsed from a plain completion; the fake drives
      it offline; no provider tool API used.

## 2. LoopBudget + the scripted loop

- [ ] 2.1 Add `LoopBudget(max_hops, max_tool_calls, max_evidence_units, timeout_s,
      stop_when="no_new_evidence")` + `AgenticConfig` in `config/schema.py`.
- [ ] 2.2 Implement `AgenticAnswerFlow` in `answer/agentic.py`: retrieve → grade →
      refine → repeat, pooling verbatim EUs, dedup, budget checks between hops, and a
      WHOLE-LOOP `timeout_s` that also bounds the final `generate()` and each tool
      call (not just between hops).
- [ ] 2.3 Red→green: `no_new_evidence` halts deterministically (deterministic
      driver); a hung generate/tool call cannot exceed `timeout_s`; pool dedup works.
      All offline with fakes.

## 3. Per-claim single-EU gate (net-new) + signals

- [ ] 3.1 Build claim decomposition + the per-claim single-EU gate: each claim ⊆
      SOME single EU (reuse `is_supported` as the per-(claim,EU) predicate); reject
      the union reading; unsupported claim → drop or abstain.
- [ ] 3.2 Interrupted partial generation is DISCARDED, not gated-and-emitted; draft
      claims never enter the pool.
- [ ] 3.3 Emit `signals.loop.stop_reason ∈ {no_new_evidence, sufficient, budget,
      timeout}`; wire `Decision.partial`.
- [ ] 3.4 Red→green: a cross-EU stitched claim is rejected; a single-EU claim is
      cited; budget-abstain vs no-evidence-abstain carry different `stop_reason`;
      a timeout never lowers the bar.

## 4. `strategy=` seam + integration

- [ ] 4.1 Add `strategy=` to `client.ask()` — `"strict"` default (unchanged),
      `"deep"` opt-in; honor `GraphConfig.max_hops`.
- [ ] 4.2 Red→green: default is strict and byte-identical to today; `"deep"` runs
      the loop and ends in the gate over verbatim EUs.
- [ ] 4.3 End-to-end deep-ask over a small multi-doc corpus (docs + code) with
      fakes; assert multi-passage pooling beats single-passage on a gather question.
- [ ] 4.4 `task lint` / `typecheck` / `test` green.
