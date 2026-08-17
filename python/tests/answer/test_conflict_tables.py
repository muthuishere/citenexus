"""One canonical definition for the ADR-0007 tables, proven (ADR-0010 tier 2).

The five conflict tables used to be hand-declared in ``answer/tables.py``. They
now have exactly one source — ``conformance/conflict.json`` — and every port's
copy, Python's included, is generated from it by
``scripts/gen_conflict_tables.py``.

Three things have to hold for that to be safe, and each has a test here:

1. The generated Python copy is byte-identical *in membership* to the tables
   that shipped before the extraction. Those memberships are pinned literally
   below — not derived from the module under test, which would assert nothing.
2. The canonical file, the generated Python copy, and the emitted Go/TS copies
   all carry the same values, so no port is handed a table the reference does
   not use.
3. ``CONFLICT_NEGATIONS`` is still exactly the ADR-0007 derivation from
   ``POLARITY_MARKERS``. Generation removed the ``-`` operator from the source;
   it must not remove the invariant.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from citenexus.answer import conflict as conflict_module
from citenexus.answer.tables import (
    _NEGATION_EXTRAS,
    _SCOPE_RESTRICTORS,
    CONFLICT_ANTONYMS,
    CONFLICT_LANGUAGES,
    CONFLICT_NEGATIONS,
    CONFLICT_REPORT_BIGRAMS,
    CONFLICT_SCOPE_MARKERS,
    CONFLICT_THRESHOLDS,
    MEASUREMENT_UNITS,
    POLARITY_MARKERS,
)

_REPO_ROOT = Path(__file__).resolve().parents[2].parent
CANONICAL_PATH = _REPO_ROOT / "conformance" / "conflict.json"
CANONICAL: dict[str, Any] = json.loads(CANONICAL_PATH.read_text(encoding="utf-8"))

# ── The pre-extraction memberships, transcribed from the git history of
#    python/src/citenexus/answer/tables.py. Freezing them here is the whole
#    point: this file fails if the extraction changed a single token. ───────────

FROZEN_NEGATIONS = frozenset(
    {
        "absent", "cannot", "denied", "excluded", "fail", "failed", "fails",
        "forbidden", "lack", "lacks", "neither", "never", "no", "nobody",
        "none", "nor", "not", "nothing", "prohibited", "unable", "without",
    }
)  # fmt: skip

FROZEN_ANTONYMS = frozenset(
    {
        ("above", "below"), ("accelerates", "decelerates"),
        ("allowed", "forbidden"), ("approved", "rejected"),
        ("attracts", "repels"), ("before", "after"),
        ("eligible", "ineligible"), ("enabled", "disabled"),
        ("exceeds", "below"), ("expands", "contracts"), ("gain", "loss"),
        ("granted", "denied"), ("greater", "less"), ("greater", "lower"),
        ("higher", "lower"), ("increase", "decrease"),
        ("increased", "decreased"), ("increases", "decreases"),
        ("mandatory", "optional"), ("more", "less"), ("open", "closed"),
        ("passed", "failed"), ("permitted", "prohibited"), ("profit", "loss"),
        ("required", "optional"), ("rises", "falls"), ("rose", "fell"),
        ("surplus", "deficit"), ("upheld", "overturned"), ("valid", "invalid"),
    }
)  # fmt: skip

FROZEN_REPORT_BIGRAMS = frozenset(
    {
        ("allegation", "that"), ("argument", "that"), ("assertion", "that"),
        ("claim", "that"), ("claimed", "that"), ("claims", "that"),
        ("contention", "that"), ("hypothesis", "that"),
        ("misconception", "that"), ("myth", "that"), ("suggestion", "that"),
    }
)  # fmt: skip

FROZEN_SCOPE_MARKERS = frozenset(
    {
        "adult", "adults", "annual", "child", "children", "commercial",
        "daily", "domestic", "elderly", "gross", "hourly", "inbound",
        "infants", "international", "monthly", "neonates", "net", "offpeak",
        "offshore", "onshore", "outbound", "paediatric", "peak", "pediatric",
        "quarterly", "residential", "weekly",
    }
)  # fmt: skip

FROZEN_MEASUREMENT_UNITS = frozenset(
    {
        "a", "amps", "bar", "billion", "billions", "bp", "bps", "celsius",
        "cl", "cm", "day", "days", "degree", "degrees", "dl", "eur",
        "fahrenheit", "ft", "g", "gbp", "ghz", "hour", "hours", "hz", "inch",
        "inches", "j", "k", "kelvin", "kg", "khz", "km", "kmh", "kw", "l", "m",
        "mcg", "members", "mg", "mhz", "mi", "mile", "miles", "million",
        "millions", "minute", "minutes", "ml", "mm", "mol", "month", "months",
        "mph", "n", "pa", "pct", "people", "percent", "psi", "second",
        "seconds", "thousand", "ug", "units", "usd", "v", "volts", "w",
        "watts", "week", "weeks", "year", "years",
    }
)  # fmt: skip


def test_sizes_are_unchanged() -> None:
    assert len(CONFLICT_NEGATIONS) == 21
    assert len(CONFLICT_ANTONYMS) == 30
    assert len(CONFLICT_REPORT_BIGRAMS) == 11
    assert len(CONFLICT_SCOPE_MARKERS) == 27
    assert len(MEASUREMENT_UNITS) == 73


def test_membership_is_byte_identical_to_the_pre_extraction_tables() -> None:
    assert CONFLICT_NEGATIONS == FROZEN_NEGATIONS
    assert CONFLICT_REPORT_BIGRAMS == FROZEN_REPORT_BIGRAMS
    assert CONFLICT_SCOPE_MARKERS == FROZEN_SCOPE_MARKERS
    assert MEASUREMENT_UNITS == FROZEN_MEASUREMENT_UNITS


def test_antonym_pairs_are_unchanged_as_unordered_pairs() -> None:
    """Antonyms are UNORDERED pairs — the canonical file never carried direction.

    ``conformance/conflict.json`` has always emitted each pair alphabetised
    (``gen_conformance._conflict_table``: ``sorted(sorted(pair) ...)``), so 18 of
    the 30 pairs now come back in the opposite order to the pre-extraction
    literal — ``("increase", "decrease")`` reads back as
    ``("decrease", "increase")``. That is not a behaviour change and never could
    be: ``conflict._ANTONYMS`` symmetrises every pair before use, and the ports
    were always going to load the alphabetised form. Both facts are asserted
    here so nobody has to re-derive them.
    """
    assert {frozenset(p) for p in CONFLICT_ANTONYMS} == {frozenset(p) for p in FROZEN_ANTONYMS}
    assert frozenset(
        pair for a, b in FROZEN_ANTONYMS for pair in ((a, b), (b, a))
    ) == conflict_module._ANTONYMS
    # No pair is degenerate, so 30 unordered pairs symmetrise to exactly 60.
    assert len(conflict_module._ANTONYMS) == 60


def test_negations_are_still_derived_from_polarity_markers() -> None:
    """ADR-0007's subtraction, still enforced now that the source is generated.

    ``except`` / ``excluding`` / ``unless`` / ``other`` restrict SCOPE rather
    than flipping polarity; treating them as negations took the measured
    hard-negative false-conflict rate from 0.00 to 0.04.
    """
    assert CONFLICT_NEGATIONS == (POLARITY_MARKERS - _SCOPE_RESTRICTORS) | _NEGATION_EXTRAS
    assert _SCOPE_RESTRICTORS <= POLARITY_MARKERS
    assert not (_NEGATION_EXTRAS & POLARITY_MARKERS)


def test_python_copy_matches_the_canonical_file() -> None:
    assert sorted(CONFLICT_NEGATIONS) == CANONICAL["negations"]
    assert sorted(sorted(p) for p in CONFLICT_ANTONYMS) == CANONICAL["antonyms"]
    assert sorted(list(p) for p in CONFLICT_REPORT_BIGRAMS) == CANONICAL["report_bigrams"]
    assert sorted(CONFLICT_SCOPE_MARKERS) == CANONICAL["scope_markers"]
    assert sorted(MEASUREMENT_UNITS) == CANONICAL["measurement_units"]
    assert list(CONFLICT_LANGUAGES) == CANONICAL["languages"]


def test_thresholds_data_matches_the_runtime_constants() -> None:
    """The ports read the thresholds as data; the reference must actually use them."""
    assert CANONICAL["thresholds"] == CONFLICT_THRESHOLDS
    assert CONFLICT_THRESHOLDS == {
        "subject_overlap": conflict_module.SUBJECT_OVERLAP,
        "max_symdiff": conflict_module.MAX_SYMDIFF,
        "max_residual": conflict_module.MAX_RESIDUAL,
        "min_content": conflict_module.MIN_CONTENT,
        "duplicate_jaccard": conflict_module.DUPLICATE_JACCARD,
        "duplicate_max_length_delta": conflict_module.DUPLICATE_MAX_LENGTH_DELTA,
        "top_k": conflict_module.CONFLICT_TOP_K,
    }
    # Pinned by ADR-0007; relaxing MAX_RESIDUAL by one token cost 15pp of false
    # abstention in the spike sweep.
    assert conflict_module.MAX_RESIDUAL == 1
    assert conflict_module.SUBJECT_OVERLAP == 0.60
    assert conflict_module.MAX_SYMDIFF == 3
    assert conflict_module.MIN_CONTENT == 3
    assert conflict_module.DUPLICATE_JACCARD == 0.80


def test_generated_port_copies_are_current() -> None:
    """Every emitted file must match what the generator produces from canonical.

    Guards the whole family in one place: the Python module, the Go embedded
    JSON copy, the Go loader and the TS bundle.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "gen_conflict_tables", _REPO_ROOT / "python" / "scripts" / "gen_conflict_tables.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for path, expected in module.generate().items():
        assert Path(path).is_file(), f"missing generated file: {path}"
        assert Path(path).read_text(encoding="utf-8") == expected, (
            f"{path} is stale — regenerate with "
            "`cd python && uv run python scripts/gen_conflict_tables.py`"
        )
