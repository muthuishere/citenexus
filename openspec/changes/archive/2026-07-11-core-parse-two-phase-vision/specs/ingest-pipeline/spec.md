## ADDED Requirements

### Requirement: Ingest fulfills vision requests via the injected plugin without changing caller behavior

When a `vision` plugin is configured, `ingest()` (and `ask()` over freshly ingested
content) SHALL internally drive the `vision-orchestration` seam — emit the pending
requests, fulfill them through the injected plugin, and assemble the figure
Evidence Units — with no change to the public call signature. When no `vision`
plugin is configured, ingest SHALL emit no requests and produce no figure Evidence
Units, exactly as today. The injected plugin SHALL be the sole holder of the vision
endpoint's credentials; the pipeline SHALL pass it only `PendingVisionRequest`s.

#### Scenario: ingest() auto-fulfills when a vision plugin is present
- **WHEN** `ingest()` runs on a document with a vision-routed figure and a `vision` plugin is configured
- **THEN** the resulting evidence includes the figure's `EvidenceUnit(type=figure)` and the caller made no extra call

#### Scenario: ingest() without a vision plugin produces no figure units
- **WHEN** `ingest()` runs on the same document with no `vision` plugin configured
- **THEN** ingest completes with no figure Evidence Units and no model call
