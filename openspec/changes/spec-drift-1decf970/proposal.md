## Why

`openspec/specs/embedding-openai/spec.md` specifies an auth knob that does not
exist. The requirement "API key read from env var, never logged" (R353) reads
*"When an `api_key_env` is configured, the plugin SHALL read the key from that
named environment variable at call time and pass it ONLY in the `Authorization`
header given to the transport"*, its first scenario (R356) is configured with
`api_key_env="CITENEXUS_EMBED_API_KEY"`, and its second scenario (R357) is
triggered by *"no `api_key_env` is configured"*.

There is no `api_key_env` parameter anywhere in the tree. The shipped mechanism is
`headers` templates: `OpenAICompatibleEmbedding(headers={"Authorization": "Bearer
${ENV_VAR}"})` stores only the TEMPLATE (`python/src/citenexus/embed/client.py:49`
and `:56-59`) and forwards it unexpanded — the recording transport asserts
exactly that at `python/tests/test_client_auth_headers.py:58` — while
`HttpClient.resolve_headers` expands `${ENV_VAR}` from `os.environ` at the request
boundary (`python/src/citenexus/http.py:70-74`), the one place a secret is
materialized and never stored back. With no `headers` configured, `_headers()`
returns Content-Type alone (`python/src/citenexus/embed/client.py:65-68`), so no
`Authorization` key is sent.

The code is the design here: the `${ENV}` template seam is deliberately the
transport's, not the client's, so a secret's value never lives on a client
object, a config, a repr, or a log. The spec is what moved.

## What Changes

- **`API key read from env var, never logged` (R353)** — the requirement body now
  specifies the shipped mechanism: the plugin accepts `headers` templates such as
  `{"Authorization": "Bearer ${ENV_VAR}"}` and passes them unexpanded to the
  transport, which resolves `${ENV_VAR}` from the process environment at request
  time. The non-leakage sentence ("SHALL NOT be hardcoded, logged, or stored on
  the instance") and the "no `Authorization` header" clause stay, with the trigger
  corrected to "when no `headers` are configured".
  - its first scenario (R356) becomes **Scenario: Configured header template flows
    only through the Authorization header**: given
    `headers={"Authorization": "Bearer ${CITENEXUS_EMBED_API_KEY}"}`, the headers
    passed to the transport carry the unexpanded `Bearer ${...}` template, and the
    resolved `Bearer <value>` appears only in the request the `HttpClient` sends.
  - its second scenario (R357) keeps its name and expectation ("the headers passed
    to the transport contain no `Authorization` key") and changes only its trigger
    to *no `headers` are configured*.
