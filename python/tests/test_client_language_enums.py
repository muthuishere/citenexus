"""The acceptance pin for `language-enums`: a raw-string call site is unchanged.

The owner's ruling is the whole test: *"they can put string — enum is just
helpful stuff, so it support both."* So every assertion here is the same call
made twice — once with the plain codes a 0.10.1 caller writes today, once with
the `Language` members — asserting the two are indistinguishable, and that the
string form emits **no warning of any category**.

`warnings.simplefilter("always")` is deliberate: a `DeprecationWarning` is
invisible by default under pytest's config in some setups, and an invisible
deprecation is exactly the failure this test exists to prevent.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from citenexus import CiteNexus, Language, Script
from citenexus.config.schema import MultilingualConfig
from citenexus.lang.search import UnsupportedSearchLanguageError
from citenexus.testing import FakeEmbedding, FakeLLM

_EN_DOC = "The employee shall not disclose confidential information to any third party."
_Q = "Can the employee disclose confidential information?"


class _CountingReformulator:
    """Records every reformulation so "raises before any model call" is provable."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def reformulate(self, query: str, language: str = "en") -> str | None:
        self.calls.append((query, language))
        return f"{query} [{language}]"


def _rag(tmp_path: Path, reformulator: _CountingReformulator | None = None) -> CiteNexus:
    rag = CiteNexus(
        tmp_path,
        embedder=FakeEmbedding(),
        generator=FakeLLM(),
        reformulator=reformulator,
    )
    rag.ingest(text=_EN_DOC, document_id="policy-en")
    return rag


# --------------------------------------------------------------------------- #
# ask / retrieve — string and member are the same call.
# --------------------------------------------------------------------------- #


def test_ask_answer_language_string_and_member_agree(tmp_path: Path) -> None:
    by_string = _rag(tmp_path / "a").ask(_Q, answer_language="ta")
    by_member = _rag(tmp_path / "b").ask(_Q, answer_language=Language.TAMIL)
    assert by_string.answer_language == by_member.answer_language == "ta"
    assert by_string.model_dump_json() == by_member.model_dump_json()


def test_ask_auto_sentinel_string_and_member_agree(tmp_path: Path) -> None:
    by_string = _rag(tmp_path / "a").ask(_Q, answer_language="auto")
    by_member = _rag(tmp_path / "b").ask(_Q, answer_language=Language.AUTO)
    assert by_string.model_dump_json() == by_member.model_dump_json()


def test_search_languages_string_member_and_mixed_agree(tmp_path: Path) -> None:
    calls: list[list[tuple[str, str]]] = []
    for name, langs in (
        ("a", ("en", "ta")),
        ("b", (Language.ENGLISH, Language.TAMIL)),
        ("c", ("en", Language.TAMIL)),
    ):
        reformulator = _CountingReformulator()
        rag = _rag(tmp_path / name, reformulator)
        rag.ask(_Q, search_languages=langs)
        calls.append(reformulator.calls)
    assert calls[0] == calls[1] == calls[2]
    assert calls[0] == [(_Q, "en"), (_Q, "ta")]


def test_retrieve_string_and_member_agree(tmp_path: Path) -> None:
    rag = _rag(tmp_path, _CountingReformulator())
    by_string = [c.eu_id for c in rag.retrieve(_Q, search_languages=("en",))]
    by_member = [c.eu_id for c in rag.retrieve(_Q, search_languages=(Language.ENGLISH,))]
    assert by_string == by_member


# --------------------------------------------------------------------------- #
# NOT ONE WARNING on the string path.
# --------------------------------------------------------------------------- #


def test_the_raw_string_path_emits_no_warning(tmp_path: Path) -> None:
    rag = _rag(tmp_path, _CountingReformulator())
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        rag.ask(_Q, answer_language="ta", search_languages=("en", "hi"))
        rag.retrieve(_Q, search_languages=("en",))
        MultilingualConfig(default_answer_language="ta", fallback_language="en")
    assert [str(w.message) for w in caught] == []


# --------------------------------------------------------------------------- #
# Config takes either form.
# --------------------------------------------------------------------------- #


def test_config_accepts_either_form_identically() -> None:
    by_string = MultilingualConfig(default_answer_language="ta")
    by_member = MultilingualConfig(default_answer_language=Language.TAMIL)
    assert by_string == by_member
    assert by_string.model_dump_json() == by_member.model_dump_json()
    assert by_string.resolved_default_answer_language == "ta"


def test_client_default_answer_language_accepts_a_member(tmp_path: Path) -> None:
    rag = CiteNexus(
        tmp_path,
        embedder=FakeEmbedding(),
        generator=FakeLLM(),
        default_answer_language=Language.TAMIL,
    )
    rag.ingest(text=_EN_DOC, document_id="policy-en")
    assert rag.ask(_Q).answer_language == "ta"


# --------------------------------------------------------------------------- #
# A typo still raises by name, BEFORE any model call.
# --------------------------------------------------------------------------- #


def test_a_typo_raises_by_name_and_spends_nothing(tmp_path: Path) -> None:
    reformulator = _CountingReformulator()
    rag = _rag(tmp_path, reformulator)
    with pytest.raises(UnsupportedSearchLanguageError) as excinfo:
        rag.ask(_Q, search_languages=("en", "tamiil"))
    assert "tamiil" in str(excinfo.value)
    assert reformulator.calls == []


def test_an_unclaimed_script_names_the_script_as_a_plain_code(tmp_path: Path) -> None:
    reformulator = _CountingReformulator()
    rag = _rag(tmp_path, reformulator)
    with pytest.raises(UnsupportedSearchLanguageError) as excinfo:
        rag.ask(_Q, search_languages=(Language.KANNADA,))
    message = str(excinfo.value)
    assert "'kannada'" in message
    assert "Script." not in message
    assert excinfo.value.script == Script.KANNADA
    assert reformulator.calls == []
