"""ADR-0009/0010: the polarity table is a tier-2 asset with a silent failure mode.

The ADR-0007 spike measured that corrupting a polarity table raises false
abstention while **recall stays flat** — no internal metric degrades, so a bad
table is invisible from the inside. That is why a language may not be claimed
without a golden fixture, and why this test exists: it pins the failure mode so
the rule has teeth rather than being a comment in an ADR.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from citenexus.answer import verify
from citenexus.answer.tables import POLARITY_LANGUAGES, POLARITY_MARKERS
from citenexus.answer.verify import is_supported_v2

_CONFORMANCE = Path(__file__).resolve().parents[3] / "conformance"

# Legitimately-supported answers that must survive a clean table. Each COMPRESSES
# the passage by dropping an interior word — the shape a corrupt table punishes,
# because the guard only inspects markers inside the matched span.
_CONTROLS = [
    (
        "The contractor shall maintain liability insurance at all times.",
        "The contractor shall maintain insurance",  # drops "liability"
    ),
    (
        "The recommended dose for adult patients is 500 milligrams daily.",
        "The recommended dose is 500 milligrams daily",  # drops "for adult patients"
    ),
    (
        "Access is granted to external auditors on request.",
        "Access is granted to auditors",  # drops "external"
    ),
    (
        "The maintenance window opens at 02:00 UTC on Sunday.",
        "The maintenance window opens on Sunday",  # drops "at 02:00 UTC"
    ),
]


def test_clean_table_accepts_every_control() -> None:
    assert all(is_supported_v2(claim, passage) for passage, claim in _CONTROLS)


@pytest.mark.parametrize(
    ("corruption", "extra"),
    [
        # scope distinctions misfiled as polarity — the dangerous corruption,
        # because these read like antonyms but are really "different subject"
        ("scope-antonyms", {"adult", "external"}),
        # ordinary domain nouns swept in by an over-eager table
        ("domain-nouns", {"liability", "utc"}),
    ],
)
def test_corrupted_table_raises_false_abstention(
    monkeypatch: pytest.MonkeyPatch, corruption: str, extra: set[str]
) -> None:
    """A corrupted table rejects answers a clean table accepts.

    The rejections are FALSE ABSTENTIONS: the answers are genuinely supported.
    Nothing else in the pipeline notices — which is the point.
    """
    clean = sum(is_supported_v2(c, p) for p, c in _CONTROLS)
    monkeypatch.setattr(verify, "POLARITY_MARKERS", POLARITY_MARKERS | extra)
    corrupted = sum(is_supported_v2(c, p) for p, c in _CONTROLS)

    assert corrupted < clean, f"{corruption} corruption changed nothing — test is not probing"


def test_table_claims_only_languages_with_fixtures() -> None:
    """No language may be claimed by the table without a golden fixture."""
    assert POLARITY_LANGUAGES == ("en",)


def test_generated_table_matches_the_reference() -> None:
    """The canonical file is generated from the Python reference, never hand-edited."""
    emitted = json.loads((_CONFORMANCE / "polarity.json").read_text(encoding="utf-8"))
    assert emitted["markers"] == sorted(POLARITY_MARKERS)
    assert emitted["languages"] == list(POLARITY_LANGUAGES)
