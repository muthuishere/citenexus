# 0001 — Python stack and spec system

Status: accepted · 2026-06-26

## Context

CiteNexus is a new standalone **Python** library (the owner's documented kernel is
Go + React + Bun; it carries **no** Python tooling, packaging, or library-publish
precedent — so these decisions set precedent rather than match it). We want a
spec-driven, test-driven build that publishes to PyPI.

## Decision

- **Tooling:** `uv` (env/deps/lock) + `hatchling` build backend + `pytest`
  (+coverage) + `ruff` (lint+format) + `mypy --strict`. `src/` layout. Venv pinned
  to **Python 3.12** (`.python-version`) for wheel coverage of later heavy deps
  (lancedb, fasttext); `requires-python = ">=3.11"`.
- **Spec system:** **OpenSpec** (`openspec/`). Each capability is a change
  (`proposal → apply → archive`); the living spec accretes under `openspec/specs/`.
  The verbatim reference is `docs/SPEC-v6.md`. We do **not** run a second
  `docs/specs/in-progress→published` flow alongside OpenSpec.
- **Conventions carried from the kernel (language-agnostic):** Taskfile
  target-first; `docs/adr/NNNN-name.md`; CI `on: pull_request` from day one with
  third-party actions pinned to commit SHAs and publish `needs: test`; loose
  Conventional Commits; trunk-based + squash-merge.
- **Publishing (new precedent):** semver, tag → build → **PyPI via OIDC trusted
  publishing**, CHANGELOG. The dist-name `citenexus` is taken on PyPI; the publish
  name gets resolved (likely a suffix) before the first tag — import package stays
  `citenexus`.

## Consequences

- A new contributor runs `task setup` then `task check` and is productive.
- The kernel gives no Python/publish template, so this ADR is the baseline future
  Python repos can copy.
