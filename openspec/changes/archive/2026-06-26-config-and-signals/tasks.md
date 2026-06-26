## 1. Signal enum + gate (test-first)

- [x] 1.1 Write failing tests: `Signal` membership is exactly the six; unknown name rejected
- [x] 1.2 Write failing tests: default (no `signals`) resolves to all six; `["embedding","text"]` gates out graph/community/wiki for both ingest-build and ask-query predicates; `requires_slow_path()` false when no slow-path signal declared
- [x] 1.3 Implement `config/signals.py` (`Signal` StrEnum, `SignalSet` resolver, predicates) → green

## 2. Configuration schema (test-first)

- [x] 2.1 Write failing tests for §17 defaults (strict mode; rrf_k=60; top_k=11; lexical_signal=bge_m3_sparse; detect_confidence_threshold=0.50; answer_in_query_language=true)
- [x] 2.2 Write failing test: a representative §17 YAML loads into a fully typed config
- [x] 2.3 Write failing tests: `partition_hierarchy` accepts depth 1, 3, and 4 with arbitrary names
- [x] 2.4 Implement `config/schema.py` (pydantic v2 sub-models per §17 section + `TrustRAGConfig`) → green

## 3. Loader + precedence (test-first)

- [x] 3.1 Write failing test: env override beats YAML file value; document precedence defaults < YAML < dict < env
- [x] 3.2 Implement `config/loader.py` (`from_config` accepting dict | path | mapping, env overlay) → green

## 4. Warn-only validation (test-first)

- [x] 4.1 Write failing tests: divergence from `trustrag.validate.yaml` emits a warning and does NOT raise; missing file ⇒ no warning
- [x] 4.2 Implement `config/validate.py` (`validate_client`, `warnings.warn`) → green

## 5. Gate

- [x] 5.1 `task check` green (ruff + mypy --strict + unit tests); no `# type: ignore` without justification
- [ ] 5.2 Run `openspec validate config-and-signals` (or `status`) clean; ready for `/opsx:apply`
