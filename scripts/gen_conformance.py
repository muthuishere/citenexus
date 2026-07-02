"""Generate the cross-language conformance fixtures (docs/SPEC-PORTS-v1.md §10).

The Python implementation is the reference (§0): these fixtures are *computed*
from its internals, committed under ``conformance/``, and guarded against drift
by ``tests/test_conformance_fixtures.py``. Ports (Go / TypeScript / the Rust
core) load the same files and must reproduce every expected output exactly.

Run with:  uv run python scripts/gen_conformance.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from citenexus.answer.generator import _SYSTEM_PROMPT
from citenexus.answer.verify import _STOPWORDS, has_relevance_overlap, is_supported
from citenexus.domain.partition import PartitionPath
from citenexus.evidence.builder import build_evidence_units
from citenexus.evidence.chunked_builder import build_chunked_units
from citenexus.evidence.chunker import chunk_text
from citenexus.evidence.contextualize import _PROMPT as _CONTEXTUALIZE_PROMPT
from citenexus.extract.types import BlockKind, ExtractedBlock, ExtractedDoc, SourceType
from citenexus.lang.detect import LanguageResult
from citenexus.lang.fallback import resolve_answer_language
from citenexus.retrieve.fusion import rrf_fuse
from citenexus.retrieve.reformulate import _PROMPT as _REFORMULATE_PROMPT
from citenexus.retrieve.types import Candidate, RetrievalSignal
from citenexus.storage.bm25 import Bm25TextSearch
from citenexus.testing.fakes import tokenize
from citenexus.vision.client import _VISION_PROMPT

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PARTITION = PartitionPath.of(("workspace", "default"))


# --------------------------------------------------------------------------- #
# pinned data (§4, §5)
# --------------------------------------------------------------------------- #


def _stopwords() -> list[str]:
    words = sorted(_STOPWORDS)
    if len(words) != 44:  # the spec pins "the fixed 44-word English list"
        raise AssertionError(f"expected 44 stopwords, got {len(words)}")
    return words


def _prompts() -> dict[str, str]:
    return {
        "grounded_answer": _SYSTEM_PROMPT,
        "vision_describe": _VISION_PROMPT,
        "contextualize": _CONTEXTUALIZE_PROMPT,
        "reformulate": _REFORMULATE_PROMPT,
    }


# --------------------------------------------------------------------------- #
# cases/tokenize.json — text -> tokens (lowercase [a-z0-9]+, ASCII only)
# --------------------------------------------------------------------------- #

_TOKENIZE_INPUTS = [
    "Hello, World!",
    "The price is $4.50 (approx).",
    "ISO-9001:2015 certified",
    "MixedCASE tokens123abc under_score",
    "co-operate re-use state-of-the-art",
    "Café Münster naïve résumé",  # accents are non-ASCII and split tokens
    "Über die Straße",
    "தமிழ் உரை and english words",  # non-Latin scripts contribute no tokens
    "3.14159 and 2e10 numbers",
    "",
    "   \n\t  ",
]


def _tokenize_cases() -> list[dict[str, Any]]:
    return [{"input": text, "tokens": tokenize(text)} for text in _TOKENIZE_INPUTS]


# --------------------------------------------------------------------------- #
# cases/bm25.json — rows + query -> ordered (eu_id, score rounded 1e-6)
# --------------------------------------------------------------------------- #


class _StubStore:
    """Minimal scan()-capable store for Bm25TextSearch."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def scan(self) -> list[dict[str, Any]]:
        return list(self._rows)


