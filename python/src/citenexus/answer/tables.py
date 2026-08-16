"""Tier-2 linguistic tables for claim verification (ADR-0009, ADR-0010).

ADR-0010 tier 2: a language-dependent *table* is the asset; the code reading it
is trivial. There is one canonical definition and every port's copy is
**generated** from it, never hand-maintained. Per this repo's established
mechanism (`conformance/README.md`), the Python module is the reference and
`scripts/gen_conformance.py` emits `conformance/polarity.json` and
`conformance/segmentation.json` from it, exactly as it already does for
`stopwords.json`.

A language may not be *claimed* by the polarity table until a golden fixture
exists for it. The ADR-0007 spike measured why that rule is hard rather than
aspirational: corrupting a polarity table raises false abstention while recall
stays flat, so the failure is silent and no internal metric degrades. An absent
language abstains loudly; a wrong one abstains quietly.
"""

from __future__ import annotations

__all__ = [
    "ABBREVIATIONS",
    "CONFLICT_ANTONYMS",
    "CONFLICT_NEGATIONS",
    "CONFLICT_REPORT_BIGRAMS",
    "CONFLICT_SCOPE_MARKERS",
    "MEASUREMENT_UNITS",
    "POLARITY_LANGUAGES",
    "POLARITY_MARKERS",
    "TERMINATORS",
]

# Languages whose polarity markers are covered by a golden fixture. Adding a
# language here without a fixture is the silent-failure mode described above.
POLARITY_LANGUAGES: tuple[str, ...] = ("en",)

# Polarity markers: tokens whose DELETION flips the meaning of a claim. Kept
# deliberately small and closed — this is not a sentiment lexicon, and a marker
# that does not flip meaning on deletion only costs false abstention.
#
# Frozen as measured: this exact set produced 9/9 adversarial rejections at 0.0%
# false rejection in spikes/adr-0009-predicate/. Changing it invalidates that
# measurement, so additions require re-running the spike.
POLARITY_MARKERS: frozenset[str] = frozenset(
    {
        "absent",
        "cannot",
        "denied",
        "except",
        "excluding",
        "failed",
        "fails",
        "forbidden",
        "neither",
        "never",
        "no",
        "nobody",
        "none",
        "nor",
        "not",
        "nothing",
        "other",
        "prohibited",
        "unless",
        "without",
    }
)

# Sentence terminators, including the CJK and Arabic/Indic forms. The ADR-0009
# spike measured that adding these to the *table* fixed 100% of the Japanese
# segmentation failures — no algorithm change was required, which is why claim
# segmentation stays ADR-0010 tier 1.
TERMINATORS: str = ".!?。！？؟۔।॥‼⁇⁈⁉"  # noqa: RUF001 — fullwidth/RTL marks are the point

# Tokens that end in a terminator without ending a sentence.
ABBREVIATIONS: frozenset[str] = frozenset(
    {
        "abs",
        "al",
        "art",
        "bv",
        "bzw",
        "cf",
        "dhr",
        "dr",
        "eg",
        "etc",
        "fig",
        "ggf",
        "ie",
        "jr",
        "mevr",
        "mr",
        "mrs",
        "ms",
        "no",
        "nr",
        "para",
        "prof",
        "resp",
        "sec",
        "sr",
        "st",
        "usw",
        "vgl",
        "vs",
        "zb",
        "ziff",
    }
)

# ─────────────────────────────────────────────────────────────────────────────
# ADR-0007 conflict-surfacing tables.
#
# These are a SECOND USE of the same tier-2 asset, not a second table. The
# negation set is *derived* from ``POLARITY_MARKERS`` so the two features can
# never drift apart, minus the scope-restrictors below.
#
# The subtraction is measured, not stylistic. ``except`` / ``excluding`` /
# ``unless`` / ``other`` restrict a claim's SCOPE; they do not flip its polarity.
# For the faithfulness gate that distinction does not matter (deleting them still
# changes meaning, so they belong in POLARITY_MARKERS). For conflict detection it
# matters a great deal: the ADR-0007 spike measured that treating them as
# negations takes the hard-negative false-conflict rate from 0.00 to 0.04 — and
# in strict mode every false conflict is a FALSE REFUSAL, on a pair of passages
# that do not disagree ("All employees except contractors receive the allowance"
# does not contradict "All employees receive the allowance").
#
# Same golden-fixture rule as POLARITY_MARKERS, and a sharper reason for it: a
# corrupted conflict table raises false abstention while recall stays flat, so
# nothing inside the detector degrades when the data gets worse. Only refusals go
# up. English only until a language has hard-negative fixtures of its own.
_SCOPE_RESTRICTORS: frozenset[str] = frozenset({"except", "excluding", "other", "unless"})

CONFLICT_NEGATIONS: frozenset[str] = (POLARITY_MARKERS - _SCOPE_RESTRICTORS) | frozenset(
    {
        "excluded",
        "fail",
        "lack",
        "lacks",
        "unable",
    }
)

