"""CSV evaluation front door for v0.1.0."""

from __future__ import annotations

import csv
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from trustrag.answer.result import Decision
from trustrag.answer.verify import content_tokens

if TYPE_CHECKING:
    from trustrag.answer.result import Result


class EvaluationReport(BaseModel):
    """Aggregate metrics from `evaluate(csv)`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total: int
    answered: int
    refused: int
    grounded: int
    cited: int
    expected_supported: int

    @property
    def groundedness_rate(self) -> float:
        return self.grounded / self.answered if self.answered else 0.0

    @property
    def citation_rate(self) -> float:
        return self.cited / self.answered if self.answered else 0.0

    @property
    def expected_support_rate(self) -> float:
        return self.expected_supported / self.total if self.total else 0.0


class Evaluator:
    """Run a golden CSV through a client-like `ask` callable."""

    def __init__(self, ask: Callable[[str], Result]) -> None:
        self._ask = ask

    def evaluate(self, csv_path: str | Path) -> EvaluationReport:
        with Path(csv_path).open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        results = [self._ask_row(row) for row in rows]
        answered = [r for r in results if r.evidence.decision is Decision.answered]
        return EvaluationReport(
            total=len(results),
            answered=len(answered),
            refused=sum(1 for r in results if r.evidence.decision is Decision.refused),
            grounded=sum(1 for r in answered if r.evidence.all_claims_verified),
            cited=sum(1 for r in answered if r.sources),
            expected_supported=sum(
                1 for row, result in zip(rows, results, strict=True)
                if _expected_supported(row.get("expected", ""), result)
            ),
        )

    def _ask_row(self, row: dict[str, str]) -> Result:
        question = row.get("question") or row.get("query")
        if not question:
            raise ValueError("evaluation CSV must contain a question or query column")
        result: Result = self._ask(question)
        return result


def _expected_supported(expected: str, result: Result) -> bool:
    if not expected:
        return result.evidence.decision is Decision.answered
    expected_tokens = content_tokens(expected)
    answer_tokens = content_tokens(result.answer)
    return bool(expected_tokens) and expected_tokens <= answer_tokens