_BM25_CASES: list[dict[str, Any]] = [
    {
        "name": "single term, tf and length normalization",
        "rows": [
            {"eu_id": "d1::0", "text": "the employee may not disclose confidential information"},
            {"eu_id": "d1::1", "text": "disclose disclose disclose"},
            {"eu_id": "d2::0", "text": "annual leave policy for employees"},
        ],
        "query": "disclose",
    },
    {
        "name": "multi-term idf weighting",
        "rows": [
            {"eu_id": "a::0", "text": "contract term and termination clause"},
            {"eu_id": "a::1", "text": "termination requires written notice"},
            {"eu_id": "b::0", "text": "contract contract contract everywhere"},
            {"eu_id": "b::1", "text": "unrelated text about holidays"},
        ],
        "query": "contract termination",
    },
    {
        "name": "zero-score rows are dropped; ties keep input order",
        "rows": [
            {"eu_id": "x::0", "text": "alpha beta"},
            {"eu_id": "x::1", "text": "alpha beta"},
            {"eu_id": "x::2", "text": "gamma delta"},
        ],
        "query": "alpha",
    },
    {
        "name": "query tokens absent everywhere -> empty result",
        "rows": [
            {"eu_id": "y::0", "text": "nothing relevant here"},
            {"eu_id": "y::1", "text": "still nothing"},
        ],
        "query": "quantum entanglement",
    },
]


def _bm25_cases() -> list[dict[str, Any]]:
    cases = []
    for case in _BM25_CASES:
        search = Bm25TextSearch(_StubStore(case["rows"]))  # type: ignore[arg-type]
        results = search.search_text(case["query"], limit=10)
        cases.append(
            {
                "name": case["name"],
                "rows": case["rows"],
                "query": case["query"],
                "expected": [
                    {"eu_id": row["eu_id"], "score": round(row["_text_score"], 6)}
                    for row in results
                ],
            }
        )
    return cases


# --------------------------------------------------------------------------- #
# cases/rrf.json — ranked eu_id lists -> fused order (k=60, zero-based rank)
# --------------------------------------------------------------------------- #

_RRF_CASES: list[list[list[str]]] = [
    # agreement across lists beats a single high rank
    [["a", "b", "c"], ["b", "c", "d"], ["b", "a", "e"]],
    # single list is a no-op on order
    [["x", "y", "z"]],
    # tie on fused score -> eu_id lexicographic tie-break
    [["a", "b"], ["b", "a"]],
    # disjoint lists interleave by rank
    [["a1", "a2", "a3"], ["b1", "b2"]],
    # empty lists contribute nothing
    [[], ["only"], []],
]


def _rrf_cases() -> list[dict[str, Any]]:
    cases = []
    for lists in _RRF_CASES:
        candidate_lists = [
            [
                Candidate(eu_id=eu_id, score=1.0 / (rank + 1), signal=RetrievalSignal.vector)
                for rank, eu_id in enumerate(one_list)
            ]
            for one_list in lists
        ]
        fused = rrf_fuse(candidate_lists, k=60)
        cases.append({"lists": lists, "k": 60, "fused": [c.eu_id for c in fused]})
    return cases


# --------------------------------------------------------------------------- #
# cases/faithful.json — faithfulness (ALL tokens) + relevance (content tokens)
# --------------------------------------------------------------------------- #

_SUPPORTED_INPUTS: list[tuple[str, str]] = [
    # verbatim quote -> supported
    (
        "The employee may not disclose confidential information.",
        "Policy: The employee may not disclose confidential information. See §4.",
    ),
    # punctuation / case insensitive (token-level)
    ("EMPLOYEE, may NOT disclose!", "the employee may not disclose confidential information"),
    # one invented word -> unsupported
    (
        "The employee may freely disclose information.",
        "The employee may not disclose confidential information.",
    ),
    # faithfulness uses ALL tokens: a stopword absent from the passage fails
    ("employees the", "employees must comply"),
    # empty answer is never supported
    ("", "any passage at all"),
    # numbers must match exactly
    ("notice period is 30 days", "the notice period is 30 days per contract"),
    ("notice period is 60 days", "the notice period is 30 days per contract"),
]

_RELEVANCE_INPUTS: list[tuple[str, str]] = [
    # shared content token -> relevant
    ("Can the employee disclose this?", "The employee may not disclose confidential data."),
    # stopword-only overlap -> not relevant
    ("what is the that", "the policy covers annual leave"),
    # no overlap at all
    ("quarterly revenue targets", "the cafeteria menu changes weekly"),
    # numbers are content tokens
    ("does clause 7 apply", "clause 7 applies to contractors only"),
    # non-ASCII scripts yield no tokens -> no overlap (ASCII tokenizer, §4)
    ("தமிழ் கேள்வி", "தமிழ் ஆவணம்"),
]


