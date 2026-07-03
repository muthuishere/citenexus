## Context

Config and the signal gate are L1 foundation consumed by every later layer. The v6 spec
mandates a tiny public surface (§15) where `signals=[...]` is the one knob most clients
touch, plus a large but fully-defaulted configuration surface (§17). There is no pipeline
behavior here — only typed config, the signal-capability gate, and an optional warn-only
validation contract. Stack: Python ≥3.11, pydantic v2, mypy --strict.

## Goals / Non-Goals

**Goals:**
- One typed, fully-defaulted configuration model for the §17 surface.
- A `Signal` enum + gating predicates that ingest and ask consult to build/query only
  declared signals.
- A loader with deterministic dict/YAML/env precedence and a `from_config(...)` front door.
- A warn-only validation pass against `citenexus.validate.yaml` (never raises).

**Non-Goals:**
- Executing any ingest/retrieval/answer behavior (later layers).
- Enforcing the validation allow-list (it is advisory by design).
- Implementing the plugins themselves (only the config that selects/points at them).

## Decisions

- **Modules:**
  - `config/schema.py` — pydantic v2 `BaseModel` sub-models per §17 section, composed into a
    top-level `CiteNexusConfig`. Defaults live on the fields so a bare config is valid.
  - `config/signals.py` — `Signal(StrEnum)` with the six members; a `SignalSet` resolver
    (None ⇒ all six) and the predicates `builds_on_ingest(signal)` /
    `queried_on_ask(signal)` / `requires_slow_path()` (true iff any of graph/community/wiki).
  - `config/loader.py` — `from_config(source)` accepting dict | path | mapping + env overlay;
    precedence **defaults < YAML file < dict < environment** (later wins).
  - `config/validate.py` — `validate_client(config, validate_path)` → emits `warnings.warn`
    on divergence, returns the (unchanged) config; no-op when path is absent.
- **Signal gating semantics:** `text` and `embedding` drive the fast path; `graph`,
  `community`, `wiki` drive the slow path; `structure` is fast-path best-effort. The gate is
  the single place these phase mappings live, so ingest/ask never hard-code them.
- **StrEnum over plain Enum** so config round-trips to/from YAML/JSON as plain strings.
- **YAML parsing:** prefer stdlib-only where possible; if PyYAML is introduced it is the lone
  added runtime dep and is justified in the change that needs file loading.

## Risks / Trade-offs

- [Over-broad config surface invites drift between schema and §17] → Keep field names 1:1
  with §17 keys and add a scenario that loads a representative §17 YAML so drift fails a test.
- [Warn-only validation can be ignored] → That is intentional (§15: a warning contract, not
  enforcement); documented and tested so nobody "upgrades" it to an error.
- [Env-override precedence is easy to get wrong] → Pin it in a scenario (env beats file).

## Open Questions

- Whether to ship a JSON-Schema export of the config for editor support (defer).
