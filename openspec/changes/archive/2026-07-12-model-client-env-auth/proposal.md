# Proposal — model-client-env-auth

## Why

Configuring a real provider (Jina, OpenAI, a private gateway) needs auth on the
model clients. The pre-existing path materialized the secret VALUE into a config
object: `HttpEndpoint(api_key=SecretStr(os.environ["KEY"]))`. That pulls the key
into the caller's code and the object graph, where it can leak into a stack trace,
a serialized config, a debugger, or an LLM's context window — contrary to the
"a secret's value must never enter context" rule.

Adopt the **toolnexus HTTP pattern**: auth is a header *template*
`"Bearer ${ENV_VAR}"`, and the `${ENV_VAR}` is expanded from the process
environment **at the request boundary only**, never logged, never stored back. The
client object holds the placeholder, not the value. The direct model clients also
get first-class `headers=` so this works without going through `HttpEndpoint`.

## What Changes

- `HttpClient` expands `${ENV_VAR}` in the final merged header values at call time
  (`resolve_headers`), from `os.environ`, a missing var → `""`. `build_headers`
  stays a pure merge; expansion happens only in `__call__`. Header values are not
  logged.
- `OpenAICompatibleEmbedding` / `OpenAICompatibleGenerator` /
  `OpenAICompatibleVision` / `OpenAICompatibleReranker` gain a `headers=` param
  (`${ENV}` templates + arbitrary provider headers), merged under `Content-Type`.
- `HttpEndpoint` docstring + docs lead with the `${ENV}` header pattern; the
  `api_key: SecretStr` path is retained (backward compat) but documented as legacy.
- Docs: `custom-endpoints.mdx` rewritten around header templates.

Scope: Python only — the Go/JS ports are core-only (extract/store/detect) with no
model clients, so there is no port surface for model auth.

## Capabilities

- **New:** `model-client-auth`
- **Modified:** none (additive on the existing clients)

## Impact

Additive and backward-compatible: existing `api_key`/`transport` code keeps
working. The secure header-template path becomes the documented default.
