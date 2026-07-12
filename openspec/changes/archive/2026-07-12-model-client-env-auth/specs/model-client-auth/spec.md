## ADDED Requirements

### Requirement: Header secrets are referenced by environment placeholder

Auth and provider headers SHALL support a `${ENV_VAR}` placeholder syntax whose
value is resolved from the process environment **at the moment a request is sent**
and never earlier. The resolving HTTP client SHALL expand every `${ENV_VAR}` in the
final merged header values for that one request, SHALL treat a missing variable as
the empty string, and SHALL NOT store the resolved value back on any object or emit
it to a log. Header merging (defaults vs per-call) SHALL remain a pure operation
that preserves the unexpanded template.

#### Scenario: A placeholder expands only at the request boundary

- **WHEN** a header value `"Bearer ${API_KEY}"` is carried on a client and a request is sent with `API_KEY` set in the environment
- **THEN** the request is sent with the header resolved to `"Bearer <value>"`, while the client's stored header still holds the unexpanded `"Bearer ${API_KEY}"` template

#### Scenario: A missing variable resolves to empty

- **WHEN** a header references a `${ENV_VAR}` that is not set in the environment
- **THEN** the placeholder expands to an empty string and no error is raised

### Requirement: Model clients accept first-class auth headers

Each direct OpenAI-compatible model client (embedding, generator, vision,
reranker) SHALL accept a `headers` mapping of auth and provider headers and forward
it — unexpanded — to its transport alongside `Content-Type: application/json`. The
client SHALL hold only the header templates, never a resolved secret value, so a
secret's value cannot appear in the client's state or representation.

#### Scenario: A client forwards header templates to the transport

- **WHEN** a model client is constructed with `headers={"Authorization": "Bearer ${KEY}"}` and makes a call
- **THEN** the transport receives the `"Bearer ${KEY}"` template header (expansion is the transport's responsibility) and the resolved value appears nowhere in the client object
