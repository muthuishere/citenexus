# 0003 — PyPI dist name: `trustrag-ai`

Status: accepted · 2026-07-02

## Context

The natural dist name `trustrag` is already taken on PyPI (ADR-0001 flagged
this and deferred the resolution to "before the first tag"). We need a publish
name now that 0.2.0 is release-ready. The **import package stays `trustrag`**
regardless — hatchling packages `src/trustrag` under whatever dist name we
choose, and the public API (`from trustrag import TrustRAG`) is unaffected.

Availability was checked against the PyPI simple index on 2026-07-02
(`https://pypi.org/simple/<name>/` — HTTP 200 = taken, 404 = free):

| candidate      | status    |
|----------------|-----------|
| `trustrag`     | 200 taken |
| `trustrag-ai`  | 404 free  |
| `pytrustrag`   | 404 free  |
| `trustrag-lib` | 404 free  |

## Decision

Publish as **`trustrag-ai`**.

- **Why `trustrag-ai` over `pytrustrag`:** it keeps `trustrag` as the leading
  token (search, docs, `pip install trustrag-ai` reads naturally) instead of
  mangling the brand with a `py` prefix — a convention that mostly signals
  "port of a non-Python thing", which this is not.
- **Why over `trustrag-lib`:** `-lib` is noise (everything on PyPI is a
  library); `-ai` at least says what domain the project lives in.

Wheel/sdist artifacts are `trustrag_ai-<version>*` (PEP 503 normalization);
the wheel contains the `trustrag/` package. Verified with `uv build`.

## Consequences

- The PyPI **trusted publisher** must be registered under project name
  `trustrag-ai` (GitHub repo + `release.yml` workflow + environment `pypi`)
  before the first `v*` tag is pushed.
- README/quickstart installs read `pip install trustrag-ai` (or
  `uv add trustrag-ai`); imports remain `import trustrag`.
- If `trustrag` ever frees up on PyPI, migrating would be a new decision
  (dist renames are disruptive; default is to stay on `trustrag-ai`).
