"""`search_languages` fan-out through the public client (ADR-0013).

Measured before this change (`spikes/multilingual-search/`): an English question
over a Tamil corpus has **zero** lexical recall — the token sets are disjoint, so
BM25's `tf` is zero for every query term. Fanning the question out into each
requested language and fusing through the existing RRF fixes it, and because the
original query is always retained the fan-out is strictly additive.

The invariants these tests defend:
  * `search_languages=("en",)` is today's behaviour, unchanged;
  * ordering and the cache are deterministic;
  * an unsupported script REFUSES rather than returning an empty result;
  * citations stay verbatim in the source language;
  * `answer_language=None` still follows the §11a chain, and `"auto"` means it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from citenexus import CiteNexus
from citenexus.answer.result import Decision
from citenexus.lang.search import UnsupportedSearchLanguageError
from citenexus.retrieve.reformulate import QueryReformulator
from citenexus.testing import FakeEmbedding, FakeLLM

_EN_DOC = "The employee shall not disclose confidential information to any third party."
_TA_DOC = "ஊழியர் ரகசியத் தகவலை மூன்றாம் தரப்பினருக்கு வெளியிடக் கூடாது."

_Q = "Can the employee disclose confidential information?"
_Q_TA = "ஊழியர் ரகசியத் தகவலை வெளியிட முடியுமா?"
_Q_HI = "क्या कर्मचारी गोपनीय जानकारी का खुलासा कर सकता है?"


class RecordingReformulator:
    """Per-language lookup standing in for the small model; records every call."""

    def __init__(self, table: dict[str, str] | None = None, *, fail: bool = False) -> None:
        self.table = table if table is not None else {"ta": _Q_TA, "hi": _Q_HI, "en": _Q}
        self.calls: list[tuple[str, str]] = []
        self.fail = fail

    def reformulate(self, query: str, language: str = "en") -> str | None:
        self.calls.append((query, language))
        if self.fail:
            return None
        rewritten = self.table.get(language)
        return rewritten if rewritten and rewritten != query else None


def _rag(tmp_path: Path, reformulator: RecordingReformulator | None) -> CiteNexus:
    return CiteNexus(
        tmp_path,
        embedder=FakeEmbedding(),
        generator=FakeLLM(),
        reformulator=reformulator,
    )


# --------------------------------------------------------------------------- #
# The default is today's behaviour
# --------------------------------------------------------------------------- #


def test_default_asks_for_exactly_one_english_reformulation(tmp_path: Path) -> None:
    reformulator = RecordingReformulator({"en": "What may the employee disclose?"})
    rag = _rag(tmp_path, reformulator)
    rag.ingest(text=_EN_DOC, document_id="policy-en")
    rag.ask(_Q)
    assert reformulator.calls == [(_Q, "en")]


def test_default_matches_an_explicit_en_request(tmp_path: Path) -> None:
    a = RecordingReformulator({"en": "What may the employee disclose?"})
    b = RecordingReformulator({"en": "What may the employee disclose?"})
    rag_a, rag_b = _rag(tmp_path / "a", a), _rag(tmp_path / "b", b)
    for rag in (rag_a, rag_b):
        rag.ingest(text=_EN_DOC, document_id="policy-en")
    assert rag_a._extra_queries(_Q) == rag_b._extra_queries(_Q, ("en",))
    assert a.calls == b.calls


def test_default_needs_no_reformulator(tmp_path: Path) -> None:
    rag = _rag(tmp_path, None)
    rag.ingest(text=_EN_DOC, document_id="policy-en")
    assert rag._extra_queries(_Q) == ()
    assert rag.ask(_Q).evidence.decision is Decision.answered


def test_retrieve_default_is_unchanged(tmp_path: Path) -> None:
    rag = _rag(tmp_path, None)
    rag.ingest(text=_EN_DOC, document_id="policy-en")
    assert [c.eu_id for c in rag.retrieve(_Q)] == [c.eu_id for c in rag.retrieve(_Q, k=5)]


# --------------------------------------------------------------------------- #
# Fan-out: ordering, determinism, additivity
# --------------------------------------------------------------------------- #


def test_fanout_asks_one_reformulation_per_language_in_caller_order(tmp_path: Path) -> None:
    reformulator = RecordingReformulator()
    rag = _rag(tmp_path, reformulator)
    rag.ingest(text=_EN_DOC, document_id="policy-en")
    rag.ask(_Q, search_languages=("ta", "hi"))
    assert reformulator.calls == [(_Q, "ta"), (_Q, "hi")]


def test_extra_queries_follow_search_language_order(tmp_path: Path) -> None:
    rag = _rag(tmp_path, RecordingReformulator())
    assert rag._extra_queries(_Q, ("ta", "hi")) == (_Q_TA, _Q_HI)
    assert rag._extra_queries(_Q, ("hi", "ta")) == (_Q_HI, _Q_TA)


def test_fanout_is_deterministic_across_repeats(tmp_path: Path) -> None:
    rag = _rag(tmp_path, RecordingReformulator())
    first = rag._extra_queries(_Q, ("ta", "hi", "en"))
    for _ in range(5):
        assert rag._extra_queries(_Q, ("ta", "hi", "en")) == first


def test_a_reformulation_equal_to_the_original_is_dropped(tmp_path: Path) -> None:
    # "en" maps back to the original question — nothing gained, no extra query.
    rag = _rag(tmp_path, RecordingReformulator())
    assert _Q not in rag._extra_queries(_Q, ("en", "ta"))


def test_duplicate_reformulations_are_deduplicated(tmp_path: Path) -> None:
    rag = _rag(tmp_path, RecordingReformulator({"ta": _Q_TA, "hi": _Q_TA}))
    assert rag._extra_queries(_Q, ("ta", "hi")) == (_Q_TA,)


def test_fanout_reaches_evidence_in_the_other_language(tmp_path: Path) -> None:
    rag = _rag(tmp_path, RecordingReformulator())
    rag.ingest(text=_TA_DOC, document_id="policy-ta")
    found_without = {c.eu_id for c in rag.retrieve(_Q, search_languages=("en",))}
    found_with = {c.eu_id for c in rag.retrieve(_Q, search_languages=("ta",))}
    assert found_with, "fan-out must surface the Tamil evidence"
    assert found_with >= found_without


def test_fanout_never_loses_a_candidate(tmp_path: Path) -> None:
    rag = _rag(tmp_path, RecordingReformulator())
    rag.ingest(text=_EN_DOC, document_id="policy-en")
    rag.ingest(text=_TA_DOC, document_id="policy-ta")
    single = {c.eu_id for c in rag.retrieve(_Q, k=10, search_languages=("en",))}
    fanned = {c.eu_id for c in rag.retrieve(_Q, k=10, search_languages=("en", "ta"))}
    assert single <= fanned, "fan-out is strictly additive at retrieval"


def test_the_cache_is_paid_once_per_query_and_language(tmp_path: Path) -> None:
    reformulator = RecordingReformulator()
    rag = _rag(tmp_path, reformulator)
    rag.ingest(text=_EN_DOC, document_id="policy-en")
    rag.ask(_Q, search_languages=("ta", "hi"))
    rag.retrieve(_Q, search_languages=("ta", "hi"))
    # The client asks every time; the CACHE is what makes it cheap, and it lives
    # in QueryReformulator — this fake records raw calls, so assert the shape.
    assert reformulator.calls == [(_Q, "ta"), (_Q, "hi")] * 2


def test_the_real_reformulator_pays_the_model_once_per_pair(tmp_path: Path) -> None:
    # The cache that matters is inside QueryReformulator, so wire the real one
    # over a counting transport: ask + retrieve + a second ask, two languages.
    import json

    prompts: list[str] = []

    def transport(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        prompt = json.loads(body)["messages"][0]["content"]
        prompts.append(prompt)
        reply = _Q_TA if "in Tamil" in prompt else _Q_HI
        return json.dumps({"choices": [{"message": {"content": reply}}]}).encode("utf-8")

    rag = CiteNexus(
        tmp_path,
        embedder=FakeEmbedding(),
        generator=FakeLLM(),
        reformulator=QueryReformulator(base_url="http://s/v1", model="s", transport=transport),
    )
    rag.ingest(text=_EN_DOC, document_id="policy-en")
    rag.ask(_Q, search_languages=("ta", "hi"))
    rag.retrieve(_Q, search_languages=("ta", "hi"))
    rag.ask(_Q, search_languages=("ta", "hi"))
    assert len(prompts) == 2, "one model call per (query, language), not per call site"


def test_a_second_question_pays_again(tmp_path: Path) -> None:
    import json

    calls: list[str] = []

    def transport(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        calls.append(json.loads(body)["messages"][0]["content"])
        return json.dumps({"choices": [{"message": {"content": _Q_TA}}]}).encode("utf-8")

    rag = CiteNexus(
        tmp_path,
        embedder=FakeEmbedding(),
        generator=FakeLLM(),
        reformulator=QueryReformulator(base_url="http://s/v1", model="s", transport=transport),
    )
    rag.ingest(text=_EN_DOC, document_id="policy-en")
    rag.retrieve(_Q, search_languages=("ta",))
    rag.retrieve("A different question entirely?", search_languages=("ta",))
    assert len(calls) == 2


# --------------------------------------------------------------------------- #
# Degradation, never an error
# --------------------------------------------------------------------------- #


def test_a_dead_endpoint_degrades_to_single_query(tmp_path: Path) -> None:
    reformulator = RecordingReformulator(fail=True)
    rag = _rag(tmp_path, reformulator)
    rag.ingest(text=_EN_DOC, document_id="policy-en")
    assert rag._extra_queries(_Q, ("ta", "hi")) == ()
    result = rag.ask(_Q, search_languages=("ta", "hi"))
    assert result.evidence.decision is Decision.answered
    assert reformulator.calls, "the attempt was made"


def test_one_dead_language_does_not_sink_the_others(tmp_path: Path) -> None:
    rag = _rag(tmp_path, RecordingReformulator({"ta": _Q_TA}))
    assert rag._extra_queries(_Q, ("ta", "hi")) == (_Q_TA,)


# --------------------------------------------------------------------------- #
# The refusals
# --------------------------------------------------------------------------- #


def test_an_unsupported_script_refuses_on_ask(tmp_path: Path) -> None:
    rag = _rag(tmp_path, RecordingReformulator())
    rag.ingest(text=_EN_DOC, document_id="policy-en")
    with pytest.raises(UnsupportedSearchLanguageError) as excinfo:
        rag.ask(_Q, search_languages=("en", "kn"))
    assert excinfo.value.script == "kannada"


def test_an_unsupported_script_refuses_on_retrieve(tmp_path: Path) -> None:
    rag = _rag(tmp_path, RecordingReformulator())
    rag.ingest(text=_EN_DOC, document_id="policy-en")
    with pytest.raises(UnsupportedSearchLanguageError):
        rag.retrieve(_Q, search_languages=("kn",))


def test_the_refusal_costs_no_model_call(tmp_path: Path) -> None:
    reformulator = RecordingReformulator()
    rag = _rag(tmp_path, reformulator)
    rag.ingest(text=_EN_DOC, document_id="policy-en")
    with pytest.raises(UnsupportedSearchLanguageError):
        rag.ask(_Q, search_languages=("ta", "kn"))
    assert reformulator.calls == [], "refuse before spending"


def test_an_unsupported_script_never_returns_an_empty_result(tmp_path: Path) -> None:
    # The specific outcome the owner's rule forbids: a capability gap must not
    # look like "the corpus does not contain this".
    rag = _rag(tmp_path, RecordingReformulator())
    rag.ingest(text=_EN_DOC, document_id="policy-en")
    try:
        candidates = rag.retrieve(_Q, search_languages=("kn",))
    except UnsupportedSearchLanguageError:
        return
    pytest.fail(f"expected a refusal, got {len(candidates)} candidates")


def test_an_unknown_language_code_refuses(tmp_path: Path) -> None:
    rag = _rag(tmp_path, RecordingReformulator())
    with pytest.raises(UnsupportedSearchLanguageError):
        rag.retrieve(_Q, search_languages=("klingon",))


def test_fanout_without_a_reformulator_refuses(tmp_path: Path) -> None:
    rag = _rag(tmp_path, None)
    rag.ingest(text=_EN_DOC, document_id="policy-en")
    with pytest.raises(UnsupportedSearchLanguageError) as excinfo:
        rag.ask(_Q, search_languages=("en", "ta"))
    assert "reformulation" in str(excinfo.value)


def test_deep_strategy_refuses_a_fanout_rather_than_ignoring_it(tmp_path: Path) -> None:
    rag = _rag(tmp_path, RecordingReformulator())
    rag.ingest(text=_EN_DOC, document_id="policy-en")
    with pytest.raises(UnsupportedSearchLanguageError):
        rag.ask(_Q, strategy="deep", search_languages=("en", "ta"))


def test_empty_search_languages_refuses(tmp_path: Path) -> None:
    rag = _rag(tmp_path, RecordingReformulator())
    with pytest.raises(UnsupportedSearchLanguageError):
        rag.retrieve(_Q, search_languages=())


# --------------------------------------------------------------------------- #
# The guarantee is untouched
# --------------------------------------------------------------------------- #


def test_a_citation_reached_by_fanout_is_verbatim_in_its_source_language(
    tmp_path: Path,
) -> None:
    rag = _rag(tmp_path, RecordingReformulator())
    rag.ingest(text=_TA_DOC, document_id="policy-ta")
    result = rag.ask(_Q, search_languages=("ta",))
    assert result.evidence.decision is Decision.answered
    assert result.sources[0].passage == _TA_DOC


def test_the_reformulation_never_becomes_the_citation(tmp_path: Path) -> None:
    rag = _rag(tmp_path, RecordingReformulator())
    rag.ingest(text=_TA_DOC, document_id="policy-ta")
    result = rag.ask(_Q, search_languages=("ta",))
    for source in result.sources:
        assert source.passage != _Q_TA
        assert _Q_TA not in (source.passage or "")


def test_fanout_that_finds_nothing_still_abstains(tmp_path: Path) -> None:
    # Fan-out widens the search; it does not invent evidence. Two languages over
    # an empty corpus is still an abstention, not an answer.
    rag = _rag(tmp_path, RecordingReformulator())
    result = rag.ask(_Q, search_languages=("en", "ta"))
    assert result.evidence.decision is Decision.refused
    assert result.sources == ()


# --------------------------------------------------------------------------- #
# answer_language: "auto" is a sentinel, None is unchanged
# --------------------------------------------------------------------------- #


def test_auto_and_none_agree(tmp_path: Path) -> None:
    rag = _rag(tmp_path, None)
    rag.ingest(text=_EN_DOC, document_id="policy-en")
    implicit = rag.ask(_Q)
    explicit = rag.ask(_Q, answer_language="auto")
    assert implicit.answer_language == explicit.answer_language
    assert implicit.answer == explicit.answer


def test_none_still_follows_the_fallback_chain(tmp_path: Path) -> None:
    rag = _rag(tmp_path, None)
    rag.ingest(text=_EN_DOC, document_id="policy-en")
    # No detector is injected, so the chain falls through to the configured
    # default — exactly as before this change.
    assert rag.ask(_Q).answer_language == "en"


def test_an_explicit_language_is_still_forced(tmp_path: Path) -> None:
    rag = _rag(tmp_path, None)
    rag.ingest(text=_EN_DOC, document_id="policy-en")
    assert rag.ask(_Q, answer_language="fr").answer_language == "fr"


def test_auto_is_not_treated_as_a_language_code(tmp_path: Path) -> None:
    rag = _rag(tmp_path, None)
    rag.ingest(text=_EN_DOC, document_id="policy-en")
    assert rag.ask(_Q, answer_language="auto").answer_language != "auto"


def test_answer_language_and_search_languages_are_independent(tmp_path: Path) -> None:
    rag = _rag(tmp_path, RecordingReformulator())
    rag.ingest(text=_TA_DOC, document_id="policy-ta")
    result = rag.ask(_Q, search_languages=("ta",), answer_language="en")
    assert result.answer_language == "en"
    # ...and the citation is still the Tamil source, verbatim.
    assert result.sources[0].passage == _TA_DOC
