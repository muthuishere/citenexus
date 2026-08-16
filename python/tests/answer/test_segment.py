"""ADR-0009: guarded claim segmentation.

Naive `[.!?\\n]+` splitting — what ships today at `answer/agentic.py:53` —
failed 54.2% of the spike's six-language cases. The guarded splitter is tier-1
scanning code over a tier-2 terminator/abbreviation table (ADR-0010); adding
`。！？` to the *table* fixed 100% of the Japanese failures with no algorithm
change, which is the evidence that kept this out of the Rust core.
"""

# The fullwidth terminators below are the subject under test, not typos.
# ruff: noqa: RUF002

from __future__ import annotations

import pytest

from citenexus.answer.segment import split_claims


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # abbreviations must not split
        ("Art. 5 applies to all tenants.", 1),
        ("See Dr. Smith for details.", 1),
        ("The rate is 4 bps, cf. sec. 12 of the agreement.", 1),
        # initials must not split
        ("J. Smith signed the agreement.", 1),
        # decimals must not split
        ("The dose is 500.00 milligrams daily.", 1),
        ("Threshold calibrated to 4.5 gigaelectronvolts.", 1),
        # real sentence boundaries do split
        ("The contractor maintains insurance. The term is five years.", 2),
        ("Is it approved? It is not.", 2),
        ("One. Two. Three.", 3),
        # terminator runs are one boundary, not several
        ("Really?! Yes.", 2),
        ("Wait... then go.", 2),
        # no trailing terminator
        ("The window opens at 02:00 UTC", 1),
        ("First sentence. Second without a period", 2),
    ],
)
def test_claim_count(text: str, expected: int) -> None:
    assert len(split_claims(text)) == expected


def test_cjk_terminator_splits_without_whitespace() -> None:
    """CJK writes `。` with no following space — the splitter must not require one."""
    assert len(split_claims("従業員は開示してはならない。期間は五年である。")) == 2


def test_enumeration_stays_one_claim() -> None:
    assert len(split_claims("The parties are (a) the tenant; (b) the landlord.")) == 1


def test_segmentation_is_deterministic() -> None:
    text = "Art. 5 applies. The dose is 500.00 mg. Really?! Done."
    assert split_claims(text) == split_claims(text)


def test_empty_and_blank_yield_no_claims() -> None:
    assert split_claims("") == []
    assert split_claims("   \n  ") == []


def test_claims_are_stripped_and_nonempty() -> None:
    for claim in split_claims("  One.   Two.  "):
        assert claim == claim.strip()
        assert claim


def test_hard_line_break_ends_a_claim() -> None:
    """Pooled evidence and list items are newline-joined; merging them would
    produce one claim that no single passage can support."""
    assert split_claims("france is in europe\nparis is the capital") == [
        "france is in europe",
        "paris is the capital",
    ]


def test_blank_lines_do_not_produce_empty_claims() -> None:
    assert split_claims("one\n\n\ntwo") == ["one", "two"]
