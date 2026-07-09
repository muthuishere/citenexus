"""`citenexus verify` — the faithfulness gate, standalone.

Proves each claim's tokens are contained in one of its cited passages,
deterministically: no LLM call, no S3, no running `CiteNexus` instance. Calls
`citenexus.answer.verify.is_supported`/`has_relevance_overlap` directly — the
exact functions `AnswerFlow.ask()` uses — so this can never drift from the
internal faithfulness gate.

Scope, precisely: this proves `tokens(claim) ⊆ tokens(passage)` for whatever
passage text the caller supplies. It does NOT prove the passage was extracted
from a named source document — an optional `source_checksum` on a citation is
carried through the report for the caller's own provenance checks, but never
changes the pass/fail verdict.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from citenexus.answer.verify import has_relevance_overlap, is_supported
from citenexus.tokenize import tokenize

REPORT_VERSION = "1"


class VerifyInputError(Exception):
    """The input file is missing, not valid JSON, or fails the input schema."""


class VerifyCitation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    passage: str
    # Optional, opt-in: never affects the pass/fail verdict (see module docstring).
    source_checksum: str | None = None


class VerifyClaim(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    text: str
    citations: tuple[VerifyCitation, ...]


class VerifyInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    question: str | None = None
    claims: tuple[VerifyClaim, ...]


class ClaimVerdict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    supported: bool
    matched_citation_id: str | None
    missing_tokens: tuple[str, ...]
    relevance_overlap: bool | None


class VerifyReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    citenexus_verify_version: str = REPORT_VERSION
    overall: Literal["pass", "fail"]
    claims: tuple[ClaimVerdict, ...]


def load_input(path: Path) -> VerifyInput:
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise VerifyInputError(f"{path}: not valid JSON — {exc}") from exc
    try:
        return VerifyInput.model_validate(data)
    except ValidationError as exc:
        raise VerifyInputError(f"{path}: does not match the verify-input schema — {exc}") from exc


def _verify_claim(claim: VerifyClaim, question: str | None) -> ClaimVerdict:
    claim_tokens = set(tokenize(claim.text))
    best_citation: VerifyCitation | None = None
    best_missing: set[str] = claim_tokens
    matched: VerifyCitation | None = None

    for citation in claim.citations:
        if is_supported(claim.text, citation.passage):
            matched = citation
            best_citation = citation
            best_missing = set()
            break
        missing = claim_tokens - set(tokenize(citation.passage))
        if best_citation is None or len(missing) < len(best_missing):
            best_citation = citation
            best_missing = missing

    relevance_overlap = (
        has_relevance_overlap(question, best_citation.passage)
        if question is not None and best_citation is not None
        else None
    )
    return ClaimVerdict(
        id=claim.id,
        supported=matched is not None,
        matched_citation_id=matched.id if matched is not None else None,
        missing_tokens=tuple(sorted(best_missing)),
        relevance_overlap=relevance_overlap,
    )


def verify(verify_input: VerifyInput) -> VerifyReport:
    verdicts = tuple(_verify_claim(claim, verify_input.question) for claim in verify_input.claims)
    overall: Literal["pass", "fail"] = "pass" if all(v.supported for v in verdicts) else "fail"
    return VerifyReport(overall=overall, claims=verdicts)


def _format_text(report: VerifyReport) -> str:
    lines = []
    for claim in report.claims:
        status = "PASS" if claim.supported else "FAIL"
        line = f"[{status}] {claim.id}"
        if not claim.supported and claim.missing_tokens:
            line += f" — missing tokens: {{{', '.join(claim.missing_tokens)}}}"
        lines.append(line)
    supported_count = sum(1 for c in report.claims if c.supported)
    summary = f"{supported_count}/{len(report.claims)} claims grounded — {report.overall.upper()}"
    lines.append(summary)
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="citenexus verify")
    parser.add_argument("input", help="path to a verify-input JSON file")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--question", help="override/supply the relevance-gate question")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        verify_input = load_input(Path(args.input))
    except VerifyInputError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.question is not None:
        verify_input = verify_input.model_copy(update={"question": args.question})

    report = verify(verify_input)
    if args.format == "json":
        print(report.model_dump_json(indent=2))
    else:
        print(_format_text(report))
    return 0 if report.overall == "pass" else 1