# Antonym pairs, stored in one direction and symmetrised by the reader. Kept
# closed and boring: the spike measured that four *plausible-looking* additions
# (oral/intravenous, staging/production, heated/cooled, backups/snapshots) take
# the false-conflict rate from 0.00 to 0.07, because they are scope distinctions
# wearing an antonym's clothes. If a candidate pair can appear in two passages
# that are both true, it is not an antonym.
CONFLICT_ANTONYMS: frozenset[tuple[str, str]] = frozenset(
    {
        ("above", "below"),
        ("accelerates", "decelerates"),
        ("allowed", "forbidden"),
        ("approved", "rejected"),
        ("attracts", "repels"),
        ("before", "after"),
        ("eligible", "ineligible"),
        ("enabled", "disabled"),
        ("exceeds", "below"),
        ("expands", "contracts"),
        ("gain", "loss"),
        ("granted", "denied"),
        ("greater", "less"),
        ("greater", "lower"),
        ("higher", "lower"),
        # Every inflection must be listed: the pinned tokenizer does not stem,
        # and the conflict detector's plural fold covers a trailing -s only.
        # This is the standing maintenance cost of an antonym table and the
        # honest reason it stays English-only for now.
        ("increase", "decrease"),
        ("increased", "decreased"),
        ("increases", "decreases"),
        ("mandatory", "optional"),
        ("more", "less"),
        ("open", "closed"),
        ("passed", "failed"),
        ("permitted", "prohibited"),
        ("profit", "loss"),
        ("required", "optional"),
        ("rises", "falls"),
        ("rose", "fell"),
        ("surplus", "deficit"),
        ("upheld", "overturned"),
        ("valid", "invalid"),
    }
)

# Reported speech: a negation inside a quoted assertion belongs to a third party,
# not to the passage's own claim ("The claim that the device is not compliant was
# rejected" does not contradict "The device is compliant").
#
# BIGRAMS, deliberately. As unigrams these markers silently disable conflict
# detection across most legal text, where "claim" is a noun of art — the spike
# lost a true conflict ("The claim for indemnity is / is not valid") to exactly
# that. Only the complementizer form introduces reported speech.
CONFLICT_REPORT_BIGRAMS: frozenset[tuple[str, str]] = frozenset(
    {
        ("allegation", "that"),
        ("argument", "that"),
        ("assertion", "that"),
        ("claim", "that"),
        ("claimed", "that"),
        ("claims", "that"),
        ("contention", "that"),
        ("hypothesis", "that"),
        ("misconception", "that"),
        ("myth", "that"),
        ("suggestion", "that"),
    }
)

# Qualifiers that make two passages complementary rather than contradictory. The
# spike measured this list as currently INERT — deleting it changed no verdict,
# because the residual guard already caught every case on single-sentence
# fixtures. It is kept as cheap insurance for multi-clause Evidence Units and is
# explicitly NOT credited with the measured false-conflict rate.
CONFLICT_SCOPE_MARKERS: frozenset[str] = frozenset(
    {
        "adult",
        "adults",
        "annual",
        "child",
        "children",
        "commercial",
        "daily",
        "domestic",
        "elderly",
        "gross",
        "hourly",
        "inbound",
        "infants",
        "international",
        "monthly",
        "neonates",
        "net",
        "offpeak",
        "offshore",
        "onshore",
        "outbound",
        "paediatric",
        "peak",
        "pediatric",
        "quarterly",
        "residential",
        "weekly",
    }
)

# Unit tokens. A numeric divergence is only a conflict when both sides carry the
# SAME units, which suppresses "1 g" vs "1000 mg" and "2 hours" vs "120 minutes"
# without the detector knowing a single conversion factor.
MEASUREMENT_UNITS: frozenset[str] = frozenset(
    {
        "a",
        "amps",
        "bar",
        "billion",
        "billions",
        "bp",
        "bps",
        "celsius",
        "cl",
        "cm",
        "day",
        "days",
        "degree",
        "degrees",
        "dl",
        "eur",
        "fahrenheit",
        "ft",
        "g",
        "gbp",
        "ghz",
        "hour",
        "hours",
        "hz",
        "inch",
        "inches",
        "j",
        "k",
        "kelvin",
        "kg",
        "khz",
        "km",
        "kmh",
        "kw",
        "l",
        "m",
        "mcg",
        "members",
        "mg",
        "mhz",
        "mi",
        "mile",
        "miles",
        "million",
        "millions",
        "minute",
        "minutes",
        "ml",
        "mm",
        "mol",
        "month",
        "months",
        "mph",
        "n",
        "pa",
        "pct",
        "people",
        "percent",
        "psi",
        "second",
        "seconds",
        "thousand",
        "ug",
        "units",
        "usd",
        "v",
        "volts",
        "w",
        "watts",
        "week",
        "weeks",
        "year",
        "years",
    }
)
