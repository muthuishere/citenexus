"""TrustMode enum (spec §14)."""

from trustrag.domain.trust import TrustMode


def test_trust_modes_are_exactly_three() -> None:
    assert {m.value for m in TrustMode} == {"strict", "normal", "exploratory"}
