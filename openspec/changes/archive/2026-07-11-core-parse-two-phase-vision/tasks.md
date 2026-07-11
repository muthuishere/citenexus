## 1. Domain types (red → green)

- [x] 1.1 Write failing tests for `PendingVisionRequest` (fields: `request_id`, `payload`, `SourceRef`) — frozen, rejects unknown fields, carries no credential field
- [x] 1.2 Add the `PendingVisionRequest` type and the fulfilled-description shape (`{request_id: VisionRecord}`) to the domain layer; make 1.1 green
- [x] 1.3 Add a conformance fixture stub for the emit list + assembled figure EUs (empty expected values, filled in §3)

## 2. Emit phase — core parses and gates (red → green)

- [x] 2.1 Write a failing test: parsing a doc with a vision-routed figure returns a `PendingVisionRequest` with the correct `SourceRef` (page + bbox) and a base64 `image_url` payload
- [x] 2.2 Write a failing test: an image routed to `skip`/`text`/`ocr` by `decide()` emits NO request
- [x] 2.3 Refactor `ingest/pipeline.py::_vision_units` into `_emit_vision_requests` — runs `_persist_image_bytes` + `decide()` + builds the payload + `SourceRef`; return the pending-request tuple. Make 2.1–2.2 green
- [x] 2.4 Assert (test) the emitted `payload` contains the image data URI + prompt and NO api key / auth header

## 3. Assemble phase — descriptions become figure EUs (red → green)

- [x] 3.1 Write a failing test: given `{request_id: VisionRecord}`, assemble produces one `EvidenceUnit(type=figure)` per request with the request's `SourceRef`
- [x] 3.2 Make `vision/units.py::build_vision_units()` the assemble half (join on `request_id`); make 3.1 green
- [x] 3.3 Fill in the conformance fixture (§1.3) with the pinned emit list + assembled EUs

## 4. Degrade-to-text + isolation (red → green)

- [x] 4.1 Write a failing test: one request errors, others succeed → ingest completes, failed request yields no figure EU, others do
- [x] 4.2 Write a failing test: a request left unfulfilled yields no figure EU and does not fail ingest
- [x] 4.3 Implement per-request isolation in assemble; make 4.1–4.2 green

## 5. Wire the reference fulfiller into ingest() (no public-API change)

- [x] 5.1 Write a failing test: `ingest()` with a `vision=` plugin auto-fulfills (emit → fulfill → assemble) and yields the figure EU; without it, no figure EU and no model call
- [x] 5.2 Wrap `OpenAICompatibleVision` as the reference fulfiller (its own concurrency/auth); wire `ingest()`/`ask()` to call emit → fulfill → assemble internally. Make 5.1 green
- [x] 5.3 Assert the pipeline passes the fulfiller only `PendingVisionRequest`s (credentials stay in the plugin)

## 6. Parity fixtures + ports handoff

- [x] 6.1 Add the emit-list + figure-EU conformance fixtures to `conformance/` so Go/JS can assert byte-identical output
- [x] 6.2 Document the FFI seam: ports bind `emit` + `assemble`; each implements the in-language "POST payload → return string" fulfiller
- [x] 6.3 Keep the existing real-doc vision tests green through the whole refactor (regression gate)

## 7. Docs

- [x] 7.1 Update the `vision-orchestration` note in README/CONTENT-COVERAGE if any user-facing wording shifts (public API unchanged; internal seam only)
- [x] 7.2 On archive: fold the delta into `openspec/specs/vision-orchestration/` and `openspec/specs/ingest-pipeline/`
