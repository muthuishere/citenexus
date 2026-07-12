## ADDED Requirements

### Requirement: Env-placeholder header auth is available in every port

The `${ENV}` header-template auth SHALL be available at parity in each language
port that ships model clients (Python, Go, JavaScript). Each port SHALL provide an
HTTP client that expands `${ENV_VAR}` in the final merged headers at the request
boundary (a missing variable → empty string, values never logged), and each port's
model clients SHALL accept first-class auth/provider headers that hold only the
template. With no headers configured, every port SHALL send exactly
`{"Content-Type": "application/json"}`, preserving the pinned `model_wire`
contract.

#### Scenario: A port resolves a header template at the boundary

- **WHEN** a model client in any port is given `{"Authorization": "Bearer ${KEY}"}` and its HTTP client sends a request with `KEY` set in the environment
- **THEN** the request carries `"Bearer <value>"`, the client's stored header still holds the `"Bearer ${KEY}"` template, and a client configured with no headers sends only `Content-Type: application/json`
