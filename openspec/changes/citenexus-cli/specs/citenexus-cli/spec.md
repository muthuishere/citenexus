## ADDED Requirements

### Requirement: A single installable Go CLI exposes core features

The system SHALL provide a `citenexus` command-line binary, written in Go and
static-linked with the Rust engine into one self-contained executable per
platform, that exposes core CiteNexus features from a shell. The initial command
set SHALL include `init`, `config`, `ingest`, `ask`, and `retrieve`, each
supporting a `--json` output mode. `ingest` and `retrieve` SHALL work with no
model configured (lexical); `ask` SHALL require a configured LLM model.

#### Scenario: Ingest then retrieve then ask through the binary

- **WHEN** a user runs `citenexus init`, `citenexus ingest <source>`, and `citenexus retrieve "<q>"` in a folder
- **THEN** the retrieved candidates include the ingested document, and `citenexus ask "<q>"` returns a grounded answer or a refusal — with no separate library install

### Requirement: Distribution is one npm package that fetches a verified binary

The CLI SHALL be installable via a single npm package that downloads the correct
platform binary from GitHub Releases and caches it. The downloader SHALL verify
the binary against a published SHA256 checksum and SHALL refuse to run an
unverified or mismatched binary. Installation SHALL still succeed when the
`postinstall` script does not run (e.g. `--ignore-scripts`, offline install): the
launcher SHALL lazily download on first invocation. A cached binary SHALL be
re-executed without a network call, and an explicit `CITENEXUS_BINARY` path SHALL
bypass downloading entirely.

#### Scenario: A tampered download is refused

- **WHEN** the downloaded binary's SHA256 does not match the published checksum
- **THEN** the CLI refuses to execute it and reports a checksum failure

#### Scenario: Works even when postinstall was skipped

- **WHEN** the package was installed with scripts disabled and the CLI is invoked for the first time
- **THEN** the launcher downloads and verifies the binary on demand, caches it, and runs — with no manual step

### Requirement: Configuration is dual-level and holds no literal secrets

Configuration SHALL resolve with precedence environment → project
`./citenexus.yaml` → global `~/.config/citenexus/config.yaml` → built-in
defaults, discovering the nearest project file by walking up from the working
directory. Secrets SHALL be expressed ONLY as `${ENV_VAR}` header templates that
are resolved at the request boundary; a configuration file SHALL never require a
literal key value, so it is always safe to commit. `citenexus init` SHALL scaffold
a project config and `citenexus config get|set` SHALL edit the global config.

#### Scenario: Project config overrides global, secret stays a template

- **WHEN** a global config sets a default model and a project `citenexus.yaml` overrides it with `headers: {Authorization: "Bearer ${OPENAI_API_KEY}"}`
- **THEN** the project model wins, and the stored config holds the `${OPENAI_API_KEY}` template — the key value appears only in the outgoing request, never in the file

### Requirement: The CLI calls models in a selectable mode

The CLI SHALL select how LLM work is performed from config `mode`. In `api` mode
the CLI SHALL call models directly through its HTTP clients using `${ENV}` header
auth. The design SHALL reserve a `skill` mode in which the CLI emits durable model
requests for an external fulfiller (the agent skill) to answer and resume, without
the CLI holding any credential.

#### Scenario: api mode answers without an external fulfiller

- **WHEN** `mode: api` and an LLM model with an `${ENV}` auth header is configured
- **THEN** `citenexus ask` returns a grounded answer produced by a direct model call, requiring no external fulfillment step
