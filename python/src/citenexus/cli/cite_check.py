"""`citenexus cite-check` — retrieval-grounded cite-or-abstain gate over a dir.

Where `citenexus verify` trusts caller-supplied passages, `cite-check` reads a
real *directory* of evidence files itself, extracts their passages, retrieves
the best-matching one for a free-text claim, and returns **CITED** (with a
source span: `file:block` + page) or **ABSTAIN**. The caller supplies only the
claim and the directory — never the passage — so an ungrounded "done" claim
cannot fabricate its own support.

Deterministic and offline: no LLM call, no S3, no running `CiteNexus` instance.
The full-support verdict reuses `citenexus.answer.verify.is_supported` — the
exact function `AnswerFlow.ask()` uses — so it can never drift from the
library's faithfulness gate. Threshold rationale (AIS full-support proxy,
RAGAS-style relaxation, fail-safe abstention) is in the OpenSpec change
`2026-07-13-cite-check-cli` and the report.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from citenexus.answer.verify import content_tokens, is_supported
from citenexus.extract.dispatch import extract

_EXCERPT_CHARS = 240


class CiteCheckError(Exception):
    """A setup error (missing/unreadable directory, bad arguments) — exit 2."""


class SourceSpan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    file: str
    block: int
    page: int | None
    passage: str
    coverage: float


class CiteCheckReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    citenexus_cite_check_version: str = "1"
    verdict: Literal["CITED", "ABSTAIN"]
    claim: str
    coverage: float
    min_coverage: float
    sources: tuple[SourceSpan, ...]
    uncovered_tokens: tuple[str, ...]


class _Passage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    file: str
    block: int
    page: int | None
    text: str


def _iter_passages(evidence_dir: Path) -> list[_Passage]:
    """Extract every text block under ``evidence_dir`` as a candidate passage.

    Files the extractors cannot read (unsupported binary, decode error) are
    skipped, not fatal — but a directory that yields no passage abstains
    (fail-closed), it never cites.
    """
    passages: list[_Passage] = []
    for path in sorted(p for p in evidence_dir.rglob("*") if p.is_file()):
        rel = path.relative_to(evidence_dir).as_posix()
        try:
            doc = extract(path, document_id=rel)
        except (OSError, ValueError, TypeError):
            continue
        for block in doc.blocks:
            if block.text.strip():
                passages.append(
                    _Passage(file=rel, block=block.order, page=block.page, text=block.text)
                )
    return passages


def _coverage(claim_content: frozenset[str], passage_text: str) -> float:
    """Fraction of the claim's content tokens present in the passage (RAGAS-style)."""
    if not claim_content:
        return 0.0
    covered = claim_content & content_tokens(passage_text)
    return len(covered) / len(claim_content)


def cite_check(claim: str, evidence_dir: Path, *, min_coverage: float = 1.0) -> CiteCheckReport:
    """Decide CITED/ABSTAIN for ``claim`` against the files under ``evidence_dir``.

    Strict default (``min_coverage == 1.0``): CITE only when a single passage
    fully supports the claim, per ``is_supported`` (an AIS full-support proxy).
    A lower ``min_coverage`` relaxes to a content-token coverage ratio — it can
    only turn ABSTAIN into CITED, never the reverse.
    """
    claim_content = frozenset(content_tokens(claim))
    passages = _iter_passages(evidence_dir)
    strict = min_coverage >= 1.0

    best: _Passage | None = None
    best_coverage = 0.0
    supporter: _Passage | None = None
    supporter_coverage = 0.0

    for passage in passages:
        coverage = _coverage(claim_content, passage.text)
        if best is None or coverage > best_coverage:
            best, best_coverage = passage, coverage
        supported = is_supported(claim, passage.text) if strict else coverage >= min_coverage
        if supported and supporter is None:
            # First supporting passage wins the citation (files iterate in sorted order).
            supporter, supporter_coverage = passage, coverage

    if supporter is not None:
        span = SourceSpan(
            file=supporter.file,
            block=supporter.block,
            page=supporter.page,
            passage=supporter.text[:_EXCERPT_CHARS],
            coverage=supporter_coverage,
        )
        return CiteCheckReport(
            verdict="CITED",
            claim=claim,
            coverage=supporter_coverage,
            min_coverage=min_coverage,
            sources=(span,),
            uncovered_tokens=(),
        )

    covered = content_tokens(best.text) if best is not None else set()
    uncovered = tuple(sorted(claim_content - covered))
    return CiteCheckReport(
        verdict="ABSTAIN",
        claim=claim,
        coverage=best_coverage,
        min_coverage=min_coverage,
        sources=(),
        uncovered_tokens=uncovered,
    )


def _format_text(report: CiteCheckReport) -> str:
    if report.verdict == "CITED":
        lines = [f"CITED (coverage {report.coverage:.2f}) — {report.claim}"]
        for src in report.sources:
            page = f" p.{src.page}" if src.page is not None else ""
            lines.append(f"  ↳ {src.file}:block {src.block}{page}")
        return "\n".join(lines)
    tokens = ", ".join(report.uncovered_tokens) or "(no content tokens)"
    return (
        f"ABSTAIN (best coverage {report.coverage:.2f} < {report.min_coverage:.2f}) — "
        f"{report.claim}\n  uncovered: {{{tokens}}}"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="citenexus cite-check")
    parser.add_argument("claim", help="the free-text claim to ground")
    parser.add_argument("evidence_dir", help="a directory of evidence files")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=1.0,
        help="0.0-1.0; below 1.0 relaxes AIS full-support to a coverage ratio",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not 0.0 <= args.min_coverage <= 1.0:
        print("--min-coverage must be between 0.0 and 1.0", file=sys.stderr)
        return 2
    evidence_dir = Path(args.evidence_dir)
    if not evidence_dir.is_dir():
        print(f"{evidence_dir}: not a directory", file=sys.stderr)
        return 2

    report = cite_check(args.claim, evidence_dir, min_coverage=args.min_coverage)
    if args.format == "json":
        print(report.model_dump_json(indent=2))
    else:
        print(_format_text(report))
    return 0 if report.verdict == "CITED" else 3
