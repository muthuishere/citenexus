"""ADR-0009: the ordered containment predicate and its polarity guard.

The adversarial fixtures are the nine from `spikes/library-stress/stress.py`,
each a FALSE answer with respect to its passage that the frozen predicate
accepts (measured 9/9 in Python, Go and JS). The control set is the thirty
legitimately-supported answers from `spikes/adr-0009-predicate/`, which pinned
false rejection at 0.0%.

Both sets matter equally. A predicate that rejects everything passes the attack
suite and is worthless, so the control set is the real constraint.
"""

from __future__ import annotations

import pytest

from citenexus.answer.tables import POLARITY_MARKERS
from citenexus.answer.verify import _STOPWORDS, is_supported, is_supported_v2

# ─────────────────────────────────────────────────────────────────────────────
# The nine attacks. Each `answer` is false w.r.t. its `passage`.
# ─────────────────────────────────────────────────────────────────────────────

ATTACKS = [
    # role inversion — identical token set, opposite meaning
    (
        "legal/role-inversion",
        "The tenant shall indemnify the landlord for damage to the property.",
        "The landlord shall indemnify the tenant for damage to the property.",
    ),
    (
        "finance/role-inversion",
        "The borrower pays the lender a fee of 400 basis points.",
        "The lender pays the borrower a fee of 400 basis points.",
    ),
    (
        "medical/role-inversion",
        "Ibuprofen increases the effect of warfarin in adult patients.",
        "Warfarin increases the effect of ibuprofen in adult patients.",
    ),
    # negation deletion — a strict subset, opposite meaning
    (
        "legal/negation-deletion",
        "The employee shall not disclose confidential information.",
        "The employee shall disclose confidential information.",
    ),
    (
        "operations/negation-deletion",
        "The reactor must not be restarted without a signed safety review.",
        "The reactor must be restarted without a signed safety review.",
    ),
    (
        "medical/negation-deletion",
        "This medication is not approved for patients under twelve years.",
        "This medication is approved for patients under twelve years.",
    ),
    # value swap across a shared token pool
    (
        "finance/value-swap",
        "Region A reported 40 million in revenue and region B reported 12 million.",
        "Region A reported 12 million in revenue and region B reported 40 million.",
    ),
    (
        "physics/value-swap",
        "The sample melts at 240 kelvin and boils at 610 kelvin.",
        "The sample melts at 610 kelvin and boils at 240 kelvin.",
    ),
    # comparator inversion
    (
        "physics/comparator-inversion",
        "Pressure in chamber one is greater than pressure in chamber two.",
        "Pressure in chamber two is greater than pressure in chamber one.",
    ),
]

# ─────────────────────────────────────────────────────────────────────────────
# The control set — legitimately supported answers, four shapes.
# ─────────────────────────────────────────────────────────────────────────────

_PASSAGES = {
    "legal": "The contractor shall maintain liability insurance at all times during the term.",
    "finance": "The borrower pays the lender a fee of 400 basis points on the outstanding balance.",
    "medical": "The recommended dose for adult patients is 500 milligrams taken once daily.",
    "operations": "The maintenance window opens at 02:00 UTC on Sunday and closes later.",
    "physics": "The detector threshold is calibrated to 4.5 gigaelectronvolts before each run.",
}

