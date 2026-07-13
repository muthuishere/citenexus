# Tasks

## Story: Python CLI (reference facade)
- [ ] Write failing tests: a grounded claim over a temp evidence dir → CITED with source span; a fabricated "This is real" claim → ABSTAIN with uncovered tokens
- [ ] Write a conformance test: `cite-check` strict verdict matches `is_supported(claim, passage)` on a one-file dir
- [ ] Add `cite_check` module: walk dir → `extract.dispatch` per file → passages; score by `content_tokens` coverage; select best passage; strict `is_supported` gate + `--min-coverage` relaxation
- [ ] `CiteCheckReport` pydantic model (verdict / coverage / min_coverage / sources[file,block,page,passage] / uncovered_tokens)
- [ ] Text + `--format json` formatters; exit codes 0 (CITED) / 3 (ABSTAIN) / 2 (setup error)
- [ ] Wire `cite-check` subcommand into `citenexus.cli:main`
- [ ] `uv run pytest -m "not integration"` green (baseline 589 + new)
- [ ] `ruff` + `mypy --strict` clean

## Story: Complementarity glue (proven, not claimed)
- [ ] `scripts/cite-check-to-brain.sh` — run cite-check --format json, record verdict as a brain episode (`brain record` with reward = CITED:+1 / ABSTAIN:-1); test against a temp `brain --repo` and assert the episode is recallable
- [ ] Document the huddle-verifier interface: the JSON verdict object is the evidence artifact the huddle consumes
- [ ] Document the CEO pre-"done" gate: `cite-check ... || echo "BLOCKED: ungrounded"` on exit 3

## Deferred (follow-up changes)
- [ ] Vector-backed retrieval variant over the same seam (needs embedding endpoint; not hermetic)
- [ ] Go/JS/Rust `cite-check` binaries over existing `gate` primitives
