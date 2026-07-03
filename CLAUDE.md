# CiteNexus — Project Instructions

Evidence-first, multilingual, S3-native RAG library for domains where a wrong
answer is worse than no answer (legal, medical, finance/compliance, enterprise
search). Python library + a runnable example. Answers **only** from retrieved
evidence; refuses or states uncertainty when evidence is weak, missing, or
conflicting. The achievable guarantee is **"no ungrounded claim,"** not "zero
hallucination."

Full reference spec (v6): **`docs/SPEC-v6.md`** — the source of truth for what
behavior ships. This file is *how we build it*; the spec is *what we build*.

---

## How we work

- **Spec-driven, via OpenSpec.** OpenSpec is initialized (`openspec/`, `.claude/`).
  Every capability is one change: `/opsx:propose` → write delta-spec + tasks →
  implement → `/opsx:apply` → `/opsx:archive` (folds the delta into the living
  spec under `openspec/specs/`). OpenSpec owns the spec system — we do **not**
  run a second `docs/specs/` flow alongside it. `docs/` holds only `SPEC-v6.md`
  + ADRs.
- **Test-driven, genuinely.** Red → green → refactor per change. Spec tables are
  fixtures: the §4c rebuild matrix, §9 vision decision table, and §11a language
  cases become tests directly. Tests use **deterministic fakes** (hash-based
  embeddings, evidence-echoing LLM, identity reranker) so the cite-or-abstain and
  faithfulness logic is provable offline and flake-free.
- **No drive-by changes.** Touch only what the current change needs.

## Stack (locked)

- **uv** (env / deps / lock) · **hatchling** build backend · **pytest** (+coverage)
  · **ruff** (lint + format) · **mypy --strict**. `src/` layout. Python ≥ 3.11.
- `pyproject.toml` (PEP 621). Import name `citenexus`.
- **No bundled models.** Embedding / LLM / reranker / vision are injected
  endpoints (OpenAI-compatible). CiteNexus owns orchestration, storage, retrieval,
  fusion, grounding, evaluation.

## Conventions (carried from the reqsume kernel; library-adapted)

- **Taskfile target-first.** Every ritual is a `task` target; safety/env logic
  lives in the Taskfile, not callers. Verbs: `test` / `test:unit` /
  `test:integration` / `lint` / `format` / `typecheck` / `build` / `publish`.
  A separate `Taskfile.local.yml` (own `dotenv:`) holds the Ollama-backed
  `example` env so it can't cross-contaminate.
- **`docs/` + `docs/adr/NNNN-name.md`.** ADRs record *why X over Y* (e.g.
  ADR-0001 = uv/hatchling stack + OpenSpec; ADR-0002 = foundation-first ordering).
- **CI = GitHub Actions:** `on: pull_request` from day one; third-party actions
  pinned to commit SHAs (not floating tags); publish job `needs: test`.
- **Release:** semver, tag → build → **PyPI via OIDC trusted publishing**,
  CHANGELOG. (No precedent in the kernel — this repo sets it.)
- **Commits:** loose Conventional Commits (`feat:`/`fix:`/`docs:`/`chore:`),
  trunk-based, short-lived branches off `main`, squash-merge.
- **Never** add `Co-authored-by:` to commits. Never read/commit `*.env` or
  secrets; never echo secret values.

## Local infra (`compose.yaml`)

A local **MinIO** is the S3 backend for the storage layer (L2+), the example, and
the opt-in integration tests. `task local:minio:up` starts it and auto-creates the
bucket: S3 API `:19000`, console `:19001` (`minioadmin`/`minioadmin`), bucket
`citenexus-local` (high ports isolate it from any other MinIO on 9000). Images
pinned by digest. Env template in `.env.example` (`CITENEXUS_S3_ENDPOINT_URL`,
`AWS_*`, model base-urls). Unit tests stay hermetic (fakes) and need nothing
running; only integration/example touch MinIO + Ollama.

## Example (`example/`)

Small **multilingual** corpus (a couple PDFs + a `.txt` + one figure image),
config → **MinIO** (S3) + **local Ollama** (bge-m3 + qwen2.5 + bge-reranker-v2-m3),
`golden.csv`. `task local:example` runs ingest → ask → evaluate and prints the
grounded answer + bbox sources + score. Doubles as the README quickstart and the
single opt-in integration test (`@pytest.mark.integration`).

