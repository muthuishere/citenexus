# Tasks

## Prerequisite: tokenizer relocation
- [ ] Move `tokenize()`/`_TOKEN_RE` from `citenexus.testing.fakes` to `citenexus.tokenize`
- [ ] Re-export `tokenize` from `citenexus.testing.fakes` (backward compat, no test churn)
- [ ] Update production imports (`answer/verify.py`, `storage/bm25.py`, `retrieve/structure.py`, `smoke/pipeline.py`) to import from `citenexus.tokenize`
- [ ] `task check` still green (482 tests, unchanged behavior)

## Story: Python CLI (reference implementation)
- [ ] Write failing tests for `citenexus verify` against fixture-derived (claim, passage) cases, including a multi-citation and a multi-claim case
- [ ] Write a cross-impl conformance test asserting the CLI's per-claim verdict matches `AnswerFlow.ask()`'s faithfulness-gate outcome on the same (claim, passage)
- [ ] Add `VerifyInput`/`VerifyReport` pydantic models (decoupled from `answer.result`, no EU ids required)
- [ ] Implement `citenexus.cli.verify`, calling `citenexus.answer.verify.is_supported`/`has_relevance_overlap` unchanged
- [ ] Text and `--format json` report formatters; exit codes 0/1/2
- [ ] Wire `[project.scripts] citenexus = "citenexus.cli:main"`
- [ ] `task check`

## Story: GitHub Action
- [ ] `action.yml` (composite): checkout + setup-python (SHA-pinned per `ports-ci.yml` convention) + `pip install citenexus` + run `citenexus verify`
- [ ] Inputs: `input` (glob), `fail-on-ungrounded` (default true); output: pass/fail summary
- [ ] A workflow that dogfoods the action against our own fixtures as a real CI gate
