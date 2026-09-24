"""Re-measure ADR-0009 and ADR-0007 with the SHIPPED tables, split by language.

The two original spikes (``spikes/adr-0009-predicate/``,
``spikes/adr-0007-conflict/``) carry their own frozen copies of the tables, so
re-running them cannot see a table change. This is their equivalent: the same
fixture sets, run through the shipped ``is_supported_v2`` / ``detect_conflict``,
which read the generated tables. Run it before and after a table change and
compare; English numbers must not move.

It also measures the Dutch candidates that were REJECTED, the Dutch-stopword
question, and the known gaps, by monkeypatching the reference module in-process.
Nothing is written.

Run:  cd python && uv run python ../spikes/nl-tables/measure.py
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "python"))  # tests.answer.* fixtures
sys.path.insert(0, str(REPO / "spikes" / "adr-0009-predicate"))
sys.path.insert(0, str(REPO / "spikes" / "library-stress"))

from tests.answer import test_conflict as TC  # noqa: E402
from tests.answer import test_verify_v2 as TV  # noqa: E402

from citenexus.answer import conflict as C  # noqa: E402
from citenexus.answer import verify as V  # noqa: E402
from citenexus.answer.conflict import detect_conflict  # noqa: E402
from citenexus.answer.tables import CONFLICT_LANGUAGES, POLARITY_LANGUAGES  # noqa: E402
from citenexus.answer.verify import is_supported_v2  # noqa: E402


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


S9 = _load("spike0009", REPO / "spikes" / "adr-0009-predicate" / "spike.py")
S7 = _load("spike0007", REPO / "spikes" / "adr-0007-conflict" / "spike.py")


def is_nl(domain_or_name: str) -> bool:
    return domain_or_name.startswith("nl/") or domain_or_name.endswith("-nl")


def rate(n: int, d: int) -> str:
    return f"{n}/{d} ({(n / d if d else 0):.3f})"


# ─────────────────────────────────────────────────────────────────────────────
# ADR-0009
# ─────────────────────────────────────────────────────────────────────────────


def adr0009() -> None:
    print("ADR-0009 — shipped is_supported_v2")
    print(f"  POLARITY_LANGUAGES = {POLARITY_LANGUAGES}   markers = {len(V.POLARITY_MARKERS)}")
    atk = S9.GATE_CASES
    rej = sum(not is_supported_v2(c.answer, c.passage) for c in atk)
    ctl = S9.CONTROL
    fr = sum(not is_supported_v2(c.answer, c.passage) for c in ctl)
    print(
        f"  spike set   : attacks rejected {rate(rej, len(atk))}   "
        f"false rejection {rate(fr, len(ctl))}"
    )
    for lang, pick in (("en", lambda n: not is_nl(n)), ("nl", is_nl)):
        a = [c for c in TV.ATTACKS if pick(c[0])]
        k = [c for c in TV.CONTROLS if pick(c[0])]
        rj = [c[0] for c in a if not is_supported_v2(c[2], c[1])]
        fj = [c[0] for c in k if not is_supported_v2(c[2], c[1])]
        print(
            f"  fixtures {lang}: attacks rejected {rate(len(rj), len(a))}   "
            f"false rejection {rate(len(fj), len(k))}"
        )
        for name in sorted({c[0] for c in a} - set(rj)):
            print(f"      accepted attack: {name}")
        for name in fj:
            print(f"      rejected control: {name}")


# ─────────────────────────────────────────────────────────────────────────────
# ADR-0007
# ─────────────────────────────────────────────────────────────────────────────

Detector = Callable[[str, str], Any]


def score(pairs: list[tuple[str, str, str, str]], det: Detector) -> list[str]:
    return [f"{p[0]}/{p[1]}" for p in pairs if det(p[2], p[3]) is not None]


def conflict_report(det: Detector, *, verbose: bool = True) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    sets = {
        "spike true_conflicts (recall)": S7.TRUE_CONFLICTS,
        "spike hard_negatives (FP)": S7.HARD_NEGATIVES,
        "spike unrelated (FP)": S7.UNRELATED,
        "spike heldout_conflicts (recall)": S7.HELDOUT_CONFLICTS,
        "spike heldout_negatives (FP)": S7.HELDOUT_NEGATIVES,
    }
    for lang, pick in (("en", lambda d: not is_nl(d)), ("nl", is_nl)):
        sets[f"fixtures {lang} true_conflicts (recall)"] = [
            p for p in TC.TRUE_CONFLICTS if pick(p[0])
        ]
        sets[f"fixtures {lang} hard_negatives (FP)"] = [p for p in TC.HARD_NEGATIVES if pick(p[0])]
        sets[f"fixtures {lang} unrelated (FP)"] = [p for p in TC.UNRELATED if pick(p[0])]
    for name, pairs in sets.items():
        hits = score(pairs, det)
        out[name] = (len(hits), len(pairs))
        if verbose:
            print(f"  {name:<40} {rate(len(hits), len(pairs))}")
            if "(FP)" in name:
                for h in hits:
                    print(f"      FALSE CONFLICT: {h}")
            elif len(hits) < len(pairs):
                for p in pairs:
                    if det(p[2], p[3]) is None:
                        print(f"      missed: {p[0]}/{p[1]}")
    nl_rows = list(TC.NON_LATIN)
    ok = sum(((det(c[2], c[3]) or None) and det(c[2], c[3]).rule) == c[4] for c in nl_rows)
    out["non_latin (verdict+rule matches intent)"] = (ok, len(nl_rows))
    if verbose:
        print(f"  {'non_latin verdict+rule == intent':<40} {rate(ok, len(nl_rows))}")
    return out


def adr0007() -> None:
    print("\nADR-0007 — shipped detect_conflict")
    print(
        f"  CONFLICT_LANGUAGES = {CONFLICT_LANGUAGES}   negations = {len(C.CONFLICT_NEGATIONS)}"
        f"   antonym pairs (symmetrised) = {len(C._ANTONYMS)}"
    )
    conflict_report(detect_conflict)


# ─────────────────────────────────────────────────────────────────────────────
# Candidates and probes, by monkeypatching the reference in-process
# ─────────────────────────────────────────────────────────────────────────────


@contextmanager
def patched(**attrs: Any) -> Iterator[None]:
    saved = {k: getattr(C, k) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(C, k, v)
        yield
    finally:
        for k, v in saved.items():
            setattr(C, k, v)


def with_antonyms(*pairs: tuple[str, str]) -> dict[str, Any]:
    sym = {q for a, b in pairs for q in ((a, b), (b, a))}
    return {"_FOLDED_ANTONYMS": C._FOLDED_ANTONYMS | {(C._fold(a), C._fold(b)) for a, b in sym}}


PROBES_TRUE = [
    (
        "finance-nl",
        "incl/excl same amount",
        "De vergoeding is € 25 inclusief btw.",
        "De vergoeding is € 25 exclusief btw.",
    ),
    (
        "finance-nl",
        "incl./excl. same amount",
        "De vergoeding is € 25 incl. btw.",
        "De vergoeding is € 25 excl. btw.",
    ),
    (
        "hr-nl",
        "meer/minder same threshold",
        "Parttimers werken meer dan 20 uur per week.",
        "Parttimers werken minder dan 20 uur per week.",
    ),
    (
        "hr-nl",
        "hoger/lager",
        "De bijdrage voor schaal 8 is hoger dan het landelijk gemiddelde.",
        "De bijdrage voor schaal 8 is lager dan het landelijk gemiddelde.",
    ),
    (
        "hr-nl",
        "met/zonder toestemming",
        "Thuiswerken is toegestaan met toestemming.",
        "Thuiswerken is toegestaan zonder toestemming.",
    ),
]


def candidates() -> None:
    print("\nCANDIDATES — what each rejected entry would do if added")
    trials: list[tuple[str, dict[str, Any]]] = [
        (
            "+ antonym inclusief/exclusief + incl/excl",
            with_antonyms(("exclusief", "inclusief"), ("excl", "incl")),
        ),
        ("+ antonym meer/minder", with_antonyms(("meer", "minder"))),
        ("+ antonym hoger/lager", with_antonyms(("hoger", "lager"))),
        ("+ antonym toegestaan/verboden", with_antonyms(("toegestaan", "verboden"))),
        (
            "+ zonder as a conflict negation",
            {"CONFLICT_NEGATIONS": C.CONFLICT_NEGATIONS | {"zonder"}},
        ),
        (
            "+ behalve/uitgezonderd/tenzij as conflict negations",
            {"CONFLICT_NEGATIONS": C.CONFLICT_NEGATIONS | {"behalve", "uitgezonderd", "tenzij"}},
        ),
    ]
    base = conflict_report(detect_conflict, verbose=False)
    base_probe = score(PROBES_TRUE, detect_conflict)
    for label, attrs in trials:
        with patched(**attrs):
            got = conflict_report(detect_conflict, verbose=False)
            probe = score(PROBES_TRUE, detect_conflict)
            fp = [
                f"{p[0]}/{p[1]}"
                for p in TC.HARD_NEGATIVES + TC.UNRELATED + TC.HELDOUT_NEGATIVES
                if detect_conflict(p[2], p[3]) is not None
            ]
        moved = {k: (base[k], v) for k, v in got.items() if v != base[k]}
        print(f"  {label}")
        for k, (b, a) in moved.items():
            print(f"      {k}: {b[0]}/{b[1]} -> {a[0]}/{a[1]}")
        print(
            f"      probe true conflicts caught: {len(base_probe)} -> {len(probe)} "
            f"{sorted(set(probe) - set(base_probe))}"
        )
        for f in fp:
            print(f"      FALSE CONFLICT: {f}")


# A PROTOTYPE, measured here only — not shipped. The antonym rule ignores numbers,
# so a pair quoting DIFFERENT amounts ("€ 100 excl. btw" / "€ 121 incl. btw")
# conflicts. Declining an antonym when both sides carry numbers that differ is
# the smallest rule change that would make inclusief/exclusief admissible.
def _antonym_needs_equal_numbers(left: str, right: str) -> Any:
    finding = detect_conflict(left, right)
    if finding is None or finding.rule != "antonym":
        return finding
    a, b = C._features(left), C._features(right)
    if a.numbers and b.numbers and a.numbers != b.numbers:
        with patched(_FOLDED_ANTONYMS=frozenset()):
            return detect_conflict(left, right)
    return finding


def prototype_guard() -> None:
    print("\nPROTOTYPE (not shipped): antonym declines when both sides carry DIFFERENT numbers,")
    print("  with inclusief/exclusief, incl/excl, meer/minder, hoger/lager added")
    attrs = with_antonyms(
        ("exclusief", "inclusief"), ("excl", "incl"), ("meer", "minder"), ("hoger", "lager")
    )
    base = conflict_report(detect_conflict, verbose=False)
    with patched(**attrs):
        got = conflict_report(_antonym_needs_equal_numbers, verbose=False)
        probe = score(PROBES_TRUE, _antonym_needs_equal_numbers)
        fp = [
            f"{p[0]}/{p[1]}"
            for p in TC.HARD_NEGATIVES + TC.UNRELATED + TC.HELDOUT_NEGATIVES
            if _antonym_needs_equal_numbers(p[2], p[3]) is not None
        ]
    for k, v in got.items():
        if v != base[k]:
            print(f"      {k}: {base[k][0]}/{base[k][1]} -> {v[0]}/{v[1]}")
    print(f"      probe true conflicts caught: {sorted(probe)}")
    print(f"      false conflicts on all negative sets: {fp or 'none'}")


# Candidate Dutch stopwords — the closed-class words that would plausibly join
# conformance/stopwords.json. Measured, NOT proposed for shipping unless needed.
NL_STOP = frozenset(
    [
        "de",
        "het",
        "een",
        "en",
        "van",
        "in",
        "op",
        "te",
        "dat",
        "die",
        "voor",
        "met",
        "aan",
        "bij",
        "door",
        "om",
        "als",
        "is",
        "zijn",
        "wordt",
        "worden",
        "er",
        "ook",
        "of",
        "dan",
        "naar",
        "tot",
        "uit",
        "over",
        "na",
        "per",
        "heeft",
        "hebben",
        "kan",
        "mag",
        "moet",
    ]
)


def stopwords() -> None:
    print("\nSTOPWORDS — do Dutch function words break the conflict guards?")
    rows = [p for p in TC.TRUE_CONFLICTS + TC.HARD_NEGATIVES + TC.UNRELATED if is_nl(p[0])]
    rows += PROBES_TRUE + LONG
    base = {(p[0], p[1]): detect_conflict(p[2], p[3]) for p in rows}
    with patched(_STOPWORDS=C._STOPWORDS | NL_STOP):
        after = {(p[0], p[1]): detect_conflict(p[2], p[3]) for p in rows}
    changed = [k for k in base if (base[k] is None) != (after[k] is None)]
    print(
        f"  {len(rows)} Dutch pairs; verdicts changed by adding {len(NL_STOP)} Dutch stopwords: "
        f"{len(changed)}"
    )
    for k in changed:
        print(f"      {k[0]}/{k[1]}: {base[k]} -> {after[k]}")
    for p in LONG:
        a, b = C._features(p[2]), C._features(p[3])
        div = (a.content | b.content) - (a.content & b.content)
        print(
            f"  long: {p[1]:<44} content={len(a.content)}/{len(b.content)} "
            f"divergence={sorted(div)} -> {detect_conflict(p[2], p[3])}"
        )


LONG = [
    (
        "hr-nl",
        "long: niet, verb-final subordinate clause",
        "Indien de medewerker tijdens de proeftijd ziek wordt, wordt het loon door de werkgever "
        "gedurende de eerste twee dagen van de ziekte doorbetaald.",
        "Indien de medewerker tijdens de proeftijd ziek wordt, wordt het loon door de werkgever "
        "gedurende de eerste twee dagen van de ziekte niet doorbetaald.",
    ),
    (
        "hr-nl",
        "long: geen, 40+ tokens",
        "Een medewerker met een arbeidsovereenkomst voor bepaalde tijd van ten minste zes maanden "
        "die op de einddatum van het contract bij de werkgever in dienst is, heeft recht op een "
        "aanzegvergoeding ter hoogte van een maandsalaris.",
        "Een medewerker met een arbeidsovereenkomst voor bepaalde tijd van ten minste zes maanden "
        "die op de einddatum van het contract bij de werkgever in dienst is, heeft geen recht op "
        "een aanzegvergoeding ter hoogte van een maandsalaris.",
    ),
    (
        "hr-nl",
        "long: paraphrase + negation (should decline)",
        "De werkgever vergoedt de kosten van de opleiding volledig.",
        "De kosten van de opleiding worden door de werkgever niet volledig vergoed.",
    ),
    (
        "hr-nl",
        "long: value, different amount",
        "De thuiswerkvergoeding bedraagt voor iedere volledig thuis gewerkte dag 2 euro netto, "
        "uit te betalen met het salaris van de volgende maand.",
        "De thuiswerkvergoeding bedraagt voor iedere volledig thuis gewerkte dag 3 euro netto, "
        "uit te betalen met het salaris van de volgende maand.",
    ),
]


def known_gaps() -> None:
    print("\nKNOWN GAPS (measured, not fixed by a table)")
    gate = [
        (
            "clause-final niet (outside the matched span)",
            "De werkgever vergoedt de parkeerkosten niet.",
            "De werkgever vergoedt de parkeerkosten.",
        ),
        (
            "clause-final niet, English analogue (leading marker)",
            "No employee may access the archive.",
            "employee may access the archive.",
        ),
    ]
    for label, passage, claim in gate:
        print(f"  gate  {label:<52} supported={is_supported_v2(claim, passage)}")
    pairs = [
        (
            "negated relative clause (nl) — both true",
            "Medewerkers die geen lid zijn van de pensioenregeling ontvangen een toeslag.",
            "Medewerkers die lid zijn van de pensioenregeling ontvangen een toeslag.",
        ),
        (
            "negated relative clause (en) — both true",
            "Employees who are not members of the pension plan receive an allowance.",
            "Employees who are members of the pension plan receive an allowance.",
        ),
        (
            "Dutch thousands separator — same amount",
            "Het opleidingsbudget is € 1.500 per jaar.",
            "Het opleidingsbudget is € 1500 per jaar.",
        ),
        (
            "Dutch decimal comma — same amount",
            "De vergoeding is € 25,00 per maand.",
            "De vergoeding is € 25 per maand.",
        ),
        (
            "threshold comparative (en) — both true",
            "Employees with more than 10 years of service receive 25 days of leave.",
            "Employees with less than 10 years of service receive 20 days of leave.",
        ),
        (
            "above/below different thresholds (en) — both true",
            "The leverage ratio must stay above 2.5.",
            "The leverage ratio must stay below 3.5.",
        ),
        (
            "incl/excl same amount — true conflict, missed",
            "De vergoeding is € 25 inclusief btw.",
            "De vergoeding is € 25 exclusief btw.",
        ),
    ]
    for label, a, b in pairs:
        print(f"  conf  {label:<52} -> {detect_conflict(a, b)}")


DUTCH_ABBREVIATIONS = frozenset(
    {"bijv", "blz", "ca", "d.w.z", "evt", "excl", "i.v.m", "incl", "m.b.t", "m.u.v", "o.a", "t.o.v"}
)


def segmentation() -> None:
    import json

    from citenexus.answer import segment as S

    print("\nSEGMENTATION — conformance/cases/segmentation.json, with and without the nl entries")
    cases = json.loads((REPO / "conformance" / "cases" / "segmentation.json").read_text())
    nl = [c for c in cases if c["label"].startswith("abbrev-nl/")]
    rest = [c for c in cases if not c["label"].startswith("abbrev-nl/")]
    shipped = S.ABBREVIATIONS
    for label, table in (("without nl", shipped - DUTCH_ABBREVIATIONS), ("shipped", shipped)):
        S.ABBREVIATIONS = table
        try:
            ok_nl = sum(S.split_claims(c["text"]) == c["claims"] for c in nl)
            ok_rest = sum(S.split_claims(c["text"]) == c["claims"] for c in rest)
        finally:
            S.ABBREVIATIONS = shipped
        print(
            f"  {label:<11} dutch vectors {ok_nl}/{len(nl)}   "
            f"all other vectors {ok_rest}/{len(rest)}"
        )


def main() -> None:
    adr0009()
    adr0007()
    candidates()
    prototype_guard()
    stopwords()
    known_gaps()
    segmentation()


if __name__ == "__main__":
    main()
