> **Status:** implemented and green (Python-only; ports are core-only with no
> model clients). 601 pytest passed, mypy `--strict` + ruff clean, site builds.

## 1. HTTP boundary — `${ENV}` expansion (red → green)

- [x] 1.1 Failing test: `HttpClient.resolve_headers` expands `${ENV}` at call time; `build_headers` keeps the template; caller dict unmutated — `tests/test_http_client.py`
- [x] 1.2 Failing test: a missing var expands to `""` (`expand_env`, `resolve_headers`)
- [x] 1.3 Add `expand_env()` + `_ENV_RE` and `HttpClient.resolve_headers()`; use it in `HttpClient.__call__` (not `build_headers`, which stays a pure merge)

## 2. First-class client headers (red → green)

- [x] 2.1 Failing test: each of the 4 direct clients holds only the header TEMPLATE (`_headers()` returns it merged with `Content-Type`); no value in `repr(vars(client))` — `tests/test_client_auth_headers.py`
- [x] 2.2 Failing test: an embedding client forwards the template to its transport, and a real `HttpClient` resolves it to the live value at the edge
- [x] 2.3 Add `headers=` to `OpenAICompatibleEmbedding` / `OpenAICompatibleGenerator` / `OpenAICompatibleVision` / `OpenAICompatibleReranker`; merge under `Content-Type`

## 3. Docs + legacy note

- [x] 3.1 Rewrite `custom-endpoints.mdx` to lead with `${ENV}` header templates (direct clients + `HttpEndpoint` + `from_config`); mark `api_key: SecretStr` legacy
- [x] 3.2 Update the `HttpEndpoint` docstring to lead with the header-template pattern
- [x] 3.3 `task check` equivalent green (601 pytest, mypy, ruff); site builds (25 pages)
