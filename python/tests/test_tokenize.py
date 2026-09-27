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


def test_v1_keeps_the_exact_ascii_stubs_v2_was_written_to_fix() -> None:
    """Spec §4 v1 is frozen: `.lower()` then `[a-z0-9]+`, and nothing else.

    Every input below is one v2 deliberately changes — case folding, Unicode word
    characters, the truncated stub a non-ASCII character leaves behind. The ports
    and the 11 shipped vectors match these stubs byte-for-byte, so "fixing" v1
    (e.g. routing it through `tokenize_v2`) must fail here and not only in the
    port repos.
    """
    assert tokenize("Café Straße 東京") == ["caf", "stra", "e"]
    assert tokenize("Straße") == ["stra", "e"]
    assert tokenize("İstanbul") == ["i", "stanbul"]
    assert tokenize("ISO-9001:2015") == ["iso", "9001", "2015"]
    assert tokenize("MixedCASE tokens123abc") == ["mixedcase", "tokens123abc"]


def test_testing_fakes_still_re_exports_tokenize_for_backward_compat() -> None:
    assert tokenize_via_fakes is tokenize
