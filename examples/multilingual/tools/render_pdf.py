"""Render the Tamil corpus-src documents to real PDFs, then MEASURE the damage.

Why this script exists at all
----------------------------
The owner asked for a real PDF in the corpus, not a .txt pretending to be one.
Producing a PDF that a RAG pipeline can actually read in an Indic script turned
out to be the single hardest part of this example, and the result is a finding
worth keeping rather than hiding:

  * PDF **rendering** of Tamil and Telugu is fine on this machine. Chrome shapes
    through HarfBuzz, the system Sangam MN fonts have full coverage, and the
    printed page is correct human-readable script. No tofu boxes.
  * PDF **text extraction** is a different question, and it is where Indic
    breaks. A PDF stores positioned glyphs; getting characters back out depends
    on the font's ``/ToUnicode`` map surviving the shaper's substitutions.
    Measured 2026-08-16 across Chrome, typst and LibreOffice x eleven macOS
    Tamil/Telugu fonts:
      - **Tamil, Chrome + "Tamil Sangam MN": every codepoint round-trips.** The
        only damage is that left-side vowel signs (U+0BC6/7/8) come back in
        VISUAL order, so ``வேண்டும்`` extracts as ``ேவண்டும்`` -- the sign is
        present, just before its consonant instead of after.
      - **Telugu: unusable in every combination tried.** Conjunct clusters
        extract as U+0000 or ``(cid:N)``: no renderer/font pair on this machine
        emits a recoverable ToUnicode for Telugu ligature glyphs.

So: Tamil ships as PDF, Telugu ships as .txt, and the number is reported rather
than assumed. ``verify()`` recomputes the Tamil fidelity figure from the actual
files so RESULTS.md can never drift away from the artifacts.

Usage (no network, no API keys):
    python examples/multilingual/tools/render_pdf.py          # render + verify
    python examples/multilingual/tools/render_pdf.py verify   # verify only
"""

from __future__ import annotations

import html
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_EXAMPLE = _HERE.parent
_SRC = _EXAMPLE / "corpus-src"
_CORPUS = _EXAMPLE / "corpus"

CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

# Chosen by measurement, not by taste -- see the module docstring.
TAMIL_FONT = "Tamil Sangam MN"

# Only these two are rendered. Telugu is deliberately absent.
PDF_DOCS = (
    "07-ta-maternity-creche-annexure",
    "08-ta-termination-appeal-annexure",
)

_PAGE_CSS = f"""
@page {{ size: A4; margin: 18mm 16mm; }}
body {{ font-family: "{TAMIL_FONT}", serif; font-size: 12pt; line-height: 1.95;
        color: #111; }}
p {{ margin: 0 0 10pt 0; white-space: pre-wrap; }}
p.head {{ font-size: 10pt; color: #444; }}
"""


def _to_html(text: str) -> str:
    blocks = [b for b in text.split("\n\n") if b.strip()]
    body = "\n".join(
        f'<p class="head">{html.escape(b)}</p>' if i == 0 else f"<p>{html.escape(b)}</p>"
        for i, b in enumerate(blocks)
    )
    return (
        '<html><head><meta charset="utf-8"><style>'
        + _PAGE_CSS
        + "</style></head><body>"
        + body
        + "</body></html>"
    )


def render() -> None:
    if not CHROME.exists():
        raise SystemExit(
            f"Headless Chrome not found at {CHROME}. It is the only renderer measured "
            "to round-trip Tamil text out of a PDF on macOS; install it or ship .txt."
        )
    for stem in PDF_DOCS:
        src = _SRC / f"{stem}.txt"
        tmp_html = _SRC / f".{stem}.html"
        out = _CORPUS / f"{stem}.pdf"
        tmp_html.write_text(_to_html(src.read_text(encoding="utf-8")), encoding="utf-8")
        subprocess.run(
            [
                str(CHROME),
                "--headless",
                "--disable-gpu",
                "--no-pdf-header-footer",
                f"--print-to-pdf={out}",
                str(tmp_html),
            ],
            check=True,
            capture_output=True,
        )
        tmp_html.unlink()
        print(f"rendered {out.relative_to(_EXAMPLE)}  ({out.stat().st_size:,} bytes)")


