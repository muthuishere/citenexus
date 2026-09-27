"""ADR-0015 amendment 2026-09-27 — mirrors golang/answer/numbers_locale_test.go.

Space grouping in a decimal-comma language, Swiss apostrophe grouping in any
language, Indian lakh grouping in a language that writes it; the verbatim
readings are bounded by the whole matched number.
"""

from __future__ import annotations

import pytest

from citenexus.answer.numbers import numbers_in, verbatim_in

NB = chr(0x202F)
NBSP = chr(0x00A0)


@pytest.mark.parametrize(
    ("text", "language", "want"),
    [
        ("Le montant est de 1 234,56.", "fr", ["1234.56"]),
        ("Le montant est de 1" + NB + "234,56.", "fr", ["1234.56"]),
        ("Der Betrag ist 1" + NBSP + "234" + NBSP + "567,89.", "de", ["1234567.89"]),
        ("De prijs is 1.234,56.", "de", ["1234.56"]),
        ("The total is 1 234.", "en", ["1", "234"]),
        ("Le total est 1 234 56.", "fr", ["1", "234", "56"]),
        ("Der Preis ist 1'234.50.", "de-CH", ["1234.5"]),
        ("Der Preis ist 1" + chr(0x2019) + "234.50.", "de", ["1234.5"]),
        ("The price is 1'234.50.", "en", ["1234.5"]),
        ("The price is 1'23.", "en", ["1", "23"]),
        ("The fee is 1,00,000.", "en-IN", ["100000"]),
        ("शुल्क 12,34,567.89 है", "hi", ["1234567.89"]),
        ("The fee is 1,00,000.", "", ["?1,00,000"]),
        ("De prijs is 1.500.", "sv", ["1500"]),
        ("The price is 1.500.", "xx", ["?1.500"]),
    ],
)
def test_numbers_in_locale_grouping(text: str, language: str, want: list[str]) -> None:
    assert [m.reading.key for m in numbers_in(text, language)] == want


@pytest.mark.parametrize(
    ("claim", "want"),
    [("4.000", "4000"), ("12", "12"), ("0,12", "0.12"), ("12.75", "12.75"), ("4.00", "4")],
)
def test_verbatim_numbers_are_whole_numbers(claim: str, want: str) -> None:
    vb = verbatim_in("Het budget is € 4.000, de toeslag € 0,12 en de fee € 12.750.", "nl")
    got = numbers_in("The amount is " + claim + " here.", "en", vb)
    assert [m.reading.key for m in got] == [want]
