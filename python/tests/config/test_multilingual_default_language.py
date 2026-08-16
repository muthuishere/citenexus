"""`multilingual.default_answer_language` — the named knob for the chain's floor.

The chain's last rung used to be reached only after an evidence-dominance
inference, which made its name (`fallback_language`) accurate and its importance
low. Now it is the answer language for every call that does not state one, so it
gets the name that says so — with the old key kept working, because configs in
the field set it.
"""

from __future__ import annotations

from pathlib import Path

from citenexus import CiteNexus
from citenexus.config.schema import CiteNexusConfig, MultilingualConfig, StorageConfig


def test_default_is_english() -> None:
    assert MultilingualConfig().default_answer_language == "en"
    assert MultilingualConfig().resolved_default_answer_language == "en"


def test_the_new_knob_is_used() -> None:
    config = MultilingualConfig(default_answer_language="hi")
    assert config.resolved_default_answer_language == "hi"


def test_the_deprecated_alias_still_works() -> None:
    # Configs in the field set `fallback_language`; they must not silently
    # regress to "en" the day the new key lands.
    config = MultilingualConfig(fallback_language="fr")
    assert config.resolved_default_answer_language == "fr"


def test_the_new_knob_wins_when_both_are_set() -> None:
    config = MultilingualConfig(default_answer_language="hi", fallback_language="fr")
    assert config.resolved_default_answer_language == "hi"


def _client(tmp_path: Path, multilingual: MultilingualConfig) -> CiteNexus:
    return CiteNexus.from_config(
        CiteNexusConfig(
            storage=StorageConfig(bucket=str(tmp_path)),
            multilingual=multilingual,
        )
    )


def test_from_config_honours_the_new_knob(tmp_path: Path) -> None:
    rag = _client(tmp_path, MultilingualConfig(default_answer_language="hi"))
    assert rag._default_answer_language == "hi"


def test_from_config_honours_the_deprecated_alias(tmp_path: Path) -> None:
    rag = _client(tmp_path, MultilingualConfig(fallback_language="fr"))
    assert rag._default_answer_language == "fr"


def test_from_config_defaults_to_english(tmp_path: Path) -> None:
    rag = _client(tmp_path, MultilingualConfig())
    assert rag._default_answer_language == "en"
