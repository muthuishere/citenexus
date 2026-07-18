## 1. Protocol + typed requests

- [x] 1.1 Define `ModelRequest` types in the core (`EmbedRequest`, `GenerateRequest`,
      `RerankRequest`, `VisionRequest`) + the ABI (single polymorphic entry vs per-
      seam — resolve in design).
- [x] 1.2 Emit path: requests carry `${ENV}` header NAMES only; test asserts no
      secret value in any emitted request.

## 2. Host fulfiller + two-direction key safety

- [x] 2.1 Reference host `ModelFulfiller`: expand `${ENV}`, HTTP, return JSON.
- [x] 2.2 Response sanitization: redact echoed `Authorization`/`?key=`/`api_key`/
      known secret substrings before returning to the core.
- [x] 2.3 Red→green: no secret value appears in any core value or log in EITHER
      direction (request emit + response return).
- [x] 2.4 Deterministic fake fulfiller; emit → fulfill → parse runs offline.

## 3. Auth scope + signing hook

- [x] 3.1 Define the named host-side `sign`/`transform` capability for query-param /
      SigV4 providers; core emits unsigned, host signs at the HTTP boundary.
- [x] 3.2 Test: a signing provider is handled host-side; the signing key never
      enters the core.

## 4. Guardrails

- [x] 4.1 `cargo test` + host suites green.
- [x] 4.2 Update `docs/SPEC-PORTS-v1.md` / `rust/README.md`: the two-phase protocol,
      both-direction key safety, header-auth scope + signing hook.
- [x] 4.3 Note follow-ons: migrate generator/embedder/reranker/vision onto the
      protocol, one change each.
