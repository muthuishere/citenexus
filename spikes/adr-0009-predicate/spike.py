"""ADR-0009 validation spike — strengthened containment predicate + claim
segmentation tier decision.

Throwaway prototype. Nothing under python/src, golang/, js/ or rust/ is
touched; this only imports them.

Run:  cd python && uv run python ../spikes/adr-0009-predicate/spike.py
Exit: 0 if the predicate rejects all 9 attacks AND the false-rejection rate on
      the legitimate control set is 0; 1 otherwise.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "library-stress"))

from citenexus.answer.verify import is_supported  # noqa: E402
from citenexus.tokenize import tokenize  # noqa: E402
from predicate import (  # noqa: E402
    DEFAULT_MAX_SINGLE_GAP,
    DEFAULT_MAX_TOTAL_GAP,
    is_supported_contiguous,
    is_supported_ordered_only,
    is_supported_v0,
    is_supported_v2,
    split_guarded,
    split_shipped,
)
from stress import GATE_CASES  # noqa: E402

REPO = Path(__file__).resolve().parents[2]

# ─────────────────────────────────────────────────────────────────────────────
# The control set: 30 answers that ARE legitimately supported by their passage.
# These are the measurement that matters — a predicate that rejects everything
# passes the attack suite trivially and is worthless.
#
# kind:
#   verbatim   — the whole passage, unchanged
#   subspan    — a contiguous run of the passage (the common extractive answer)
#   punct      — a sub-span with leading/trailing whitespace + punctuation noise
#   compress   — a sub-span with interior words dropped (a real model behaviour)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TrueCase:
    domain: str
    kind: str
    passage: str
    answer: str


LEGAL_1 = "The tenant shall indemnify the landlord for damage to the property."
LEGAL_2 = "The employee shall not disclose confidential information to third parties."
LEGAL_3 = "Notice of termination must be given in writing at least thirty days in advance."
FIN_1 = "The borrower pays the lender a fee of 400 basis points on the outstanding balance."
FIN_2 = "Region A reported 40 million in revenue and region B reported 12 million."
FIN_3 = "The dividend for the period was 12 cents per share, payable on 30 June."
MED_1 = "Ibuprofen increases the effect of warfarin in adult patients."
MED_2 = "This medication is not approved for patients under twelve years."
MED_3 = "The recommended dose for adults is 500 milligrams daily, taken with food."
OPS_1 = "The reactor must not be restarted without a signed safety review."
OPS_2 = "The maintenance window opens at 02:00 UTC on Sunday and closes at 06:00 UTC."
OPS_3 = "Backups are retained for ninety days in the primary region only."
PHY_1 = "The sample melts at 240 kelvin and boils at 610 kelvin."
PHY_2 = "Pressure in chamber one is greater than pressure in chamber two."
PHY_3 = "The detector threshold is calibrated to 4.5 gigaelectronvolts."

CONTROL: list[TrueCase] = [
    # verbatim — what FakeLLM and every extractive generator produces
    TrueCase("legal", "verbatim", LEGAL_1, LEGAL_1),
    TrueCase("legal", "verbatim", LEGAL_2, LEGAL_2),
    TrueCase("finance", "verbatim", FIN_1, FIN_1),
    TrueCase("medical", "verbatim", MED_2, MED_2),
    TrueCase("operations", "verbatim", OPS_1, OPS_1),
    TrueCase("physics", "verbatim", PHY_1, PHY_1),
    # subspan — the answer is a contiguous quote out of the passage
    TrueCase("legal", "subspan", LEGAL_1, "The tenant shall indemnify the landlord"),
    TrueCase("legal", "subspan", LEGAL_3, "at least thirty days in advance"),
    TrueCase("finance", "subspan", FIN_1, "a fee of 400 basis points"),
    TrueCase("finance", "subspan", FIN_3, "12 cents per share"),
    TrueCase("medical", "subspan", MED_3, "500 milligrams daily"),
    TrueCase("medical", "subspan", MED_1, "increases the effect of warfarin"),
    TrueCase("operations", "subspan", OPS_2, "02:00 UTC on Sunday"),
    TrueCase("operations", "subspan", OPS_3, "retained for ninety days"),
    TrueCase("physics", "subspan", PHY_3, "4.5 gigaelectronvolts"),
    TrueCase("physics", "subspan", PHY_2, "Pressure in chamber one"),
    # punct — same span, whitespace / punctuation / casing noise
    TrueCase("legal", "punct", LEGAL_3, "  in writing  "),
    TrueCase("legal", "punct", LEGAL_2, "confidential information."),
    TrueCase("finance", "punct", FIN_2, "Region A reported 40 million."),
    TrueCase("finance", "punct", FIN_1, '"400 basis points"'),
    TrueCase("medical", "punct", MED_3, "500 milligrams daily!"),
    TrueCase("medical", "punct", MED_1, "  ADULT PATIENTS  "),
    TrueCase("operations", "punct", OPS_2, "(06:00 UTC)"),
    TrueCase("physics", "punct", PHY_1, "240 kelvin,"),
    # compress — interior words dropped, meaning preserved (real model output)
    TrueCase("legal", "compress", LEGAL_1, "The tenant shall indemnify the landlord for damage."),
    TrueCase("legal", "compress", LEGAL_2, "The employee shall not disclose information."),
    TrueCase("finance", "compress", FIN_1, "The borrower pays the lender 400 basis points."),
    TrueCase("medical", "compress", MED_3, "The recommended dose is 500 milligrams daily."),
    TrueCase("operations", "compress", OPS_1, "The reactor must not be restarted without a review."),
    TrueCase("physics", "compress", PHY_1, "The sample melts at 240 kelvin."),
]

PREDICATES = {
    "v0 set-containment (shipped)": is_supported_v0,
    "B contiguous-only": is_supported_contiguous,
    "C ordered-gapped, no polarity": is_supported_ordered_only,
    "v2 ADR (ordered-gapped + polarity)": is_supported_v2,
}


def part1() -> tuple[bool, float]:
    print("\n" + "=" * 78)
    print("PART 1 — the strengthened containment predicate")
    print("=" * 78)

    # sanity: the shipped predicate and our v0 replica must agree everywhere
    for c in GATE_CASES:
        assert is_supported(c.answer, c.passage) == is_supported_v0(c.answer, c.passage)

    print("\n--- 1a. the 9 adversarial fixtures (all FALSE; all must be rejected) ---\n")
    header = f"  {'domain/attack':<32}" + "".join(f"{k.split()[0]:>8}" for k in PREDICATES)
    print(header)
    attack_accepts = dict.fromkeys(PREDICATES, 0)
    for c in GATE_CASES:
        row = f"  {c.domain + '/' + c.attack:<32}"
        for name, fn in PREDICATES.items():
            ok = fn(c.answer, c.passage)
            attack_accepts[name] += int(ok)
            row += f"{'ACCEPT' if ok else 'reject':>8}"
        print(row)
    print()
    for name in PREDICATES:
        print(f"    {name:<38} accepted {attack_accepts[name]}/9 false answers")

    print(f"\n--- 1b. control set: {len(CONTROL)} TRUE answers (false-rejection rate) ---\n")
    frr: dict[str, list[TrueCase]] = {k: [] for k in PREDICATES}
    for c in CONTROL:
        for name, fn in PREDICATES.items():
            if not fn(c.answer, c.passage):
                frr[name].append(c)
    for name in PREDICATES:
        bad = frr[name]
        rate = 100.0 * len(bad) / len(CONTROL)
        print(f"    {name:<38} FRR {len(bad):>2}/{len(CONTROL)} = {rate:5.1f}%")
        for c in bad:
            print(f"        - [{c.domain}/{c.kind}] {c.answer!r}")

    print("\n--- 1c. per-kind breakdown for the ADR predicate ---\n")
    kinds = sorted({c.kind for c in CONTROL})
    for k in kinds:
        rows = [c for c in CONTROL if c.kind == k]
        bad = [c for c in rows if not is_supported_v2(c.answer, c.passage)]
        print(f"    {k:<10} {len(rows) - len(bad)}/{len(rows)} accepted")

    print("\n--- 1d. gap-budget sweep (single, total) for the ADR predicate ---\n")
    print(f"    {'budget':<14}{'attacks accepted':>18}{'control rejected':>18}")
    for single, total in [(0, 0), (1, 2), (2, 4), (3, 6), (4, 8), (6, 12), (10, 30)]:
        a = sum(
            is_supported_v2(c.answer, c.passage, max_single_gap=single, max_total_gap=total)
            for c in GATE_CASES
        )
        r = sum(
            not is_supported_v2(c.answer, c.passage, max_single_gap=single, max_total_gap=total)
            for c in CONTROL
        )
        mark = "  <- default" if (single, total) == (DEFAULT_MAX_SINGLE_GAP, DEFAULT_MAX_TOTAL_GAP) else ""
        print(f"    ({single},{total})".ljust(18) + f"{a:>14}/9{r:>15}/{len(CONTROL)}{mark}")

    attacks_ok = attack_accepts["v2 ADR (ordered-gapped + polarity)"] == 0
    rate = 100.0 * len(frr["v2 ADR (ordered-gapped + polarity)"]) / len(CONTROL)
    return attacks_ok, rate


def part1e_shadow_pytest() -> None:
    print("\n--- 1e. shadow-run against the real test suite (676 tests) ---\n")
    out = REPO / "spikes" / "adr-0009-predicate" / "shadow.json"
    if out.exists():
        out.unlink()
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent), SHADOW_OUT=str(out))
    proc = subprocess.run(
        ["uv", "run", "pytest", "-q", "-p", "shadow_gate"],
        cwd=REPO / "python",
        env=env,
        capture_output=True,
        text=True,
    )
    print("    pytest:", proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "no output")
    if not out.exists():
        print("    (no shadow data captured)")
        return
    data = json.loads(out.read_text())
    total = len(data)
    disagree = [d for d in data if d["v0"] and not d["v2"]]
    print(f"    gate calls observed        : {total}")
    print(f"    v0 accepted, v2 would REJECT: {len(disagree)}")
    seen = set()
    for d in disagree:
        key = (d["claim"][:60], d["passage"][:60])
        if key in seen:
            continue
        seen.add(key)
        print(f"        claim  : {d['claim'][:90]!r}")
        print(f"        passage: {d['passage'][:90]!r}")
    if not disagree:
        print("    => swapping v2 in would break 0 existing gate decisions.")


# ─────────────────────────────────────────────────────────────────────────────
# PART 2 — claim segmentation and the tier question.
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SegCase:
    lang: str
    text: str
    expected: int
    note: str = ""


SEG_CASES = [
    # --- English ---
    SegCase("en", "The tenant must pay rent. The landlord must repair the roof.", 2),
    SegCase("en", "Is the clause valid? It is. Nothing else applies.", 3),
    SegCase("en", "Art. 5 applies to the tenant.", 1, "legal-citation abbreviation"),
    SegCase("en", "Dr. Smith signed the review.", 1, "honorific"),
    SegCase("en", "Use a solvent, e.g. acetone, before assembly.", 1, "e.g."),
    SegCase("en", "The dose is 500.00 milligrams daily.", 1, "decimal"),
    SegCase("en", "The steps are (a) foo; (b) bar; (c) baz.", 1, "enumeration"),
    SegCase("en", "Section 3.2.1 governs the notice period.", 1, "dotted numbering"),
    # --- Dutch (the brief's target language) ---
    SegCase("nl", "De huurder betaalt de huur. De verhuurder herstelt het dak.", 2),
    SegCase("nl", "Dhr. Jansen heeft getekend.", 1, "honorific"),
    SegCase("nl", "De dosis is 500,00 milligram per dag.", 1, "comma decimal — no dot"),
    SegCase("nl", "Art. 7:658 BW is van toepassing.", 1, "statute citation"),
    SegCase("nl", "Is de clausule geldig? Ja. Niets anders geldt.", 3),
    # --- German ---
    SegCase("de", "Der Mieter zahlt die Miete. Der Vermieter repariert das Dach.", 2),
    SegCase(
        "de",
        "Der Vermieter, der das Dach repariert, haftet nicht, wenn der Mieter "
        "die Anzeige unterlaesst.",
        1,
        "compound sentence, one terminator",
    ),
    SegCase("de", "Vgl. Abs. 2 Ziff. 3.", 1, "stacked abbreviations"),
    SegCase("de", "Die Dosis betraegt 4.5 Milligramm.", 1, "decimal"),
    # --- Tamil ---
    SegCase("ta", "குத்தகைதாரர் வாடகை செலுத்த வேண்டும். உரிமையாளர் கூரையை சரிசெய்ய வேண்டும்.", 2),
    SegCase("ta", "இது சரியா? ஆம்.", 2),
    # --- Japanese (no spaces, ideographic full stop) ---
    SegCase("ja", "借主は家賃を支払う。貸主は屋根を修理する。", 2, "no spaces, U+3002"),
    SegCase("ja", "これは有効ですか？はい。", 2, "full-width question mark"),
    SegCase("ja", "投与量は500.00ミリグラムです。", 1, "decimal inside CJK"),
    # --- Arabic (RTL) ---
    SegCase("ar", "يجب على المستأجر دفع الإيجار. يجب على المالك إصلاح السقف.", 2),
    SegCase("ar", "هل البند صالح؟ نعم.", 2, "Arabic question mark U+061F"),
    # --- deliberately-hard cases held back from the tuning set ---
    SegCase("en", "The U.S. Army issued the order.", 1, "HELD OUT: dotted acronym"),
    SegCase("en", "He arrived at 5 p.m. She left immediately.", 2,
            "HELD OUT: abbreviation at a real sentence end"),
    SegCase("th", "ผู้เช่าต้องจ่ายค่าเช่า ผู้ให้เช่าต้องซ่อมหลังคา", 2,
            "HELD OUT: Thai has no sentence terminator at all"),
]

SPLITTERS = {
    "naive (shipped agentic.py:53)": split_shipped,
    "guarded (tier1 code + tier2 table)": split_guarded,
}


def part2() -> str:
    print("\n" + "=" * 78)
    print("PART 2 — claim decomposition and the ADR-0010 tier decision")
    print("=" * 78)

    results: dict[str, dict[str, list[int]]] = {
        name: {} for name in SPLITTERS
    }  # name -> lang -> [ok, total]

    for name, fn in SPLITTERS.items():
        print(f"\n--- {name} ---\n")
        for c in SEG_CASES:
            got = fn(c.text)
            ok = len(got) == c.expected
            results[name].setdefault(c.lang, [0, 0])
            results[name][c.lang][1] += 1
            results[name][c.lang][0] += int(ok)
            if not ok:
                note = f" ({c.note})" if c.note else ""
                print(f"    FAIL [{c.lang}] expected {c.expected}, got {len(got)}{note}")
                print(f"         {c.text[:70]}")
                print(f"         -> {[s[:34] for s in got]}")
        print()
        for lang in sorted(results[name]):
            ok, tot = results[name][lang]
            print(f"    {lang}: {tot - ok}/{tot} failed ({100.0 * (tot - ok) / tot:5.1f}%)")
        tot_ok = sum(v[0] for v in results[name].values())
        tot_all = sum(v[1] for v in results[name].values())
        print(f"    OVERALL failure rate: {tot_all - tot_ok}/{tot_all} "
              f"= {100.0 * (tot_all - tot_ok) / tot_all:.1f}%")

    # ── the finding that dominates the tier question ──────────────────────────
    print("\n--- 2c. what the PINNED TOKENIZER does to these languages ---\n")
    print("    citenexus.tokenize is re.compile(r'[a-z0-9]+') over text.lower().")
    print("    Segmentation is downstream of it, so measure it first.\n")
    dead = []
    for c in SEG_CASES:
        toks = tokenize(c.text)
        if not toks:
            dead.append(c.lang)
        print(f"    [{c.lang}] {len(toks):>3} tokens  <- {c.text[:44]}")
    dead_langs = sorted(set(dead))
    print(f"\n    scripts that tokenize to ZERO tokens: {dead_langs or 'none'}")
    print("    For those, is_supported() short-circuits on `bool(answer_tokens)`")
    print("    and returns False => EVERY answer in that script abstains, today,")
    print("    before any predicate or segmenter runs.")

    guarded_fail = sum(
        1 for c in SEG_CASES if len(split_guarded(c.text)) != c.expected
    )
    return "tier1" if guarded_fail == 0 else "tier1-with-residue"


def main() -> int:
    print("ADR-0009 predicate + segmentation validation spike")
    print("throwaway; imports the library, modifies nothing")

    attacks_ok, frr = part1()
    part1e_shadow_pytest()
    verdict = part2()

    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    print(f"  9 adversarial fixtures rejected by is_supported_v2 : {attacks_ok}")
    print(f"  false-rejection rate on {len(CONTROL)} legitimate answers  : {frr:.1f}%")
    print(f"  segmentation tier verdict                          : {verdict}")
    print()
    return 0 if (attacks_ok and frr == 0.0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
