"""TrustMode — the three answering postures (spec §14)."""

from __future__ import annotations

from enum import StrEnum


class TrustMode(StrEnum):
    """How aggressively the system is willing to answer.

    - ``strict``: legal/medical/compliance — min sources enforced, citations
      mandatory, unsupported claims removed, low evidence ⇒ refusal.
    - ``normal``: general enterprise search — citations preferred, moderate
      evidence allowed.
    - ``exploratory``: brainstorming — weak evidence may be summarized, with
      speculation explicitly labeled; never for regulated domains.
    """

    strict = "strict"
    normal = "normal"
    exploratory = "exploratory"
