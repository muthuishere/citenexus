# Tasks

## Prerequisite: tokenizer relocation
- [x] Move `tokenize()`/`_TOKEN_RE` from `citenexus.testing.fakes` to `citenexus.tokenize`
- [x] Re-export `tokenize` from `citenexus.testing.fakes` (backward compat, no test churn)
- [x] Update production imports (`answer/verify.py`, `storage/bm25.py`, `retrieve/structure.py`, `smoke/pipeline.py`) to import from `citenexus.tokenize`
- [x] `task check` still green (485 tests incl. 3 new, unchanged behavior)

## Story: Python CLI (reference implementation)
- [x] Write failing tests for `citenexus verify` against fixture-derived (claim, passage) cases, including a multi-citation and a multi-claim case
- [x] Write a cross-impl conformance test asserting the CLI's per-claim verdict matches `AnswerFlow.ask()`'s faithfulness-gate outcome on the same (claim, passage)
- [x] Add `VerifyInput`/`VerifyReport` pydantic models (decoupled from `answer.result`, no EU ids required)
- [x] Implement `citenexus.cli.verify`, calling `citenexus.answer.verify.is_supported`/`has_relevance_overlap` unchanged
- [x] Text and `--format json` report formatters; exit codes 0/1/2
- [x] Wire `[project.scripts] citenexus = "citenexus.cli:main"`
- [x] `task check` (506 passed, 12 skipped; ruff + mypy --strict clean)

## Story: GitHub Action
- [x] `action.yml` (composite): setup-python (SHA-pinned per `ports-ci.yml` convention) + `pip install citenexus` + run `citenexus verify`
- [x] Inputs: `input` (glob), `fail-on-ungrounded` (default true); file-level `::error::` annotations
- [x] A workflow (`verify-gate.yml`) that dogfoods the CLI (installed from this checkout) against `.github/verify-fixtures/dogfood.json` as a real CI gate
- [ ] Follow-up (blocked on the next PyPI release, not on this change): exercise the composite action itself end-to-end once `citenexus verify` is on PyPI — until then it's validated by local bash simulation only (pass / fail / fail-override / malformed / no-glob-match), not a live Actions run

## Deferred (separate follow-up changes, not this one)
- [ ] Go/TS thin `verify` CLI wrappers over the existing `golang/gate`, `js/src/gate` primitives
- [ ] Rust: fold "token gates" into the already-planned v2 FFI migration (SPEC-PORTS-v1 §9) — not a standalone `rust/src/gate.rs`
