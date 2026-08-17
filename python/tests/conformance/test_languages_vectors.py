"""conformance/cases/languages.json asserted as a BINDING contract.

The named code vocabulary — 41 languages, 27 scripts, which of them CiteNexus
claims — is what stops a port silently naming a language it cannot tokenize.
Go pins it (``golang/lang/codes_test.go:31``) and JS pins it
(``js/src/lang/codes.test.ts:30``); Python's ``tests/lang/test_codes.py``
asserted the same sets against Python's own constants, never against the
committed file.
"""

from __future__ import annotations

from typing import Any

import pytest

from citenexus.lang.codes import Language, Script
from citenexus.lang.fallback import AUTO_ANSWER_LANGUAGE
from citenexus.lang.search import SEARCH_LANGUAGES
from citenexus.tokenize import CONTINUOUS_SCRIPTS, SUPPORTED_SCRIPTS

from .fixtures import load_case

FIXTURE: dict[str, Any] = load_case("languages.json")

EXPECTED_COUNTS: dict[str, int] = {
    "scripts": 27,
    "supported_scripts": 14,
    "continuous_scripts": 7,
    "languages": 41,
}


def test_list_sizes() -> None:
    got = {k: len(FIXTURE[k]) for k in EXPECTED_COUNTS}
    assert got == EXPECTED_COUNTS


def test_auto_sentinel() -> None:
    """The one answer_language value that is NOT a language."""
    assert FIXTURE["auto_sentinel"] == str(AUTO_ANSWER_LANGUAGE)
    assert FIXTURE["auto_sentinel"] not in {row["code"] for row in FIXTURE["languages"]}


def test_script_enum_matches_fixture() -> None:
    assert sorted(m.value for m in Script) == FIXTURE["scripts"]


def test_claimed_script_sets_match_fixture() -> None:
    assert sorted(SUPPORTED_SCRIPTS) == FIXTURE["supported_scripts"]
    assert sorted(CONTINUOUS_SCRIPTS) == FIXTURE["continuous_scripts"]


def test_language_enum_matches_fixture() -> None:
    members = {m.value for m in Language} - {str(AUTO_ANSWER_LANGUAGE)}
    assert members == {row["code"] for row in FIXTURE["languages"]}


def test_search_table_order_is_the_fixture_order() -> None:
    """Every port reads the table top-to-bottom; the ORDER is part of the contract."""
    assert [str(e.code) for e in SEARCH_LANGUAGES.values()] == [
        row["code"] for row in FIXTURE["languages"]
    ]


@pytest.mark.parametrize("row", [pytest.param(r, id=r["code"]) for r in FIXTURE["languages"]])
def test_language_row(row: dict[str, Any]) -> None:
    entry = SEARCH_LANGUAGES[row["code"]]
    assert entry.name == row["name"]
    assert [str(s) for s in entry.scripts] == row["scripts"]
    assert entry.is_supported is row["supported"]