def _faithful_cases() -> dict[str, list[dict[str, Any]]]:
    return {
        "supported": [
            {"answer": answer, "passage": passage, "supported": is_supported(answer, passage)}
            for answer, passage in _SUPPORTED_INPUTS
        ],
        "relevance": [
            {"query": query, "passage": passage, "relevant": has_relevance_overlap(query, passage)}
            for query, passage in _RELEVANCE_INPUTS
        ],
    }


# --------------------------------------------------------------------------- #
# cases/chunker.json — text + params -> chunks
# --------------------------------------------------------------------------- #

_LONG_WORDS = " ".join(f"w{i:02d}" for i in range(25))
_PARAGRAPHS = (
    "Alpha one two three four five.\n\n"
    "Beta six seven eight nine ten eleven twelve.\n\n"
    "Gamma thirteen fourteen.\n\n"
    "Delta fifteen sixteen seventeen eighteen."
)
_SENTENCES = (
    "First sentence has five words here. Second sentence is also short. "
    "Third one keeps going a bit longer than the others did. Fourth ends it."
)

_CHUNKER_INPUTS: list[dict[str, Any]] = [
    {"text": "short text fits in one chunk", "max_tokens": 450, "overlap": 60},
    {"text": _PARAGRAPHS, "max_tokens": 12, "overlap": 3},
    {"text": _PARAGRAPHS, "max_tokens": 12, "overlap": 0},
    {"text": _SENTENCES, "max_tokens": 10, "overlap": 2},
    {"text": _LONG_WORDS, "max_tokens": 10, "overlap": 3},  # oversized word-run hard split
    {"text": "line one\nline two\nline three\nline four", "max_tokens": 4, "overlap": 2},
    {"text": "   ", "max_tokens": 10, "overlap": 2},  # whitespace-only -> no chunks
]


def _chunker_cases() -> list[dict[str, Any]]:
    return [
        {
            **case,
            "chunks": chunk_text(
                case["text"], max_tokens=case["max_tokens"], overlap=case["overlap"]
            ),
        }
        for case in _CHUNKER_INPUTS
    ]


# --------------------------------------------------------------------------- #
# cases/language.json — the §11a answer-language fallback chain, rung by rung
# --------------------------------------------------------------------------- #

_LANGUAGE_INPUTS: list[dict[str, Any]] = [
    {
        "name": "rung 1: reliable detection wins over everything",
        "detection": {"language": "ta", "confidence": 0.95, "is_reliable": True},
        "answer_language": "fr",
        "conversation_language": "de",
        "languages_in_evidence": ["en", "en"],
        "default_answer_language": "en",
    },
    {
        "name": "rung 2: unreliable detection -> explicit override",
        "detection": {"language": "en", "confidence": 0.30, "is_reliable": False},
        "answer_language": "fr",
        "conversation_language": "de",
        "languages_in_evidence": ["en"],
        "default_answer_language": "en",
    },
    {
        "name": "rung 3: no detection, no override -> conversation language",
        "detection": None,
        "answer_language": None,
        "conversation_language": "de",
        "languages_in_evidence": ["en", "es"],
        "default_answer_language": "en",
    },
    {
        "name": "rung 4: dominant evidence language",
        "detection": {"language": "en", "confidence": 0.20, "is_reliable": False},
        "answer_language": None,
        "conversation_language": None,
        "languages_in_evidence": ["en", "es", "es"],
        "default_answer_language": "en",
    },
    {
        "name": "rung 4 tie: first-seen evidence language wins (stable)",
        "detection": None,
        "answer_language": None,
        "conversation_language": None,
        "languages_in_evidence": ["fr", "en", "fr", "en"],
        "default_answer_language": "en",
    },
    {
        "name": "rung 5: nothing else -> configured default",
        "detection": None,
        "answer_language": None,
        "conversation_language": None,
        "languages_in_evidence": [],
        "default_answer_language": "hi",
    },
]


