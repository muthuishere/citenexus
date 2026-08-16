## Why

Remote-model seams (generator, embedder, reranker, vision, distillers) each make an
authenticated HTTP call. As more deterministic logic consolidates (ADR-0006), the
orchestration around those calls wants to be shared — but the **API key must never
enter the Rust core** (SPEC-PORTS-v1; ADR-0005 vision design). The vision seam
already solved this with a two-phase emit-request pattern; this change **defines
that pattern as a first-class protocol** so any seam can reuse it, with the key
held only in the host. Split out of `rust-first-core` (which the review found too
large) so it is independently reviewable.

## What Changes

- **New: the two-phase model-fulfiller protocol.** The core builds and **emits** a
  typed model request (`EmbedRequest` / `GenerateRequest` / `RerankRequest` /
  `VisionRequest`); the host **fulfills** it — expands `${ENV}` creds, does the
  HTTP, returns JSON — and the core resumes. Two phases, **no FFI callback**.
- **Key never crosses the FFI, both directions.** Emitted requests carry `${ENV}`
  header **names**, never values (request direction). The host `ModelFulfiller`
  MUST also **sanitize the response** before returning it to the core — provider
  error/debug bodies can echo the `Authorization` header or a `?key=` param, so a
  reflected secret must be scrubbed, never re-entering a core value or log.
- **Auth scope is explicit.** The protocol covers `${ENV}`-**header** auth. Providers
  needing query-param keys or request-signing (AWS SigV4 / Bedrock) are handled by
  the host fulfiller (which may sign the core-built request at the HTTP boundary);
  the core never signs and never holds the signing key. Signing support is a named,
  explicit fulfiller capability, not an unstated gap.
- **New: a reference host fulfiller + a deterministic fake** so the protocol runs
  offline and the contract is pinned by tests.
- Per-seam migration (generator/embedder/reranker/vision onto the protocol) is
  **out of scope** — follow-on changes, one per seam, reusing this contract.

## Capabilities

### New Capabilities
- `model-fulfiller`: the two-phase emit-request protocol for remote-model seams —
  typed core-emitted requests, a per-host fulfiller holding `${ENV}` creds, request-
  and response-direction key sanitization, explicit header-auth scope + a signing
  hook, a reference fulfiller, and a deterministic fake.

## Impact

- **Depends on ADR-0006** (establishes that this protocol is orthogonal to where
  deterministic logic lives).
- **Rust core:** the `ModelRequest` types + ABI (single polymorphic entry vs. one
  per seam — resolve in design).
- **Hosts:** a thin `ModelFulfiller` per language (~30 LOC) that expands `${ENV}`,
  does the HTTP, and scrubs the response.
- **Security:** the change's whole point — key provably out of Rust in both
  directions; reflected-secret path closed; signing path named, not hidden.
- **0.x:** additive; establishes the contract, migrates no seam yet.
