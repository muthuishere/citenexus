"""``Language`` / ``Script`` — the named code sets (change: language-enums).

The whole design is one constraint: the enums are a CONVENIENCE layer, never a
migration. A caller on 0.10.1 passing ``"ta"`` must behave identically forever,
with no warning. These tests pin that, and pin the ``StrEnum`` properties that
make it possible — equality, hashing, ``json.dumps`` and ``str()`` — because if
any of them drift, a conformance fixture moves.
"""

from __future__ import annotations

import json
import warnings
from enum import StrEnum

import pytest

from citenexus.lang import AUTO_ANSWER_LANGUAGE, Language, Script
from citenexus.lang.search import SEARCH_LANGUAGES, resolve_search_languages
from citenexus.tokenize import (
    CONTINUOUS_SCRIPTS,
    SUPPORTED_SCRIPTS,
    scripts_in,
    unsupported_scripts,
)

# --------------------------------------------------------------------------- #
# 1. A member IS its code.
# --------------------------------------------------------------------------- #


def test_language_is_a_strenum() -> None:
    assert issubclass(Language, StrEnum)
    assert issubclass(Script, StrEnum)


def test_member_equals_its_code() -> None:
    # Bound through ``str`` on purpose: mypy's ``strict_equality`` narrows an
    # enum member to a Literal and calls member-vs-literal "non-overlapping",
    # even though a StrEnum member genuinely IS the string at runtime. Going
    # through ``str`` asserts the runtime fact that every call site relies on.
    tamil: str = Language.TAMIL
    latin: str = Script.LATIN
    assert tamil == "ta"
    assert latin == "latin"


def test_member_hashes_as_its_code() -> None:
    """Interchangeable as a mapping key — this is what keeps lookups working."""
    assert hash(Language.TAMIL) == hash("ta")
    by_string: dict[str, int] = {"ta": 1}
    assert by_string[Language.TAMIL] == 1
    by_member: dict[str, int] = {Language.TAMIL: 1}
    assert by_member["ta"] == 1


def test_member_serializes_as_its_code() -> None:
    """The property that lets this land without moving a fixture."""
    assert json.dumps(Language.TAMIL) == '"ta"'
    assert json.dumps(Script.LATIN) == '"latin"'
    assert json.dumps({"answer_language": Language.TAMIL}) == '{"answer_language": "ta"}'
    assert json.dumps([Script.TELUGU]) == '["telugu"]'


def test_member_formats_as_its_code() -> None:
    assert f"{Language.TAMIL}" == "ta"
    assert str(Script.LATIN) == "latin"
    assert "-".join([Language.ENGLISH, Language.TAMIL]) == "en-ta"


def test_lookup_by_value() -> None:
    assert Language("ta") is Language.TAMIL
    assert Script("telugu") is Script.TELUGU
    with pytest.raises(ValueError):
        Language("tamiil")


# --------------------------------------------------------------------------- #
# 2. The "auto" sentinel is named, but is not a searchable language.
# --------------------------------------------------------------------------- #


def test_auto_is_a_named_member_and_the_sentinel() -> None:
    auto: str = Language.AUTO
    assert auto == "auto"
    assert AUTO_ANSWER_LANGUAGE == Language.AUTO


def test_auto_is_not_in_the_search_table() -> None:
    assert Language.AUTO not in SEARCH_LANGUAGES
    with pytest.raises(Exception, match="unknown search language 'auto'"):
        resolve_search_languages(["auto"])


# --------------------------------------------------------------------------- #
# 3. The member sets are exactly the tables — one definition, not three.
# --------------------------------------------------------------------------- #


def test_language_members_are_the_search_codes_plus_auto() -> None:
    assert {m.value for m in Language} == {str(c) for c in SEARCH_LANGUAGES} | {"auto"}
    assert len(SEARCH_LANGUAGES) == 41


def test_search_table_is_keyed_by_language_and_names_scripts() -> None:
    for code, entry in SEARCH_LANGUAGES.items():
        assert isinstance(code, Language)
        assert isinstance(entry.code, Language)
        assert entry.code == code
        assert all(isinstance(s, Script) for s in entry.scripts)


def test_search_table_still_resolves_by_plain_string() -> None:
    assert SEARCH_LANGUAGES["ta"].name == "Tamil"
    assert SEARCH_LANGUAGES[Language.TAMIL] is SEARCH_LANGUAGES["ta"]


def test_script_sets_are_script_members() -> None:
    assert all(isinstance(s, Script) for s in SUPPORTED_SCRIPTS)
    assert all(isinstance(s, Script) for s in CONTINUOUS_SCRIPTS)


def test_script_sets_still_answer_plain_string_membership() -> None:
    assert "latin" in SUPPORTED_SCRIPTS
    assert "telugu" in SUPPORTED_SCRIPTS
    assert "khmer" not in SUPPORTED_SCRIPTS
    assert "han" in CONTINUOUS_SCRIPTS
    assert "hangul" not in CONTINUOUS_SCRIPTS


def test_script_members_cover_the_range_table() -> None:
    from citenexus.tokenize import _SCRIPT_RANGES

    assert {n for _f, _l, n in _SCRIPT_RANGES} <= {m.value for m in Script}
    unknown: str = Script.UNKNOWN
    common: str = Script.COMMON
    assert unknown == "unknown"
    assert common == "common"


# --------------------------------------------------------------------------- #
# 4. Tokenizer outputs are Script members AND compare as plain strings.
# --------------------------------------------------------------------------- #


def test_scripts_in_returns_script_members_that_equal_strings() -> None:
    found = scripts_in("hello 東京")
    assert all(isinstance(s, Script) for s in found)
    assert list(found) == ["han", "latin"]


def test_unsupported_scripts_equals_plain_strings() -> None:
    got = unsupported_scripts("ជនជាតិ")  # khmer — named, unclaimed
    assert list(got) == ["khmer"]
    assert json.dumps(list(got)) == '["khmer"]'


# --------------------------------------------------------------------------- #
# 5. Strings in, strings out — and NOT ONE WARNING.
# --------------------------------------------------------------------------- #


def test_resolve_accepts_strings_enums_and_a_mix_identically() -> None:
    by_string = resolve_search_languages(["en", "ta"])
    by_enum = resolve_search_languages([Language.ENGLISH, Language.TAMIL])
    mixed = resolve_search_languages(["en", Language.TAMIL])
    assert by_string == by_enum == mixed


def test_the_string_path_emits_no_warning() -> None:
    """The acceptance pin: raw strings are first-class forever, not the old way."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        resolve_search_languages(["en", "ta", "hi"])
    assert caught == []


def test_unknown_code_still_raises_by_name() -> None:
    with pytest.raises(Exception, match="unknown search language 'tamiil'"):
        resolve_search_languages(["tamiil"])


def test_unclaimed_script_error_names_plain_codes_not_reprs() -> None:
    """``!r`` on a StrEnum would print ``<Script.KANNADA: 'kannada'>``."""
    with pytest.raises(Exception) as excinfo:
        resolve_search_languages(["kn"])
    message = str(excinfo.value)
    assert "'kannada'" in message
    assert "Script." not in message
    assert "Language." not in message
