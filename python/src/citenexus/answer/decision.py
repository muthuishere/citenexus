"""Structured single-decision output — the deep-ask loop's per-step primitive.

The library scripts the loop (`answer/agentic.py`); the model only answers small,
well-scoped decisions: *is the pool sufficient?* and *what should I search next?*.
That is a **JSON object parsed off the existing completion path** — NOT
OpenAI/Anthropic function-calling machinery. The wire clients gain one generic
``complete(prompt) -> str`` seam (`answer/generator.py`, `answer/anthropic.py`);
this module prompts through it and parses the reply. The model never owns control
flow, so a weak 7B driver cannot derail the loop.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, ConfigDict

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class LoopDecision(BaseModel):
    """One scripted-loop decision: keep going, and if so, on what query."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sufficient: bool = False
    next_query: str | None = None


class DecisionModel(Protocol):
    """The seam the loop asks its single per-hop decision through."""

    def decide(self, question: str, evidence: Sequence[str]) -> LoopDecision: ...


class Completion(Protocol):
    """A raw completion seam — one prompt in, one string out.

    Both wire generators implement this off their existing transport, with no
    provider tool/function-calling. Keeping it generic means the decision prompt
    and parsing live here, not in the clients.
    """

    def complete(self, prompt: str) -> str: ...


_DECISION_PROMPT = (
    "You are the controller of an evidence-gathering loop. Decide whether the "
    "evidence gathered so far is SUFFICIENT to answer the question, and if not, "
    "what single search query to run next. Reply with ONLY a JSON object of the "
    'form {{"sufficient": true|false, "next_query": "<query or null>"}}. No prose.'
    "\n\nQuestion: {question}\n\nEvidence so far:\n{evidence}"
)


def parse_decision(raw: str) -> LoopDecision:
    """Parse a ``LoopDecision`` from a plain completion string.

    Tolerant of surrounding prose: the first ``{...}`` object is extracted and
    validated. An unparseable reply is a conservative "not sufficient, no next
    query" — the loop then stops on ``no_new_evidence`` rather than looping blind.
    """
    match = _JSON_OBJECT.search(raw)
    if match is None:
        return LoopDecision()
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return LoopDecision()
    if not isinstance(payload, dict):
        return LoopDecision()
    sufficient = bool(payload.get("sufficient", False))
    next_query = payload.get("next_query")
    if not isinstance(next_query, str) or not next_query.strip():
        next_query = None
    return LoopDecision(sufficient=sufficient, next_query=next_query)


class CompletionDecisionModel:
    """A ``DecisionModel`` that parses a JSON decision off a ``Completion`` path."""

    def __init__(self, completion: Completion) -> None:
        self._completion = completion

    def decide(self, question: str, evidence: Sequence[str]) -> LoopDecision:
        prompt = _DECISION_PROMPT.format(
            question=question,
            evidence="\n---\n".join(evidence) if evidence else "(none)",
        )
        return parse_decision(self._completion.complete(prompt))
