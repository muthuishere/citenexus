"""Tests for `citenexus verify` — the standalone faithfulness-gate CLI.

Reuses conformance/cases/faithful.json so the CLI is proven against the exact
same fixtures Go/TS/Rust conformance already tests against, and asserts the
CLI never drifts from `citenexus.answer.verify.is_supported` — the same
function `AnswerFlow.ask()` calls internally.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from citenexus.answer.verify import is_supported
from citenexus.cli.verify import VerifyInputError, load_input, main, verify

_FIXTURES_PATH = Path(__file__).resolve().parents[3] / "conformance" / "cases" / "faithful.json"
FAITHFUL_FIXTURES = json.loads(_FIXTURES_PATH.read_text(encoding="utf-8"))


def _write(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "input.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_all_supported_claims_pass(tmp_path: Path) -> None:
    payload = {
        "claims": [
            {
                "id": "c1",
                "text": "The employee may not disclose confidential information.",
                "citations": [
                    {
                        "id": "s1",
                        "passage": "The employee may not disclose confidential information.",
                    }
                ],
            },
        ]
    }
    report = verify(load_input(_write(tmp_path, payload)))
    assert report.overall == "pass"
    assert report.claims[0].supported is True
    assert report.claims[0].matched_citation_id == "s1"
    assert report.claims[0].missing_tokens == ()


def test_ungrounded_claim_reports_missing_tokens(tmp_path: Path) -> None:
    payload = {
        "claims": [
            {
                "id": "c1",
                "text": "The employee may freely disclose information.",
                "citations": [
                    {
                        "id": "s1",
                        "passage": "The employee may not disclose confidential information.",
                    }
                ],
            },
        ]
    }
    report = verify(load_input(_write(tmp_path, payload)))
    assert report.overall == "fail"
    claim = report.claims[0]
    assert claim.supported is False
    assert "freely" in claim.missing_tokens


def test_claim_supported_by_second_citation_not_first(tmp_path: Path) -> None:
    payload = {
        "claims": [
            {
                "id": "c1",
                "text": "notice period is 30 days",
                "citations": [
                    {"id": "wrong", "passage": "the notice period is 60 days per contract"},
                    {"id": "right", "passage": "the notice period is 30 days per contract"},
                ],
            }
        ]
    }
    report = verify(load_input(_write(tmp_path, payload)))
    assert report.overall == "pass"
    assert report.claims[0].matched_citation_id == "right"


def test_multiple_claims_are_verified_independently(tmp_path: Path) -> None:
    payload = {
        "claims": [
            {
                "id": "good",
                "text": "notice period is 30 days",
                "citations": [{"id": "s1", "passage": "the notice period is 30 days per contract"}],
            },
            {
                "id": "bad",
                "text": "notice period is 60 days",
                "citations": [{"id": "s1", "passage": "the notice period is 30 days per contract"}],
            },
        ]
    }
    report = verify(load_input(_write(tmp_path, payload)))
    assert report.overall == "fail"
    verdicts = {c.id: c.supported for c in report.claims}
    assert verdicts == {"good": True, "bad": False}


def test_relevance_overlap_uses_question_when_supplied(tmp_path: Path) -> None:
    payload = {
        "question": "Can the employee disclose this?",
        "claims": [
            {
                "id": "c1",
                "text": "The employee may not disclose confidential information.",
                "citations": [
                    {"id": "s1", "passage": "The employee may not disclose confidential data."}
                ],
            },
        ],
    }
    report = verify(load_input(_write(tmp_path, payload)))
    assert report.claims[0].relevance_overlap is True


def test_relevance_overlap_is_none_without_a_question(tmp_path: Path) -> None:
    payload = {
        "claims": [
            {"id": "c1", "text": "x", "citations": [{"id": "s1", "passage": "x"}]},
        ]
    }
    report = verify(load_input(_write(tmp_path, payload)))
    assert report.claims[0].relevance_overlap is None


def test_citation_without_checksum_still_verifies_on_containment_alone(tmp_path: Path) -> None:
    payload = {
        "claims": [
            {
                "id": "c1",
                "text": "notice period is 30 days",
                "citations": [{"id": "s1", "passage": "the notice period is 30 days per contract"}],
            },
        ]
    }
    report = verify(load_input(_write(tmp_path, payload)))
    assert report.claims[0].supported is True


@pytest.mark.parametrize("case", FAITHFUL_FIXTURES["supported"])
def test_cli_verdict_matches_the_internal_answer_flow_gate(
    case: dict[str, Any], tmp_path: Path
) -> None:
    """The CLI must never drift from AnswerFlow.ask()'s faithfulness gate."""
    payload = {
        "claims": [
            {
                "id": "c1",
                "text": case["answer"],
                "citations": [{"id": "s1", "passage": case["passage"]}],
            },
        ]
    }
    report = verify(load_input(_write(tmp_path, payload)))
    assert (
        report.claims[0].supported
        == is_supported(case["answer"], case["passage"])
        == case["supported"]
    )


def test_malformed_input_raises_a_distinct_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not json at all", encoding="utf-8")
    with pytest.raises(VerifyInputError):
        load_input(bad)


def test_missing_claims_field_raises_a_distinct_error(tmp_path: Path) -> None:
    path = _write(tmp_path, {"question": "no claims here"})
    with pytest.raises(VerifyInputError):
        load_input(path)


class TestMainExitCodes:
    def test_exit_0_when_all_claims_supported(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = {
            "claims": [
                {
                    "id": "c1",
                    "text": "notice period is 30 days",
                    "citations": [
                        {"id": "s1", "passage": "the notice period is 30 days per contract"}
                    ],
                },
            ]
        }
        code = main([str(_write(tmp_path, payload))])
        assert code == 0

    def test_exit_1_when_a_claim_is_unsupported(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = {
            "claims": [
                {
                    "id": "c1",
                    "text": "notice period is 60 days",
                    "citations": [
                        {"id": "s1", "passage": "the notice period is 30 days per contract"}
                    ],
                },
            ]
        }
        code = main([str(_write(tmp_path, payload))])
        assert code == 1

    def test_exit_2_on_malformed_input(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json", encoding="utf-8")
        code = main([str(bad)])
        assert code == 2

    def test_json_format_emits_a_parseable_report(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = {
            "claims": [
                {
                    "id": "c1",
                    "text": "notice period is 30 days",
                    "citations": [
                        {"id": "s1", "passage": "the notice period is 30 days per contract"}
                    ],
                },
            ]
        }
        main([str(_write(tmp_path, payload)), "--format", "json"])
        out = json.loads(capsys.readouterr().out)
        assert out["overall"] == "pass"
        assert out["claims"][0]["id"] == "c1"

    def test_text_format_prints_a_human_summary(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = {
            "claims": [
                {
                    "id": "c1",
                    "text": "notice period is 30 days",
                    "citations": [
                        {"id": "s1", "passage": "the notice period is 30 days per contract"}
                    ],
                },
            ]
        }
        main([str(_write(tmp_path, payload))])
        captured = capsys.readouterr().out
        assert "PASS" in captured
        assert "c1" in captured
