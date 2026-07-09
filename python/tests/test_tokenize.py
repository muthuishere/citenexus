"""The pinned SPEC-PORTS-v1 §4 tokenizer lives in its own production module —
not under `testing`, since four non-test modules depend on it (verify, bm25,
structure retrieval, the smoke pipeline)."""

from __future__ import annotations

from citenexus.testing.fakes import tokenize as tokenize_via_fakes
from citenexus.tokenize import tokenize


def test_tokenize_lowercases_and_splits_on_non_alnum() -> None:
    assert tokenize("The Employee, may NOT disclose!") == [
        "the",
        "employee",
        "may",
        "not",
        "disclose",
    ]


def test_tokenize_empty_text_yields_no_tokens() -> None:
    assert tokenize("") == []


def test_testing_fakes_still_re_exports_tokenize_for_backward_compat() -> None:
    assert tokenize_via_fakes is tokenize
