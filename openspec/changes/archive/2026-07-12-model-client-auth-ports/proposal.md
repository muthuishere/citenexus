# Proposal — model-client-auth-ports

## Why

`model-client-auth` (the `${ENV}` header pattern) shipped in the Python reference,
but the Go and JavaScript ports had no HTTP client and no way to attach auth
headers — the model clients sent only `Content-Type`, and auth was "the endpoint
layer's job" that was never ported. A secret-handling security feature must hold
at parity in every port, not just the reference.

## What Changes

- **Go** (`golang/models`): new `HTTPClient` (real `net/http` transport) with
  `ExpandEnv` + `ResolveHeaders` that expands `${ENV}` at the request boundary;
  `WithHeaders(...)` functional option adds first-class auth headers to
  `NewOpenAIChatGenerator` / `NewOpenAIEmbedding` / `NewAnthropicGenerator`
  (variadic, backward-compatible). `wireHeaders` sends `Content-Type` + templates.
- **JavaScript** (`js/src/http.ts`): new `HttpClient` (`buildHeaders` /
  `resolveHeaders` + async `send` via `fetch`) and `expandEnv`; `headers?` on the
  `OpenAIChatConfig` / `OpenAIEmbedConfig` / `AnthropicConfig`, sent via
  `wireHeaders`. Exported from the package root.
- With no headers configured, every port sends exactly
  `{"Content-Type": "application/json"}` — so the pinned `model_wire` conformance
  is unchanged.

## Capabilities

- **Modified:** `model-client-auth` (add a port-parity requirement)

## Impact

Additive and backward-compatible in both ports (variadic option in Go, optional
config field in JS). Go `go test` + `vet` + `gofmt` clean; JS `tsc` + vitest green;
Python unchanged.
