## 1. Prove the hole (red first)

- [x] 1.1 Red: deep-ask, strict mode, floored policy, only a below-floor EU
      retrievable ⇒ currently ANSWERS from it. The test asserts the refusal.
- [x] 1.2 Red: the same hole through `CiteNexus.ask(..., strategy="deep")` with
      the client's configured policy — proving it is reachable from the public API.

## 2. One selection point, reused (not a second implementation)

- [x] 2.1 Make `select_by_authority` / `tier_of` / `AuthoritySelection` generic
      over a minimal read-only `HasAuthorityMeta` protocol, so the loop's
      `_PooledEvidence` uses the SAME function as `Candidate`
- [x] 2.2 Confirm the protocol exposes `authority_meta` and nothing else —
      authority still structurally cannot read passage text
- [x] 2.3 Confirm the strict flow's behaviour is unchanged (type-level change only)

## 3. Carry the metadata into the loop

- [x] 3.1 Add `authority_meta` to the `search_evidence` tool rows (additive key;
      opaque metadata, not citable text — navigate-not-cite untouched)
- [x] 3.2 Add `authority_meta` to `_PooledEvidence`, defaulting to `""` so a
      scripted tool that omits it reads as unranked

## 4. Apply the floor at pool admission

- [x] 4.1 `AgenticAnswerFlow(authority=...)`, defaulting to `default.v1`/no floor
- [x] 4.2 Gate each hop's rows through `select_by_authority` BEFORE pooling
- [x] 4.3 Red: a withheld EU is never shown to the decision model
- [x] 4.4 Red: a withheld EU consumes no `max_evidence_units` budget
- [x] 4.5 Red: a withheld EU cannot satisfy a claim under the single-EU gate
- [x] 4.6 Red: a withheld-only hop does NOT stop the loop as `no_new_evidence`;
      an already-seen-only hop still does

## 5. Order the pool + populate the signals

- [x] 5.1 Order the pool by descending tier before generation (stable)
- [x] 5.2 Red: a claim supported by two tiers is cited to the higher one
- [x] 5.3 `authority_floor_applied` true iff the floor actually withheld something
- [x] 5.4 `authority_tier` = the WEAKEST tier among cited EUs
- [x] 5.5 Empty pool caused by the floor ⇒ refusal naming insufficient authority,
      with NO generator call

## 6. TrustMode coupling

- [x] 6.1 Red: `normal` withholds nothing, reorders only
- [x] 6.2 Red: `exploratory` ignores authority entirely

## 7. Wire the client

- [x] 7.1 `_deep_ask` passes the existing `self._authority` to `AgenticAnswerFlow`
- [x] 7.2 Red: an `ordered.v1` floor declared in config enforces on
      `strategy="deep"` with no extra ceremony. NOTE: `from_config` takes no
      `embedder`/`generator` (models ride HttpEndpoints), so the test builds the
      policy through `from_config` and hands that same object to a fake-model
      client — the config→policy step and the policy→deep step are both covered,
      just not in one constructor call.

## 8. Prove nothing else moved

- [x] 8.1 `answer/verify.py` and the faithfulness predicate untouched; no
      authority module imports them
- [x] 8.2 `task check` — lint + mypy (src AND tests) + pytest; only ADDED tests
- [x] 8.3 `spikes/library-stress/stress.py` — all four probes still PASS
- [x] 8.4 Conformance fixtures NOT regenerated (no pinned algorithm changed)

## 9. Contradictions found against ADR-0004 / authority-floor

- [x] 9.1 **"A single new selection point"** (ADR-0004, Decision) is now
      literally false as written: `select_by_authority` has three call sites (the
      strict flow, deep-ask admission, deep-ask ordering). What the ADR was
      protecting — ONE implementation of the min-bar, so no copy can drift — is
      intact and is why the function was made generic instead of duplicated. The
      ADR wording should say "a single selection FUNCTION", not "point".

- [x] 9.2 **`authority_tier` is under-specified for multi-source answers.**
      ADR-0004 and the authority-floor design both define it as "the cited
      source's tier name", assuming exactly one cited source — true of the strict
      flow, false of deep-ask, which cites one EU per claim. This change defines
      it as the WEAKEST tier among the cited EUs (an answer's standing is the
      standing of its weakest support). The two definitions agree wherever they
      overlap, but the ADR needs the extension written down before a port
      implements it the other way.

- [x] 9.3 **"The only reachable behaviour change is more abstention"** holds for
      truth but not for COST in the loop. A withheld-only hop no longer stops the
      loop, so a run with a configured floor can spend more hops / tool calls
      than the same run without one. It is bounded by `max_hops`,
      `max_tool_calls` and `timeout_s` exactly as before, and it is unreachable
      with no floor configured — but "strictly fewer answers, nothing else
      changes" is not the whole story once the selection point is inside a loop.

- [x] 9.4 No new fixture drift. `conformance/cases/result_roundtrip.json` is
      already +4 lines from `authority-floor` (its task 7.1); this change adds
      nothing to it and regenerates nothing.
