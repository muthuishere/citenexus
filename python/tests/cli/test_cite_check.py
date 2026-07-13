"""Tests for `citenexus cite-check` — the retrieval-grounded cite-or-abstain gate.

Unlike `citenexus verify` (which trusts caller-supplied passages), `cite-check`
reads a real evidence *directory* itself, retrieves the supporting passage, and
returns CITED (with a source span) or ABSTAIN. This is the gate that catches a
fabricated "done" claim: the claimant supplies only the claim string, never the
evidence.
"""

from __future__ import annotations

from pathlib import Path

from citenexus.answer.verify import is_supported
from citenexus.cli.cite_check import CiteCheckReport, cite_check, main


def _dir_with(tmp_path: Path, files: dict[str, str]) -> Path:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    for name, text in files.items():
        (evidence / name).write_text(text, encoding="utf-8")
    return evidence


def test_grounded_claim_is_cited_with_source_span(tmp_path: Path) -> None:
    evidence = _dir_with(
        tmp_path,
        {
            "handbook.txt": "Unrelated preamble paragraph.\n\n"
            "The employee may not disclose confidential information.",
            "other.txt": "Nothing relevant here at all.",
        },
    )
    report: CiteCheckReport = cite_check(
        "The employee may not disclose confidential information.", evidence
    )
    assert report.verdict == "CITED"
    assert report.sources, "a CITED verdict must name at least one source span"
    src = report.sources[0]
    assert src.file == "handbook.txt"
    assert src.block == 1  # second paragraph block (0-indexed)
    assert report.uncovered_tokens == ()


def test_fabricated_claim_abstains_with_uncovered_tokens(tmp_path: Path) -> None:
    evidence = _dir_with(
        tmp_path,
        {"handbook.txt": "The employee may not disclose confidential information."},
    )
    report = cite_check("This dashboard is real and shipped to production.", evidence)
    assert report.verdict == "ABSTAIN"
    assert not report.sources
    assert "dashboard" in report.uncovered_tokens
    assert "shipped" in report.uncovered_tokens


def test_empty_directory_abstains_never_cites(tmp_path: Path) -> None:
    evidence = tmp_path / "empty"
    evidence.mkdir()
    report = cite_check("Anything at all.", evidence)
    assert report.verdict == "ABSTAIN"


def test_strict_verdict_matches_is_supported(tmp_path: Path) -> None:
    """Conformance: under the strict default, cite-check agrees with is_supported."""
    claim = "The employee may not disclose confidential information."
    passage = "The employee may not disclose confidential information."
    evidence = _dir_with(tmp_path, {"only.txt": passage})
    report = cite_check(claim, evidence)
    assert (report.verdict == "CITED") == is_supported(claim, passage)


def test_partial_support_abstains_under_strict_default(tmp_path: Path) -> None:
    evidence = _dir_with(tmp_path, {"h.txt": "The employee may not disclose information."})
    # "confidential" is absent from the passage → not full support.
    report = cite_check("The employee may not disclose confidential information.", evidence)
    assert report.verdict == "ABSTAIN"
    assert "confidential" in report.uncovered_tokens


def test_min_coverage_relaxes_toward_ratio(tmp_path: Path) -> None:
    evidence = _dir_with(tmp_path, {"h.txt": "The employee may not disclose information."})
    # content tokens of claim: employee, disclose, confidential, information (4);
    # passage covers 3/4 = 0.75.
    strict = cite_check("The employee may not disclose confidential information.", evidence)
    assert strict.verdict == "ABSTAIN"
    relaxed = cite_check(
        "The employee may not disclose confidential information.",
        evidence,
        min_coverage=0.75,
    )
    assert relaxed.verdict == "CITED"
    assert relaxed.coverage >= 0.75


def test_missing_directory_is_setup_error_exit_2(tmp_path: Path) -> None:
    code = main(["A claim.", str(tmp_path / "nope")])
    assert code == 2


def test_exit_codes_cited_zero_abstain_three(tmp_path: Path) -> None:
    evidence = _dir_with(
        tmp_path,
        {"h.txt": "The employee may not disclose confidential information."},
    )
    cited = main(["The employee may not disclose confidential information.", str(evidence)])
    assert cited == 0
    abstain = main(["This is a totally fabricated ungrounded claim.", str(evidence)])
    assert abstain == 3


def test_json_format_emits_stable_verdict_object(tmp_path: Path, capsys: object) -> None:
    import json

    evidence = _dir_with(
        tmp_path,
        {"h.txt": "The employee may not disclose confidential information."},
    )
    code = main(
        [
            "The employee may not disclose confidential information.",
            str(evidence),
            "--format",
            "json",
        ]
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert out["verdict"] == "CITED"
    assert out["sources"]
    assert out["sources"][0]["file"] == "h.txt"
    assert "coverage" in out and "min_coverage" in out
