"""ADR-0009: the ordered containment predicate and its polarity guard.

The English adversarial fixtures are the nine from `spikes/library-stress/stress.py`,
each a FALSE answer with respect to its passage that the frozen predicate
accepts (measured 9/9 in Python, Go and JS). The control set is the thirty
legitimately-supported answers from `spikes/adr-0009-predicate/`, which pinned
false rejection at 0.0%. The Dutch sets (``DUTCH_ATTACKS`` / ``DUTCH_CONTROLS``)
are the golden fixture behind the "nl" claim in ``POLARITY_LANGUAGES``.

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
# Dutch ("nl") — the golden fixture that lets POLARITY_LANGUAGES claim "nl".
#
# One negation-deletion attack per Dutch marker, each written so the marker
# sits INSIDE the matched span (the guard inspects only the span; see the
# known-gap test at the bottom of this file for the clause-final case it cannot
# see). Every one of these is accepted by the frozen predicate AND was accepted
# by ``is_supported_v2`` before the Dutch markers existed.
# ─────────────────────────────────────────────────────────────────────────────

DUTCH_ATTACKS = [
    (
        "nl/negation-deletion (niet)",
        "De werknemer mag vertrouwelijke informatie niet aan derden verstrekken.",
        "De werknemer mag vertrouwelijke informatie aan derden verstrekken.",
    ),
    (
        "nl/negation-deletion (geen)",
        "Een uitzendkracht heeft geen recht op de eindejaarsuitkering.",
        "Een uitzendkracht heeft recht op de eindejaarsuitkering.",
    ),
    (
        "nl/negation-deletion (nooit)",
        "Wachtwoorden mogen nooit per e-mail worden gedeeld.",
        "Wachtwoorden mogen per e-mail worden gedeeld.",
    ),
    (
        "nl/negation-deletion (zonder)",
        "Overwerk wordt zonder schriftelijke goedkeuring uitbetaald.",
        "Overwerk wordt schriftelijke goedkeuring uitbetaald.",
    ),
    (
        "nl/negation-deletion (niemand)",
        "Buiten kantooruren mag niemand de serverruimte betreden.",
        "Buiten kantooruren mag de serverruimte betreden.",
    ),
    (
        "nl/negation-deletion (niets)",
        "De werkgever vergoedt niets van de reiskosten bij thuiswerk.",
        "De werkgever vergoedt van de reiskosten bij thuiswerk.",
    ),
    (
        "nl/negation-deletion (verboden)",
        "Roken is verboden in alle bedrijfsgebouwen.",
        "Roken is in alle bedrijfsgebouwen.",
    ),
    (
        "nl/negation-deletion (one noch of two)",
        "Noch de proeftijd noch de opzegtermijn mag worden verlengd.",
        "Noch de proeftijd de opzegtermijn mag worden verlengd.",
    ),
    # scope restrictors: dropping the restriction widens the claim to a
    # population the passage explicitly excludes
    (
        "nl/restrictor-deletion (behalve)",
        "Alle medewerkers behalve stagiairs ontvangen een laptop.",
        "Alle medewerkers ontvangen een laptop.",
    ),
    (
        "nl/restrictor-deletion (uitgezonderd)",
        "Alle functies uitgezonderd de directie vallen onder de cao.",
        "Alle functies vallen onder de cao.",
    ),
    (
        "nl/restrictor-deletion (tenzij)",
        "Het verlof wordt tenzij anders overeengekomen in hele dagen opgenomen.",
        "Het verlof wordt in hele dagen opgenomen.",
    ),
]

#: Legitimately-supported Dutch answers. Each keeps every marker inside its span
#: or drops only non-marker words, so a Dutch table that over-reaches shows up
#: here as false abstention.
DUTCH_CONTROLS = [
    (
        "nl/verbatim-negated",
        "Een uitzendkracht heeft geen recht op de eindejaarsuitkering.",
        "Een uitzendkracht heeft geen recht op de eindejaarsuitkering.",
    ),
    (
        "nl/negation-kept-compressed",
        "De werknemer mag vertrouwelijke informatie niet aan derden verstrekken.",
        "De werknemer mag informatie niet aan derden verstrekken",
    ),
    (
        "nl/compress",
        "De werkgever vergoedt de reiskosten voor woon-werkverkeer maandelijks achteraf.",
        "De werkgever vergoedt de reiskosten maandelijks achteraf",
    ),
    (
        "nl/subspan",
        "De proeftijd bedraagt twee maanden bij een contract voor onbepaalde tijd.",
        "De proeftijd bedraagt twee maanden",
    ),
    (
        "nl/noise",
        "De opzegtermijn voor de werkgever is een maand per vijf dienstjaren.",
        "  de OPZEGTERMIJN voor de werkgever is een maand!  ",
    ),
    (
        "nl/markers-kept",
        "Buiten kantooruren mag niemand zonder begeleiding de serverruimte betreden.",
        "Buiten kantooruren mag niemand zonder begeleiding de serverruimte betreden",
    ),
    (
        "nl/double-noch-kept",
        "Noch de proeftijd noch de opzegtermijn mag worden verlengd.",
        "noch de proeftijd noch de opzegtermijn mag worden verlengd",
    ),
    (
        "nl/restrictor-kept-compressed",
        "Alle medewerkers behalve stagiairs ontvangen jaarlijks een nieuwe laptop.",
        "Alle medewerkers behalve stagiairs ontvangen een laptop",
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

# Dutch fixtures join the shared sets, so every port runs them from
# conformance/cases/faithful_v2.json.
ATTACKS += DUTCH_ATTACKS
CONTROLS += DUTCH_CONTROLS


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


def test_known_gap_clause_final_dutch_negation() -> None:
    """KNOWN GAP, pinned: the guard inspects only the MATCHED span.

    Dutch puts ``niet`` after the object in a main clause ("De werkgever vergoedt
    de parkeerkosten niet."), so a claim that stops before it matches a span the
    marker is not inside, and the deletion is accepted. The English analogue is a
    leading marker ("No employee may ..."). The table cannot close this; the
    predicate's span rule would have to look one token past the span.
    """
    passage = "De werkgever vergoedt de parkeerkosten niet."
    assert is_supported_v2("De werkgever vergoedt de parkeerkosten.", passage) is True
    # an interior "niet" IS caught
    assert (
        is_supported_v2(
            "De werkgever vergoedt de parkeerkosten volledig.",
            "De werkgever vergoedt de parkeerkosten niet volledig.",
        )
        is False
    )
