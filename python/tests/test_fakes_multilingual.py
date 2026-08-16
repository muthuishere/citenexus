"""The shipped fakes must not silently degrade on non-Latin text.

``FakeEmbedding`` used to hash the frozen v1 tokenizer (``[a-z0-9]+`` over
``.lower()``), which yields **zero tokens** for Tamil, Telugu, Chinese, Arabic
and every other non-Latin script — and therefore the zero vector. Nothing
raised: cosine similarity against a zero vector is defined, it just ranks
meaninglessly, so every offline multilingual retrieval test built on the fakes
was measuring nothing while appearing green.

These tests make that failure mode impossible to reintroduce quietly.
"""

from __future__ import annotations

import math

import pytest

from citenexus.testing.fakes import FakeEmbedding, is_zero_vector
from citenexus.tokenize import SUPPORTED_SCRIPTS

# One realistic sample per script the library CLAIMS to support. Keyed by the
# script name ``tokenize.SUPPORTED_SCRIPTS`` uses, so a script added there
# without a sample here fails a test instead of quietly embedding to zero.
SAMPLES: dict[str, str] = {
    "tamil": "ஊழியர் மகப்பேறு விடுப்பு பெறலாம்",
    "telugu": "ఉద్యోగి సెలవు పొందవచ్చు",
    "han": "员工可以享受产假",
    "arabic": "يمكن للموظف الحصول على إجازة",
    "hiragana": "しゅっさんかをとる",
    "katakana": "マタニティリーブ",
    "devanagari": "कर्मचारी मातृत्व अवकाश ले सकता है",
    "bengali": "কর্মচারী ছুটি নিতে পারেন",
    "cyrillic": "Сотрудник может взять отпуск",
    "greek": "Ο υπάλληλος μπορεί να πάρει άδεια",  # noqa: RUF001
    "hebrew": "העובד יכול לקחת חופשה",
    "hangul": "직원은 출산 휴가를 받을 수 있습니다",
    "thai": "พนักงานสามารถลาคลอดได้",
    "latin": "Employees are entitled to maternity leave",
}

TAMIL = SAMPLES["tamil"]
TELUGU = SAMPLES["telugu"]


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_tamil_embeds_to_a_non_zero_vector() -> None:
    """The headline regression: Tamil must carry signal, not the zero vector."""
    vec = FakeEmbedding().embed(TAMIL)
    assert not is_zero_vector(vec)
    assert math.isclose(math.sqrt(sum(v * v for v in vec)), 1.0, rel_tol=1e-9)


def test_zero_vector_is_detectable() -> None:
    """``is_zero_vector`` is the guard rail — it must actually fire.

    Text with no word characters at all still normalizes to all-zeros (the
    normalizer divides by 1.0 rather than raising), which is exactly the silent
    state a multilingual test must be able to assert against.
    """
    assert is_zero_vector(FakeEmbedding().embed("   ...   "))
    assert is_zero_vector([0.0] * 64)
    assert not is_zero_vector([0.0, 0.0, 0.5])


def test_ascii_only_mode_reproduces_the_old_zero_vector_bug() -> None:
    """The opt-in v1 path is kept for fixtures that pin v1 — and it is exactly
    the bug, which is why it is opt-in and never the default."""
    assert is_zero_vector(FakeEmbedding(ascii_only=True).embed(TAMIL))
    assert not is_zero_vector(FakeEmbedding(ascii_only=True).embed("annual leave"))


@pytest.mark.parametrize("script", sorted(SAMPLES))
def test_every_claimed_script_embeds_to_a_non_zero_vector(script: str) -> None:
    """Every script in ``SUPPORTED_SCRIPTS`` must produce a real vector."""
    assert not is_zero_vector(FakeEmbedding().embed(SAMPLES[script])), script


def test_samples_cover_exactly_the_claimed_scripts() -> None:
    """A guard against the *class* of bug: the library advertises a set of
    scripts, so a script added to ``SUPPORTED_SCRIPTS`` without a sample proving
    the shipped fake actually embeds it fails here rather than silently ranking
    zero vectors in some future multilingual test."""
    assert set(SAMPLES) == set(SUPPORTED_SCRIPTS)


def test_tamil_query_retrieves_its_own_tamil_document_by_cosine() -> None:
    """The actual thing multilingual retrieval tests want to assert — and which
    was unprovable while every Tamil vector was zero."""
    embedder = FakeEmbedding()
    tamil = embedder.embed(TAMIL)
    telugu = embedder.embed(TELUGU)
    query = embedder.embed("மகப்பேறு விடுப்பு")

    assert _cosine(query, tamil) > 0.0
    assert _cosine(query, tamil) > _cosine(query, telugu)


def test_ascii_behavior_is_unchanged_by_the_switch() -> None:
    """v2 is a strict superset of v1 on pure ASCII, which is why the pinned
    ``conformance/cases/e2e_hermetic.json`` corpus is byte-identical either
    way. Asserted directly on that corpus's sentences."""
    default = FakeEmbedding()
    legacy = FakeEmbedding(ascii_only=True)
    for text in (
        "The employee shall not disclose confidential information.",
        "Employees are entitled to thirty days of annual leave.",
        "The contract termination clause requires ninety days written notice.",
        "What is the capital of France?",
        "I can't answer that from the available evidence.",
    ):
        assert default.embed(text) == legacy.embed(text)
