# 0003 — Product name: `citenexus` (was TrustRAG)

Status: accepted · 2026-07-02 (supersedes the earlier `trustrag-ai` decision
made the same day)

## Context

The project was built as **TrustRAG**, but the dist name `trustrag` is taken on
PyPI by an unrelated, established project — gomate-community/TrustRAG (~1.3k
GitHub stars, a component-style RAG framework from a Chinese research lab).
The first resolution was to publish as `trustrag-ai` while keeping import
`trustrag`. That left two real problems:

1. **Import collision** — their package also ships the `trustrag` module;
   installing both breaks the environment.
2. **Brand shadow** — every search for "trustrag" lands on a 1.3k-star project
   that is not us, forever.

Pre-first-publish was the last cheap moment to fix the name properly.

## Decision

Rename the product to **`citenexus`** — dist name, import package
(`from citenexus import CiteNexus`), Rust crate (`citenexus-core`), C-ABI
symbol prefix (`citenexus_*`), env-var prefix (`CITENEXUS_*`).

Why this name:

- **It names the differentiator**: the cite-or-abstain gate — citations routed
  to verbatim evidence are the product.
- **toolnexus family**: the author's toolnexus established the `*nexus`
  pattern (a small engine that unifies X); citenexus unifies citations.
- **Fully virgin** (verified 2026-07-02): PyPI 404, npm 404, crates.io 404,
  `citenexus.dev` unregistered, no existing project or company by the name —
  unlike `trustnexus`, whose `.com`/`.ai` are held by an existing entity.
- **One name on every registry** — the planned Go/TS ports publish under the
  same brand (`citenexus` on npm, `citenexus-core` on crates.io).

## Consequences

- `pip install citenexus` / `from citenexus import CiteNexus`.
- The PyPI **trusted publisher** must be registered under project name
  `citenexus` (GitHub repo + `release.yml` workflow + environment `pypi`)
  before the first `v*` tag is pushed.
- The GitHub repo should be renamed `muthuishere/citenexus` before launch
  (GitHub redirects the old URL). The local `.vsync` identity pin keeps
  `repo=muthuishere_trustrag` until the vault is deliberately migrated.
- Rejected alternatives: `trustrag-ai` (collision + shadow remained),
  `trustnexus` (existing entity holds `.com`/`.ai`), `verirag`/`citerag`
  (suffix-style, weaker than the toolnexus family pattern).