def _language_cases() -> list[dict[str, Any]]:
    cases = []
    for case in _LANGUAGE_INPUTS:
        detection = LanguageResult(**case["detection"]) if case["detection"] is not None else None
        expected = resolve_answer_language(
            detection=detection,
            answer_language=case["answer_language"],
            conversation_language=case["conversation_language"],
            languages_in_evidence=case["languages_in_evidence"],
            default_answer_language=case["default_answer_language"],
        )
        cases.append({**case, "expected": expected})
    return cases


# --------------------------------------------------------------------------- #
# cases/eu_ids.json — block layouts -> eu_id lists (both builders) + checksum
# --------------------------------------------------------------------------- #

_EU_DOCS: list[dict[str, Any]] = [
    {
        "name": "block builder skips empty blocks; eu_id = doc::order",
        "document_id": "policy-1",
        "blocks": [
            {"order": 0, "kind": "heading", "text": "Confidentiality", "page": 1},
            {"order": 1, "kind": "paragraph", "text": "Employees may not disclose.", "page": 1},
            {"order": 2, "kind": "paragraph", "text": "   ", "page": 1},
            {"order": 3, "kind": "table", "text": "term | value", "page": 2},
        ],
        "chunk_max_tokens": 450,
        "chunk_overlap": 60,
    },
    {
        "name": "chunked builder splits an oversized block into doc::order::i children",
        "document_id": "long-doc",
        "blocks": [
            {"order": 0, "kind": "heading", "text": "Intro", "page": 1},
            {
                "order": 1,
                "kind": "paragraph",
                "text": (
                    "One two three four five six seven eight.\n\n"
                    "Nine ten eleven twelve thirteen fourteen fifteen sixteen.\n\n"
                    "Seventeen eighteen nineteen twenty twenty-one twenty-two."
                ),
                "page": 2,
            },
        ],
        "chunk_max_tokens": 8,
        "chunk_overlap": 2,
    },
]


def _eu_id_cases() -> dict[str, Any]:
    cases = []
    for spec in _EU_DOCS:
        doc = ExtractedDoc(
            document_id=spec["document_id"],
            source_type=SourceType.plain,
            blocks=tuple(
                ExtractedBlock(
                    order=b["order"], kind=BlockKind(b["kind"]), text=b["text"], page=b["page"]
                )
                for b in spec["blocks"]
            ),
        )
        block_units = build_evidence_units(doc, partition=_PARTITION, language="en")
        chunked_units = build_chunked_units(
            doc,
            partition=_PARTITION,
            language="en",
            max_tokens=spec["chunk_max_tokens"],
            overlap=spec["chunk_overlap"],
        )
        cases.append(
            {
                **spec,
                "block_builder_eu_ids": [u.eu_id for u in block_units],
                "chunked_builder_eu_ids": [u.eu_id for u in chunked_units],
            }
        )
    raw = "hello citenexus\n"
    return {
        "cases": cases,
        "checksum_example": {
            "raw_utf8": raw,
            "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        },
    }


# --------------------------------------------------------------------------- #
# entry points
# --------------------------------------------------------------------------- #


def _render(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def generate() -> dict[str, str]:
    """All fixtures as {relative path under conformance/: rendered JSON text}."""
    return {
        "stopwords.json": _render(_stopwords()),
        "prompts.json": _render(_prompts()),
        "cases/tokenize.json": _render(_tokenize_cases()),
        "cases/bm25.json": _render(_bm25_cases()),
        "cases/rrf.json": _render(_rrf_cases()),
        "cases/faithful.json": _render(_faithful_cases()),
        "cases/chunker.json": _render(_chunker_cases()),
        "cases/language.json": _render(_language_cases()),
        "cases/eu_ids.json": _render(_eu_id_cases()),
    }


def main() -> None:
    base = _REPO_ROOT / "conformance"
    for rel_path, text in generate().items():
        path = base / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(_REPO_ROOT)}")


if __name__ == "__main__":
    main()