def _normalise(s: str) -> str:
    """Collapse whitespace; leave every other codepoint alone."""
    return " ".join(s.split())


# Tamil vowel signs that a shaper draws to the LEFT of their consonant. A PDF
# stores glyphs in the order they are painted, so these come back out BEFORE the
# consonant they belong to. U+0BCA/U+0BCB/U+0BCC are two-part signs: their left
# half is one of these and their right half is drawn after the consonant, so the
# composed codepoint is split rather than reordered.
_LEFT_SIGNS = "ெேை"
_TWO_PART = {
    ("ெ", "ா"): "ொ",  # ெ + ா  ->  ொ
    ("ே", "ா"): "ோ",  # ே + ா  ->  ோ
    ("ெ", "ௗ"): "ௌ",  # ெ + ௗ  ->  ௌ
}


def repair_tamil_visual_order(text: str) -> str:
    """Undo the PDF text layer's VISUAL ordering of Tamil left-side vowel signs.

    Deterministic, no dictionary, ~20 lines: when a left-side sign appears before
    a consonant, swap it behind the consonant, and if the character after the
    consonant is the right half of a two-part sign, recombine the pair. This
    exists to MEASURE how much of the extraction damage is mechanical (fully
    recoverable) rather than lost information -- see RESULTS.md. It is not part
    of CiteNexus; it is the evidence that a fix belongs in the PDF extractor.
    """
    out: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in _LEFT_SIGNS and i + 1 < len(text) and "க" <= text[i + 1] <= "ஹ":
            cons = text[i + 1]
            j = i + 2
            # Carry the consonant's own virama/sign cluster across the swap.
            tail = ""
            if j < len(text) and text[j] in "்ாௗ":
                combined = _TWO_PART.get((ch, text[j]))
                if combined is not None:
                    out.append(cons + combined)
                    i = j + 1
                    continue
                tail = text[j]
                j += 1
            out.append(cons + ch + tail)
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


# The exact tokens each PDF document must still carry after extraction -- these
# are the ones golden.csv questions turn on.
_TOKENS: dict[str, tuple[str, ...]] = {
    "07-ta-maternity-creche-annexure": ("5.4", "26", "5.6", "INR 6,000", "6", "5.8", "10"),
    "08-ta-termination-appeal-annexure": ("8.3", "21", "8.4", "45", "8.1", "7"),
}


def verify() -> int:
    """Recompute the Tamil PDF fidelity numbers reported in RESULTS.md."""
    import pdfplumber  # a CiteNexus dependency; offline

    failures = 0
    for stem in PDF_DOCS:
        pdf_path = _CORPUS / f"{stem}.pdf"
        src_text = _normalise((_SRC / f"{stem}.txt").read_text(encoding="utf-8"))
        with pdfplumber.open(pdf_path) as pdf:
            got = _normalise(" ".join(p.extract_text() or "" for p in pdf.pages))
        repaired = repair_tamil_visual_order(got)

        # 1. No lost glyphs. This is the check Telugu fails outright.
        lost = got.count("\x00") + got.count("(cid:")
        # 2. Exact-token survival: the tokens a golden question turns on.
        missing = [t for t in _TOKENS[stem] if t not in got]
        # 3. Reordering damage, measured: how many source words appear verbatim,
        #    raw out of the PDF and after the deterministic repair above.
        src_words = [w for w in src_text.split() if any(ord(c) > 0x0B80 for c in w)]
        raw = sum(1 for w in src_words if w in got)
        fixed = sum(1 for w in src_words if w in repaired)
        n = len(src_words) or 1

        ok = lost == 0 and not missing and fixed / n > 0.95
        failures += 0 if ok else 1
        print(
            f"{stem}  {'OK' if ok else 'FAIL'}\n"
            f"   lost glyphs (NUL/cid)      : {lost}   (must be 0 -- Telugu fails here)\n"
            f"   exact tokens missing       : {missing or 'none'}\n"
            f"   Tamil words verbatim, raw  : {raw}/{n} = {raw / n:.1%}\n"
            f"   Tamil words verbatim, after"
            f" reorder repair               : {fixed}/{n} = {fixed / n:.1%}"
        )
    return failures


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "verify":
        raise SystemExit(verify())
    render()
    raise SystemExit(verify())


if __name__ == "__main__":
    main()
