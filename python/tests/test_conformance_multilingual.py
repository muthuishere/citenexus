"""Python runs the ADR-0006 multilingual anti-drift corpus.

The gate, ``bm25``, and ``chunker`` STAY per host language; ``conformance/cases/
multilingual.json`` (Turkish dotted-İ, German ß, NFC vs NFD, CJK, combining
marks) is the shared vector suite that pins them against drift across Python,
Go, and JS. This test loads the COMMITTED fixture and runs Python's real runtime
functions against it — the same contract the Go and JS ports must satisfy — so a
regression in the reference tokenizer is caught here too, not only in the ports.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from citenexus.answer.verify import has_relevance_overlap, is_supported
from citenexus.evidence.chunker import chunk_text
from citenexus.storage.bm25 import Bm25TextSearch
from citenexus.tokenize import tokenize

_CORPUS = json.loads(
    (Path(__file__).resolve().parents[2] / "conformance" / "cases" / "multilingual.json").read_text(
        encoding="utf-8"
    )
)


class _StubStore:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def scan(self) -> list[dict[str, Any]]:
        return list(self._rows)


def test_multilingual_tokenize_vectors() -> None:
    cases = _CORPUS["tokenize"]
    assert cases, "no multilingual tokenize cases"
    for case in cases:
        assert tokenize(case["input"]) == case["tokens"], case["input"]


def test_multilingual_bm25_vectors() -> None:
    cases = _CORPUS["bm25"]
    assert cases, "no multilingual bm25 cases"
    for case in cases:
        search = Bm25TextSearch(_StubStore(case["rows"]))  # type: ignore[arg-type]
        results = search.search_text(case["query"], limit=10)
        got = [{"eu_id": r["eu_id"], "score": round(r["_text_score"], 6)} for r in results]
        assert got == case["expected"], case["name"]


def test_multilingual_chunker_vectors() -> None:
    cases = _CORPUS["chunker"]
    assert cases, "no multilingual chunker cases"
    for case in cases:
        got = chunk_text(case["text"], max_tokens=case["max_tokens"], overlap=case["overlap"])
        assert got == case["chunks"], case["text"]


def test_multilingual_gate_vectors() -> None:
    gate = _CORPUS["gate"]
    assert gate["supported"] and gate["relevance"], "no multilingual gate cases"
    for case in gate["supported"]:
        assert is_supported(case["answer"], case["passage"]) is case["supported"], case
    for case in gate["relevance"]:
        assert has_relevance_overlap(case["query"], case["passage"]) is case["relevant"], case
