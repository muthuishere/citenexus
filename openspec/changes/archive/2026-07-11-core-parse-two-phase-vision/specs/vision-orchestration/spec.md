## ADDED Requirements

### Requirement: Vision is orchestrated in two phases with the host fulfilling the model call

The system SHALL describe figures through a two-phase seam in which the core
**emits** model-ready requests, the **host fulfills** them, and the core
**assembles** the results — the core SHALL NOT open a network connection or invoke
a model itself. Phase one (`emit`) SHALL parse an artifact and return its
page-level evidence together with a tuple of `PendingVisionRequest`s. Phase two
(`fulfill`) is performed by the caller's injected transport and SHALL return one
description per request. Phase three (`assemble`) SHALL join descriptions to
requests by `request_id` and produce the figure Evidence Units. The core SHALL
never receive, store, or emit the fulfiller's credentials.

#### Scenario: The core emits requests instead of calling a model
- **WHEN** an artifact containing a vision-routed figure is parsed in the emit phase
- **THEN** the result includes a `PendingVisionRequest` for that figure and no model call has been made by the core

#### Scenario: Assemble joins descriptions to requests
- **WHEN** the host returns a description for a request's `request_id` and it is passed to the assemble phase
- **THEN** the core produces one `EvidenceUnit(type=figure)` for that request, carrying its `SourceRef` (document, page, bbox)

### Requirement: A pending vision request is self-contained and credential-free

Each `PendingVisionRequest` SHALL carry a stable `request_id`, a model-ready
`payload` (the base64 `image_url` data URI plus the prompt, fully assembled by the
core), and the `SourceRef` (document id, page, bbox) the figure belongs to. The
payload SHALL be opaque to the host beyond "send it and return the text," and SHALL
NOT contain any API key or transport credential. The fulfilled result SHALL be
addressed back to its request solely by `request_id`.

#### Scenario: The payload carries no credential
- **WHEN** a `PendingVisionRequest` is emitted
- **THEN** its `payload` contains the image data URI and prompt but no API key, token, or auth header

### Requirement: The §9 pre-filter gates which images become requests

The emit phase SHALL run the `conditional-vision` `decide()` router per image and
SHALL create a `PendingVisionRequest` only for images routed to
`VisionDecision.vision`. Images routed to `text`, `ocr`, or `skip` SHALL NOT leave
the core as requests and SHALL NOT cause a model call.

#### Scenario: A decorative image never becomes a request
- **WHEN** an image is routed to `VisionDecision.skip` by `decide()` in the emit phase
- **THEN** no `PendingVisionRequest` is emitted for it

### Requirement: Unfulfilled or failed requests degrade to text

A `PendingVisionRequest` that the host does not fulfill, or whose fulfillment
returns an error, SHALL yield no figure Evidence Unit and SHALL NOT fail ingest —
identical to the behavior when no vision fulfiller is configured. Fulfillment
outcomes SHALL be isolated per request: one failed request SHALL NOT prevent
assembling the figure EUs of the requests that succeeded.

#### Scenario: A failed fulfillment does not fail ingest
- **WHEN** the host returns an error for one request and valid descriptions for others
- **THEN** ingest completes, the failed request yields no figure EU, and every succeeding request yields its figure EU

### Requirement: The emitted requests and assembled units are deterministic across ports

For the same artifact and configuration, the tuple of `PendingVisionRequest`s
(including the exact `payload` bytes and `request_id`s) and the assembled figure
Evidence Units SHALL be byte-identical across the Python, Go, and JS ports. Only
the host-side fulfillment (the raw model call) may differ per language. These
SHALL be pinned as conformance fixtures.

#### Scenario: Ports reproduce the emit list byte-for-byte
- **WHEN** the same artifact is parsed by the Python, Go, and JS emit phases
- **THEN** each produces the identical ordered tuple of `PendingVisionRequest`s