---

## Build plan — foundation-first (chosen ordering)

Each L is one or more OpenSpec changes, built test-first, then archived.

- **L0 — Scaffold:** uv + pyproject + Taskfile(+local) + ruff/mypy/pytest + CI
  (PR-triggered, SHA-pinned) + release(OIDC) + `docs/SPEC-v6.md` + ADR-0001/0002
  + this file. (Per kernel: AGENTS.md is normally canonical with CLAUDE.md a thin
  pointer — for now CLAUDE.md is the single canonical project doc, by request.)
- **L1 — Core domain (pure, exhaustively unit-tested):** `core-domain-types`
  (EvidenceUnit, variable-depth PartitionPath, Result/Provenance/EvidenceSignals,
  trust modes) · `config-and-signals` (`signals=[…]` capability gate + warn-only
  `citenexus.validate.yaml`) · `plugin-protocol-registry` (11 typed ABCs +
  registry + `rag.use()`) · `provenance-and-rebuild` (artifact stamps + partial-
  rebuild planner = §4c matrix).
- **L2 — Storage & runtime:** `storage-partition-seam` (S3 + manifests + leaf-
  LanceDB resolution; local-fs/MinIO test backend) · `worker-queue-resume`
  (durable queue, retry/backoff, DLQ, idempotent-by-hash, resume) ·
  `telemetry-cost` (one event stream, two views) · `access-prefilter`
  (scope→partitions, `allowed_partitions` hard pre-filter, `acl` carried-not-
  enforced) · **`smoke-e2e`** (stub ingest→vector→ask over fakes, kept green by
  every later layer — the mitigation for foundation-first drift risk).
- **L3 — Ingest & extraction:** `ingest-pipeline` (universal intake:
  files/prefix/raw, sync+async, signal-gated, idempotent) · `extractors`
  (pdf/docx/pptx/html/md/txt/csv/image+OCR/plain + unknown→plain fallback) ·
  `conditional-vision` (pre-filter + 3-way decision) · `evidence-builder` +
  `structure-index` (best-effort; "no structure → empty, not failure") ·
  `language-detect` (fastText lid.176 + threshold + fallback chain).
- **L4 — Embedding, retrieval, fusion:** `embedding-bge-m3` (dense+sparse,
  batched) · `vector-store-lance` · `retrievers` (v0.1: vector + sparse-lexical +
  structure) · `rrf-fusion-rerank` (k=60, rerank seam, navigate-not-cite resolve-
  down-to-EU invariant).
- **L5 — Answer, verify, eval (the guarantee):** `answer-flow-strict` (temp-0
  grounded, per-claim faithfulness gate, cite-or-abstain, structured signals,
  conflict surfacing, **answer-language invariant** regenerate-on-mismatch,
  citations verbatim) · `evaluate-and-judge` (`evaluate(csv)` front door +
  groundedness/citation/refusal/per-language metrics + append-only audit + offline
  judge baseline). **→ ship `0.1.0` to PyPI** once L5 + `example/` are green.
- **L6 — v0.2/v0.3 breadth (later):** graph (extractor/resolve/lance/traverse/
  Leiden community) · wiki (distill/index/store/lint, navigate-not-cite) ·
  streaming (token / sentence-gated) · conversation memory (partition/acl-scoped)
  · MCP server · online judge · synthetic/drift · external-store authorization
  enforcement · agentic loop.

### Public API target (DHH-style, three verbs)

```python
from citenexus import CiteNexus
rag = CiteNexus("s3://my-bucket", signals=["embedding", "text"])  # signals gate ingest+ask
rag.ingest()                                                     # any type; sync, or ingest_async
answer = rag.ask("Can the employee disclose this?")             # strict default; answer in query language
score = rag.evaluate("golden.csv")                               # scored, audited
```

`retrieve()` (documents only) is the public engine under `ask()` — the eval
surface and the small-model escape hatch.

## Open decisions to resolve at L0

- **PyPI dist name** — `citenexus` may be taken; pick a fallback dist name if so
  (import stays `citenexus`).
- **fastText `lid.176`** (~126 MB) is a vendored asset behind
  `LanguageDetectorPlugin` — fetch on first use / cache, not a pip dep.
