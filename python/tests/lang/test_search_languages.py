"""The search-language capability table (ADR-0013).

`search_languages` may only name a language the tokenizer actually claims. The
measured failure this guards is Kannada: it is absent from ADR-0011's script range
table, so it classifies as "unknown" — yet `tokenize_v2` still emits tokens for
it, so BM25 would return plausible-looking rankings for a script the library makes
no claim about. Refusing by name is the only honest outcome.
"""

from __future__ import annotations

import pytest

from citenexus.lang.search import (
    SEARCH_LANGUAGES,
    UnsupportedSearchLanguageError,
    resolve_search_languages,
)
from citenexus.tokenize import SUPPORTED_SCRIPTS, scripts_in

# --------------------------------------------------------------------------- #
# The default
# --------------------------------------------------------------------------- #


def test_default_is_english_only() -> None:
    (language,) = resolve_search_languages(("en",))
    assert language.code == "en"
    assert language.name == "English"
    assert language.scripts == ("latin",)


def test_caller_order_is_preserved() -> None:
    codes = [lang.code for lang in resolve_search_languages(("ta", "en", "hi"))]
    assert codes == ["ta", "en", "hi"]


def test_duplicates_collapse_keeping_first_occurrence() -> None:
    codes = [lang.code for lang in resolve_search_languages(("en", "ta", "en"))]
    assert codes == ["en", "ta"]


def test_codes_are_case_and_whitespace_insensitive() -> None:
    codes = [lang.code for lang in resolve_search_languages((" EN ", "Ta"))]
    assert codes == ["en", "ta"]


def test_empty_request_is_refused() -> None:
    with pytest.raises(UnsupportedSearchLanguageError):
        resolve_search_languages(())


# --------------------------------------------------------------------------- #
# The refusals — the whole point of the module
# --------------------------------------------------------------------------- #


def test_kannada_is_refused_by_name() -> None:
    with pytest.raises(UnsupportedSearchLanguageError) as excinfo:
        resolve_search_languages(("kn",))
    error = excinfo.value
    assert error.language == "kn"
    assert error.script == "kannada"
    message = str(error)
    assert "Kannada" in message
    assert "kannada" in message
    assert "ADR-0011" in message


def test_kannada_really_is_unclaimed_not_just_untabled() -> None:
    # The regression this test exists for: someone "fixes" Kannada by adding it to
    # SUPPORTED_SCRIPTS without the ADR-0011 golden fixture. If that happens this
    # fails and the refusal tests above fail with it, which is the intended alarm.
    assert "kannada" not in SUPPORTED_SCRIPTS
    # NAMED but unclaimed: the range table knows Kannada by name (so a refusal can
    # say which script it is), and SUPPORTED_SCRIPTS deliberately does not claim it
    # because no ADR-0011 golden fixture backs it. That pair is the invariant.
    assert scripts_in("\u0c89\u0ca6\u0ccd\u0caf\u0cc7\u0cbe\u0c97\u0cbf") == ("kannada",)


@pytest.mark.parametrize("code", ["kn", "ml", "gu", "pa", "or", "si", "km", "lo", "my"])
def test_every_unclaimed_script_language_is_refused(code: str) -> None:
    with pytest.raises(UnsupportedSearchLanguageError) as excinfo:
        resolve_search_languages((code,))
    assert excinfo.value.language == code
    assert excinfo.value.script is not None


def test_unknown_code_is_refused_never_guessed() -> None:
    with pytest.raises(UnsupportedSearchLanguageError) as excinfo:
        resolve_search_languages(("xx",))
    assert excinfo.value.language == "xx"
    assert excinfo.value.script is None
    assert "never guessed" in str(excinfo.value)


def test_one_bad_language_refuses_the_whole_request() -> None:
    # No partial fan-out: searching 2 of the 3 requested languages and returning
    # results would be exactly the silent wrong answer this design forbids.
    with pytest.raises(UnsupportedSearchLanguageError):
        resolve_search_languages(("en", "ta", "kn"))


def test_the_error_is_a_value_error() -> None:
    # Existing `except ValueError` call sites must keep behaving.
    with pytest.raises(ValueError):
        resolve_search_languages(("kn",))


# --------------------------------------------------------------------------- #
# The table itself
# --------------------------------------------------------------------------- #


def test_supported_languages_use_adr_0011_script_names() -> None:
    for language in SEARCH_LANGUAGES.values():
        for script in language.scripts:
            assert script == script.lower()
        if language.is_supported:
            assert set(language.scripts) <= SUPPORTED_SCRIPTS


def test_every_claimed_script_has_at_least_one_language() -> None:
    claimed = {s for lang in SEARCH_LANGUAGES.values() for s in lang.scripts}
    assert claimed >= SUPPORTED_SCRIPTS


def test_table_keys_match_their_language_codes() -> None:
    for code, language in SEARCH_LANGUAGES.items():
        assert code == language.code


def test_japanese_needs_three_scripts_and_has_them_all() -> None:
    japanese = SEARCH_LANGUAGES["ja"]
    assert set(japanese.scripts) == {"han", "hiragana", "katakana"}
    assert japanese.is_supported


def test_tamil_is_supported_kannada_is_not() -> None:
    assert SEARCH_LANGUAGES["ta"].is_supported
    assert not SEARCH_LANGUAGES["kn"].is_supported
    assert SEARCH_LANGUAGES["kn"].unsupported == ("kannada",)
