## ADDED Requirements

### Requirement: Remote-model calls use a two-phase emit-request protocol

Remote-model interactions SHALL follow a two-phase protocol: the Rust core builds
and **emits** a typed model request (`EmbedRequest`, `GenerateRequest`,
`RerankRequest`, `VisionRequest`); the host **fulfills** it (performs the HTTP) and
returns the response as JSON; the core then parses it and resumes. There MUST be no
FFI callback — the two phases replace it. This change defines the protocol and a
reference fulfiller; each seam migrates onto it in follow-on work.

#### Scenario: The core emits a request and resumes on the response

- **WHEN** an operation needs a model call
- **THEN** the core emits a typed request instead of calling the network itself
- **AND** after the host returns the response JSON, the core parses it and resumes
  with no callback across the FFI

### Requirement: The API key never crosses the FFI in either direction

An emitted request MUST carry `${ENV}` header **names**, never secret values, and
the host MUST expand them only at the HTTP boundary (request direction). The host
`ModelFulfiller` MUST **sanitize the response** before returning it to the core —
redacting any echoed `Authorization` header, `?key=`/`api_key` parameter, or known
secret substring — so a reflected credential never enters a core value or log
(response direction). No secret value SHALL appear in any emitted request, core
value, or log.

#### Scenario: An emitted request contains no secret value

- **WHEN** the core emits a request requiring authentication
- **THEN** the request references the credential by `${ENV}` name only
- **AND** the host expands it at the HTTP call

#### Scenario: A reflected secret in a response is scrubbed

- **WHEN** a provider returns an error body echoing the auth header or key param
- **THEN** the host fulfiller redacts it before returning to the core
- **AND** no secret value appears in any core value or log

### Requirement: Auth scope is explicit, with a host-side signing hook

The base protocol SHALL cover `${ENV}`-header auth. Query-param keys and request-
signing (e.g. AWS SigV4 / Bedrock) SHALL be handled by the host fulfiller via a
named `sign`/`transform` capability that may mutate the core-built request at the
HTTP boundary. The core MUST NOT sign requests or hold a signing key.

#### Scenario: A signing provider is handled host-side

- **WHEN** a provider requires request signing
- **THEN** the host fulfiller signs the core-built request at the HTTP boundary
- **AND** the signing key never enters the core

### Requirement: A reference fulfiller and a deterministic fake exist

The change SHALL provide a reference host `ModelFulfiller` and a deterministic fake,
so the protocol is exercisable offline and the contract is pinned by tests.

#### Scenario: The protocol runs offline with the fake fulfiller

- **WHEN** an operation runs with the fake fulfiller
- **THEN** the emit → fulfill → parse cycle completes with no network access
