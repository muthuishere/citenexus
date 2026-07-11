## Why

Figures need a vision LLM (VL), but the core must not make the HTTP call: doing so
would force it to re-implement the host's transport (auth, proxy, streaming,
retries, telemetry) and — worse — hold the API key inside the polyglot core,
breaking CiteNexus's standing rule that the **host owns transport + credentials**
and that a secret's value never enters the model/core layer. We need a contract
that keeps every deterministic decision identical across the Go/JS/Python ports
while the raw model call stays host-side. ADR-0005 settled the shape; this change
specifies it. Now, because the vision path just went end-to-end on real documents
(image bytes persisted at ingest + the §9 pre-filter wired in) and the next ports
must copy exactly this behavior.

## What Changes

- Introduce a **two-phase, host-fulfilled vision-orchestration contract**:
  1. **Parse/emit** — the core parses an artifact and returns page-level evidence
     **plus a list of pending vision requests**, each carrying the prepared,
     model-ready payload and the `SourceRef` (document + page + bbox) it belongs to.
     The §9 `decide()` gate runs here, so only `vision`-routed images become requests.
  2. **Host fulfills** — the caller executes those requests with its **own injected
     transport** (its concurrency, auth, mocking), returning one description per
     request id. The core never opens a socket and never sees the API key.
  3. **Assemble** — the descriptions are fed back and the core builds the citable
     `EvidenceUnit(type=figure)`, page + bbox intact.
- **BREAKING (internal seam only):** the ingest pipeline's single "describe images
  inline" step splits into emit → fulfill → assemble. The public `ingest()` still
  fulfills automatically via the injected `vision=` plugin (no caller change); the
  two-phase seam is what the ports and advanced callers bind to.
- **Degrade-to-text on fulfillment failure or absence:** a request that errors or
  is left unfulfilled yields no figure EU and never blocks the rest of ingest —
  identical to the current "no vision plugin" behavior.
- Pin the contract as conformance fixtures so Go/JS reproduce the emit list and the
  assembled figure EUs **byte-identically**, with the transport call as the only
  host-side seam.

## Capabilities

### New Capabilities
- `vision-orchestration`: the two-phase emit-requests → host-fulfills → assemble
  contract; where the §9 gate sits; the pending-request and fulfilled-description
  shapes; the "core never holds the key / never makes the call" invariant; and the
  degrade-to-text-on-failure rule.

### Modified Capabilities
- `ingest-pipeline`: the image path becomes emit → fulfill → assemble rather than a
  single inline describe step; `ask()`/`ingest()` fulfill via the injected `vision=`
  plugin, preserving today's caller-facing behavior.

## Impact

- **Specs:** new `vision-orchestration`; delta on `ingest-pipeline`. Reads on
  `conditional-vision` (the `decide()` gate is reused unchanged, now positioned in
  the emit phase) and `evidence-builder` (figure EU assembly).
- **Code (Python reference):** `ingest/pipeline.py` (`_persist_image_bytes`,
  `_vision_units`) refactors into an emit step + an assemble step; `vision/units.py`
  `build_vision_units()` becomes the assemble half; a new pending-request type carries
  payload + `SourceRef`. `vision/client.py` `OpenAICompatibleVision` becomes the
  reference *fulfiller*, not something the core calls mid-parse.
- **Ports:** Go/JS bind emit + assemble across the FFI seam and implement the thin
  "POST payload → return string" fulfiller in-language (each already has the shim).
- **Contract:** adds conformance fixtures (pending-request list + assembled figure
  EUs). No new runtime dependency; no change to the abstain guarantee; the API key
  stays exclusively in the host's transport call.