CONTROLS = (
    # verbatim
    [(f"verbatim/{k}", p, p) for k, p in _PASSAGES.items()]
    # leading sub-span
    + [
        ("subspan/legal", _PASSAGES["legal"], "The contractor shall maintain liability insurance"),
        (
            "subspan/finance",
            _PASSAGES["finance"],
            "The borrower pays the lender a fee of 400 basis points",
        ),
        (
            "subspan/medical",
            _PASSAGES["medical"],
            "The recommended dose for adult patients is 500 milligrams",
        ),
        (
            "subspan/operations",
            _PASSAGES["operations"],
            "The maintenance window opens at 02:00 UTC on Sunday",
        ),
        (
            "subspan/physics",
            _PASSAGES["physics"],
            "The detector threshold is calibrated to 4.5 gigaelectronvolts",
        ),
    ]
    # interior sub-span
    + [
        ("interior/legal", _PASSAGES["legal"], "maintain liability insurance at all times"),
        ("interior/finance", _PASSAGES["finance"], "a fee of 400 basis points"),
        ("interior/medical", _PASSAGES["medical"], "500 milligrams taken once daily"),
        ("interior/operations", _PASSAGES["operations"], "opens at 02:00 UTC on Sunday"),
        ("interior/physics", _PASSAGES["physics"], "calibrated to 4.5 gigaelectronvolts"),
    ]
    # punctuation / case / whitespace noise
    + [
        (
            "noise/legal",
            _PASSAGES["legal"],
            "  the CONTRACTOR shall maintain liability insurance!  ",
        ),
        (
            "noise/finance",
            _PASSAGES["finance"],
            "The borrower pays the lender a fee — of 400 basis points.",
        ),
        (
            "noise/medical",
            _PASSAGES["medical"],
            "the recommended DOSE for adult patients is 500 milligrams",
        ),
        (
            "noise/operations",
            _PASSAGES["operations"],
            "The maintenance window opens at 02:00 UTC, on Sunday.",
        ),
        (
            "noise/physics",
            _PASSAGES["physics"],
            "THE DETECTOR THRESHOLD IS CALIBRATED TO 4.5 GIGAELECTRONVOLTS",
        ),
    ]
    # compression — interior words dropped, order preserved (within the gap budget)
    + [
        ("compress/legal", _PASSAGES["legal"], "The contractor shall maintain insurance"),
        ("compress/finance", _PASSAGES["finance"], "The borrower pays a fee of 400 basis points"),
        ("compress/medical", _PASSAGES["medical"], "The recommended dose is 500 milligrams daily"),
        ("compress/operations", _PASSAGES["operations"], "The maintenance window opens on Sunday"),
        (
            "compress/physics",
            _PASSAGES["physics"],
            "The detector threshold is 4.5 gigaelectronvolts",
        ),
    ]
    # negation preserved — must still be accepted
    + [
        (
            "negation-kept/legal",
            "The employee shall not disclose confidential information.",
            "The employee shall not disclose confidential information.",
        ),
        (
            "negation-kept/medical",
            "This medication is not approved for patients under twelve years.",
            "This medication is not approved for patients under twelve",
        ),
        (
            "negation-kept/operations",
            "The reactor must not be restarted without a signed safety review.",
            "The reactor must not be restarted",
        ),
        (
            "negation-kept/finance",
            "The lender may not charge a fee above 400 basis points.",
            "The lender may not charge a fee",
        ),
        (
            "negation-kept/physics",
            "The sample does not melt below 240 kelvin.",
            "The sample does not melt below 240 kelvin.",
        ),
    ]
)


@pytest.mark.parametrize(("name", "passage", "answer"), ATTACKS, ids=[a[0] for a in ATTACKS])
def test_attack_is_rejected(name: str, passage: str, answer: str) -> None:
    """A false answer must be rejected even though every token is in the passage."""
    assert is_supported_v2(answer, passage) is False


@pytest.mark.parametrize(("name", "passage", "answer"), CONTROLS, ids=[c[0] for c in CONTROLS])
def test_control_is_accepted(name: str, passage: str, answer: str) -> None:
    """A legitimately supported answer must not be rejected — false rejection is 0%."""
    assert is_supported_v2(answer, passage) is True


def test_frozen_predicate_still_accepts_every_attack() -> None:
    """Pins WHY this change exists: the frozen gate accepts all nine."""
    assert all(is_supported(answer, passage) for _, passage, answer in ATTACKS)


@pytest.mark.parametrize(
    ("name", "passage", "answer"),
    ATTACKS + CONTROLS,
    ids=[c[0] for c in ATTACKS + CONTROLS],
)
def test_v2_is_strictly_narrower(name: str, passage: str, answer: str) -> None:
    """Anything v2 accepts, the frozen predicate already accepted.

    This is the safety property: the new predicate can only reduce what passes,
    so it can never admit an ungrounded claim that v1 blocked.
    """
    if is_supported_v2(answer, passage):
        assert is_supported(answer, passage)


def test_empty_claim_is_rejected() -> None:
    assert is_supported_v2("", "some passage") is False
    assert is_supported_v2("anything", "") is False


def test_polarity_table_is_not_derived_from_stopwords() -> None:
    """ADR-0009: `_STOPWORDS` wrongly classifies `no`/`not` as stopwords, so the
    relevance gate is already blind to negation. The polarity table must be an
    independent asset, not a slice of that set."""
    assert "not" in _STOPWORDS and "no" in _STOPWORDS  # the existing defect
    assert "not" in POLARITY_MARKERS and "no" in POLARITY_MARKERS
    assert not POLARITY_MARKERS <= _STOPWORDS
