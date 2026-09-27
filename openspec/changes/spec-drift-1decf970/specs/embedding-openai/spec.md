## MODIFIED Requirements

### Requirement: API key read from env var, never logged

The plugin SHALL accept `headers` templates such as
`{"Authorization": "Bearer ${ENV_VAR}"}` and pass them unexpanded to the
transport; the transport SHALL resolve `${ENV_VAR}` from the process environment
at request time. The key value SHALL NOT be hardcoded, logged, or stored on the
instance. When no `headers` are configured, the request SHALL be sent without an
`Authorization` header.

#### Scenario: Configured header template flows only through the Authorization header

- **WHEN** `headers={"Authorization": "Bearer ${CITENEXUS_EMBED_API_KEY}"}` is
  configured and `embed(...)` is called
- **THEN** the headers passed to the transport carry the unexpanded
  `Bearer ${...}` template, and the resolved `Bearer <value>` appears only in the
  request the `HttpClient` sends

#### Scenario: No key configured sends no Authorization header

- **WHEN** no `api_key_env` is configured and `embed(...)` is called
- **THEN** the headers passed to the transport contain no `Authorization` key
