## Context

CiteNexus is a polyglot library: Python is the reference; Go/JS (and the Rust
`citenexus-core` cdylib beneath them) must behave identically. Figures are
described by an injected vision LLM. Today the Python ingest pipeline calls the
`VisionPlugin` inline (`ingest/pipeline.py::_vision_units` → `vision/units.py`),
which is fine for one language but forces every port to either re-implement the
transport or make the core hold credentials. ADR-0005 (`docs/adr/0005-*`) settled
the architecture; this design turns it into a testable contract. Constraints:
the API key must never enter the core; deterministic decisions must be
byte-identical across ports; the abstain/grounding guarantee is untouched.

## Goals / Non-Goals

**Goals:**
- A two-phase seam — **emit** (core) → **fulfill** (host) → **assemble** (core) —
  where the host makes every model call with its own transport.
- The API key lives only in the host's fulfiller; it is structurally impossible
  for the core to log or leak it.
- The §9 `decide()` gate (`conditional-vision`) sits in the emit phase, unchanged,
  so decorative/OCR images never become requests.
- Deterministic parity: the pending-request list and the assembled figure EUs are
  pinned as conformance fixtures; only the raw "POST payload → return string" call
  differs per language.
- `ingest()`/`ask()` keep today's caller-facing behavior — they fulfill
  automatically via the injected `vision=` plugin.

**Non-Goals:**
- Migrating the whole deterministic parse (page-splitting, table extraction) into
  the Rust core — that is the broader ADR-0005 direction, tracked separately; this
  change specifies only the vision-orchestration seam (reference impl in Python,
  contract fixtures for the ports).
- Streaming vision, batching heuristics, or a new VL provider.
- Changing `decide()`'s routing logic or the figure-EU citation shape.

## Decisions

**D1 — Two-phase emit/fulfill/assemble, not core-makes-the-call, not a callback.**
Ranked in ADR-0005 as two-phase > FFI-callback > core-makes-call.
- *Core-makes-the-call (rich config struct in)* — rejected: core re-implements the
  host transport and holds the key.
- *FFI callback (core invokes a host function-pointer mid-parse)* — viable, keeps
  the key host-side, but adds function-pointer plumbing across three bindings with
  GC-liveness / thread-safety / reentrancy gotchas.
- *Two-phase emit-requests* — chosen: plain data in/out across FFI, no callbacks,
  host owns the calls, key never crosses in, naturally batch-parallel.

**D2 — Request/description shapes.** A `PendingVisionRequest` carries: a stable
`request_id`, the model-ready `payload` (the base64 `image_url` data URI + prompt
already assembled by the core), and the `SourceRef` (document id + page + bbox) the
figure belongs to. Fulfillment returns `{request_id: description}` (a
`VisionRecord` per id). The core assembles figure EUs by joining on `request_id`;
the payload is opaque to the host beyond "POST it, return the text."

**D3 — The fulfiller is the injected `vision=` plugin.** In Python, the reference
fulfiller wraps `OpenAICompatibleVision`: given the pending requests it runs them
(its own concurrency + auth) and returns descriptions. `ingest()`/`ask()` call it
automatically, so no public-API change. Advanced callers (or a host in another
language) can drive emit/fulfill/assemble by hand.

**D4 — Degrade-to-text.** A request that errors, times out, or is never fulfilled
produces no figure EU and never fails ingest — byte-identical to the current
"no vision plugin configured" path. Fulfillment errors are per-request, isolated.

**D5 — Where `decide()` sits.** Unchanged logic, moved to the emit phase: the core
runs `decide()` per image and only `VisionDecision.vision` images become
`PendingVisionRequest`s. `text`/`ocr`/`skip` never leave the core.

## Risks / Trade-offs

- **[Two FFI round-trips per artifact instead of one]** → Acceptable; it also
  enables the host to fulfill all of a document's requests in parallel. The extra
  crossing carries plain serialized data, not callbacks.
- **[Ports could drift on the payload string]** → Pin the exact payload bytes
  (data-URI encoding + prompt) in conformance fixtures; the fulfiller only
  transports it, so drift is caught at the fixture, not at runtime.
- **[A host might log the payload, which contains the image]** → Document that the
  payload is image content (not a secret) and that the key stays in the host's own
  transport config; the core neither receives nor emits the key.
- **[Refactor could regress the just-shipped end-to-end path]** → TDD: keep the
  existing real-doc vision tests green through the emit/assemble split before
  adding the two-phase seam tests.

## Migration Plan

1. Add `PendingVisionRequest` + the fulfilled-description shape to the domain types.
2. Split `_vision_units` into `_emit_vision_requests` (parse + `decide()` + build
   payload + `SourceRef`) and `_assemble_vision_units` (join descriptions → figure
   EUs); `build_vision_units()` becomes the assemble half.
3. Wrap `OpenAICompatibleVision` as the reference fulfiller; wire `ingest()`/`ask()`
   to call emit → fulfill → assemble internally. No public-API change.
4. Add conformance fixtures (pending-request list + assembled figure EUs).
5. Ports (Go/JS) bind emit + assemble and implement the in-language fulfiller.

Rollback: the split is internal; reverting to the inline `_vision_units` restores
prior behavior with no data-format change (figure EUs are unchanged on disk).

## Open Questions

- Should the pending-request payload be provider-shaped (OpenAI `image_url`) in the
  core, or provider-neutral with the fulfiller adapting? Leaning provider-shaped
  (OpenAI-compatible is the injected-endpoint contract already), revisit if a
  non-OpenAI VL fulfiller appears.
- Batch granularity for fulfillment (per-image vs per-document) — a host concern;
  the contract stays per-request so either works.
