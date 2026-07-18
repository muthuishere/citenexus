## Context

CiteNexus injects OpenAI-compatible model endpoints; the key must never enter the
Rust core (SPEC-PORTS-v1, ADR-0005). The vision seam already uses a two-phase
emit-request pattern (core emits what it needs, host fulfills, core resumes). This
change promotes that to a reusable protocol. Split from `rust-first-core` per the
2026-07-17 review (that change was too large).

## Goals / Non-Goals

**Goals:**
- One protocol for all remote-model seams; the key held only in the host.
- Key provably out of Rust in **both** directions (request and response).
- Explicit handling of non-header auth (query-param, signing).
- Offline-testable via a fake fulfiller.

**Non-Goals:**
- Migrating any seam onto the protocol (follow-on changes, one per seam).
- Moving deterministic logic (ADR-0006 / `rust-first-core`).
- The core making HTTP calls or holding any credential.

## Decisions

### 1. Two phases, no callback

`core: emit typed request → host: fulfill (HTTP) → core: parse + resume`. Two FFI
crossings, not a callback, honoring SPEC-PORTS-v1's "no callbacks across FFI". The
request is data; the fulfillment is the host's.

### 2. Key out of Rust in both directions

- **Request:** the emitted request carries `${ENV}` header **names**, never values;
  the host expands them at the HTTP boundary.
- **Response:** the host `ModelFulfiller` MUST scrub the response before handing it
  back — strip/redact any echoed `Authorization` header, `?key=`/`api_key` param, or
  known secret substring — because provider 401/debug bodies reflect credentials. A
  test asserts no secret value appears in any core-visible value or log, in either
  direction.

### 3. Explicit auth scope + a signing hook

The base protocol is `${ENV}`-**header** auth. Query-param keys and request-signing
(AWS SigV4 / Bedrock) are handled by the host fulfiller: it may mutate/sign the
core-built request at the HTTP boundary via a named `sign`/`transform` capability.
The core never signs and never holds the signing key. This makes the previously-
unstated non-header path an explicit, testable fulfiller responsibility.

### 4. Reference fulfiller + deterministic fake

Ship a reference host `ModelFulfiller` (expand `${ENV}`, HTTP, scrub) and a
deterministic fake that returns canned JSON, so emit → fulfill → parse runs offline
and the contract is pinned.

## Risks / Trade-offs

- **[Reflected secret in a response]** → response-direction scrub + a test asserting
  no secret in core values/logs.
- **[Signing needs the core-built request + the key]** → the host signs at the HTTP
  boundary; the core emits an unsigned request; the key stays host-side.
- **[ABI shape churn]** → decide single-polymorphic vs per-seam entry before
  migrating any seam.

## Migration Plan

Land the protocol + reference fulfiller + fake + the two-direction key tests.
Migrate no seam here. Follow-on changes move generator/embedder/reranker/vision onto
it, one per change.

## Open Questions

- ABI: one polymorphic `ModelRequest` entry vs. one per seam.
- Whether the signing hook is part of v1 or a fast-follow (lean: define the hook
  now, implement SigV4 when a signing provider is actually wired).
