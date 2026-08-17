"""Generate the cross-language conformance fixtures (docs/SPEC-PORTS-v1.md §10).

The Python implementation is the reference (§0): these fixtures are *computed*
from its internals, committed under ``conformance/``, and guarded against drift
by ``tests/test_conformance_fixtures.py``. Ports (Go / TypeScript / the Rust
core) load the same files and must reproduce every expected output exactly.

Run with:  uv run python scripts/gen_conformance.py
"""

from __future__ import annotations

import base64
import hashlib
import json
import unicodedata
from pathlib import Path
from typing import Any

from citenexus.answer.anthropic import AnthropicGenerator
from citenexus.answer.generator import _SYSTEM_PROMPT, OpenAICompatibleGenerator
from citenexus.answer.result import (
    Claim,
    Decision,
    EvidenceSignals,
    ProvenanceEntry,
    Result,
    SourceRef,
)
from citenexus.answer.segment import split_claims
from citenexus.answer.verify import (
    _STOPWORDS,
    content_tokens,
    has_relevance_overlap,
    is_supported,
    is_supported_v2,
)
from citenexus.domain.partition import PartitionPath
from citenexus.domain.trust import TrustMode
from citenexus.embed.client import OpenAICompatibleEmbedding
from citenexus.evidence.builder import build_evidence_units
from citenexus.evidence.chunked_builder import build_chunked_units
from citenexus.evidence.chunker import chunk_text
from citenexus.evidence.contextualize import _PROMPT as _CONTEXTUALIZE_PROMPT
from citenexus.evidence.structure import build_structure
from citenexus.extract.types import (
    BlockKind,
    ExtractedBlock,
    ExtractedDoc,
    SourceType,
    StructureType,
)
from citenexus.graph.distill import _PROMPT as _GRAPH_DISTILL_PROMPT
from citenexus.graph.store import build_comention_graph
from citenexus.lang.codes import Language, Script
from citenexus.lang.detect import LanguageResult
from citenexus.lang.fallback import AUTO_ANSWER_LANGUAGE, resolve_answer_language
from citenexus.lang.search import SEARCH_LANGUAGES
from citenexus.retrieve.fusion import rrf_fuse
from citenexus.retrieve.reformulate import _PROMPT as _REFORMULATE_PROMPT
from citenexus.retrieve.types import Candidate, RetrievalSignal
from citenexus.storage.bm25 import Bm25TextSearch
from citenexus.testing.fakes import FakeEmbedding, FakeLLM, tokenize
from citenexus.tokenize import (
    CONTINUOUS_SCRIPTS,
    SUPPORTED_SCRIPTS,
    TOKENIZER_VERSION,
    tokenize_v2,
    unsupported_scripts,
)
from citenexus.vision.client import _VISION_PROMPT
from citenexus.vision.describe import FakeVision
from citenexus.vision.fulfill import fulfill_vision_requests
from citenexus.vision.requests import build_pending_request
from citenexus.vision.units import build_vision_units
from citenexus.wiki.distill import _PROMPT as _WIKI_DISTILL_PROMPT

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
        "wiki_distill": _WIKI_DISTILL_PROMPT,
        "graph_distill": _GRAPH_DISTILL_PROMPT,
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
# cases/e2e_hermetic.json — corpus + questions -> cite-or-abstain outcome.
#
# This is §0 executed offline: with the pinned hash FakeEmbedding and the
# extractive FakeLLM, every port must reproduce the SAME decision/document/
# passage. It mirrors citenexus.smoke.SmokePipeline.ask over an in-memory cosine
# store (no LanceDB, no filesystem — the semantics ports must implement, not the
# storage). Questions are designed so content-token grounding selects exactly one
# document, so the outcome does not hinge on cosine tie-breaking.
# --------------------------------------------------------------------------- #

_REFUSAL = "I can't answer that from the available evidence."

_E2E_CORPUS: list[dict[str, str]] = [
    {"document_id": "nda", "text": "The employee shall not disclose confidential information."},
    {"document_id": "leave", "text": "Employees are entitled to thirty days of annual leave."},
    {
        "document_id": "termination",
        "text": "The contract termination clause requires ninety days written notice.",
    },
]

_E2E_QUESTIONS: list[str] = [
    "Can the employee disclose confidential information?",
    "How many days of annual leave do employees get?",
    "What notice does the termination clause require?",
    "What is the capital of France?",  # no content overlap -> abstain
]

_E2E_TOP_K = 5


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _hermetic_ask(question: str) -> dict[str, Any]:
    """The reference cite-or-abstain outcome for ``question`` over the corpus.

    Reuses the exact pinned primitives: FakeEmbedding (§4 hash), content-token
    grounding (relevance gate), the extractive FakeLLM, and the per-claim
    faithfulness gate (``split_claims`` + ``is_supported_v2``). Vectors are
    L2-normalized, so cosine == dot product.
    """
    embedder = FakeEmbedding()
    llm = FakeLLM()
    rows = [
        {
            "eu_id": f"{doc['document_id']}::0",
            "document_id": doc["document_id"],
            "text": doc["text"],
            "vector": embedder.embed(doc["text"]),
        }
        for doc in _E2E_CORPUS
    ]
    qvec = embedder.embed(question)
    # Rank by descending cosine, stable tie-break by insertion order; take top_k.
    ranked = sorted(rows, key=lambda r: -_cosine(qvec, r["vector"]))[:_E2E_TOP_K]
    q_terms = content_tokens(question)
    grounded = [r for r in ranked if q_terms & content_tokens(str(r["text"]))]
    if not grounded:
        return {
            "decision": Decision.refused.value,
            "answer": _REFUSAL,
            "document": None,
            "passage": None,
            "eu_id": None,
        }
    top = grounded[0]
    passage = str(top["text"])
    generated = llm.answer(question, passage)
    # Per-atomic-claim gate, mirroring SmokePipeline.ask (ADR-0009).
    supported = [c for c in split_claims(generated) if is_supported_v2(c, passage)]
    if not supported:
        return {
            "decision": Decision.refused.value,
            "answer": _REFUSAL,
            "document": None,
            "passage": None,
            "eu_id": None,
        }
    answer = " ".join(supported)
    return {
        "decision": Decision.answered.value,
        "answer": answer,
        "document": str(top["document_id"]),
        "passage": passage,
        "eu_id": str(top["eu_id"]),
    }


def _e2e_hermetic_cases() -> dict[str, Any]:
    return {
        "corpus": _E2E_CORPUS,
        "top_k": _E2E_TOP_K,
        "refusal_answer": _REFUSAL,
        "cases": [{"question": q, "expected": _hermetic_ask(q)} for q in _E2E_QUESTIONS],
    }


# --------------------------------------------------------------------------- #
# cases/result_roundtrip.json — canonical Result JSON (§7). Ports must serialize
# an equivalent Result to byte-identical JSON (field names, enum values, null
# handling, empty arrays).
# --------------------------------------------------------------------------- #


def _result_roundtrip_cases() -> list[dict[str, Any]]:
    answered = Result(
        answer="The employee shall not disclose confidential information.",
        answer_language="en",
        mode=TrustMode.strict,
        evidence=EvidenceSignals(
            decision=Decision.answered,
            supporting_sources=1,
            distinct_documents=1,
            all_claims_verified=True,
            languages_in_evidence=("en",),
        ),
        claims=(
            Claim(
                claim="The employee shall not disclose confidential information.",
                supported=True,
                sources=("nda::0",),
            ),
        ),
        sources=(
            SourceRef(
                document="nda",
                passage="The employee shall not disclose confidential information.",
                passage_language="en",
                source_uri="raw/workspace=default/nda-sha",
            ),
        ),
        provenance=(
            ProvenanceEntry(
                claim="The employee shall not disclose confidential information.",
                evidence_unit="nda::0",
                document_id="nda",
                s3_object="raw/workspace=default/nda-sha",
                checksum="a" * 64,
                produced_by={"embedding": "fake-hashing"},
            ),
        ),
    )
    refused = Result(
        answer=_REFUSAL,
        answer_language="en",
        mode=TrustMode.strict,
        evidence=EvidenceSignals(decision=Decision.refused),
        missing_evidence=("no sufficiently relevant evidence found",),
    )
    return [
        {"name": "answered with full provenance", "result": answered.model_dump(mode="json")},
        {"name": "refused on no evidence", "result": refused.model_dump(mode="json")},
    ]


# --------------------------------------------------------------------------- #
# cases/model_wire.json — the §5 model-client wire contract. For each client the
# fixture pins (a) the EXACT HTTP request bytes it must emit for given inputs and
# (b) the parsed output for a canned response. Captured from the Python reference
# clients via a recording transport, so ports reproduce the wire byte-for-byte
# with an injected fake transport (hermetic, no network). Auth headers are the
# endpoint layer's job (never here) — the wire body carries no secrets.
# --------------------------------------------------------------------------- #

_WIRE_QUESTION = "Can the employee disclose confidential information?"
_WIRE_PASSAGE = "The employee shall not disclose confidential information."
_WIRE_ANSWER = "The employee shall not disclose confidential information."


class _Capture:
    """Recording transport: stores the request, returns a canned response."""

    def __init__(self, response: bytes) -> None:
        self._response = response
        self.call: dict[str, Any] | None = None

    def __call__(self, url: str, body: bytes, headers: dict[str, str]) -> bytes:
        self.call = {
            "method": "POST",
            "url": url,
            "headers": dict(headers),
            "body": json.loads(body.decode("utf-8")),
        }
        return self._response


def _wire_requests() -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []

    # OpenAI-compatible chat (/chat/completions), no max_tokens.
    cap = _Capture(b'{"choices":[{"message":{"content":"x"}}]}')
    OpenAICompatibleGenerator(
        base_url="https://api.example.com/v1", model="qwen2.5", transport=cap
    ).answer(_WIRE_QUESTION, _WIRE_PASSAGE, "en")
    requests.append(
        {
            "name": "openai chat answer, temperature always sent, no max_tokens",
            "client": "openai_chat",
            "config": {"base_url": "https://api.example.com/v1", "model": "qwen2.5"},
            "inputs": {
                "question": _WIRE_QUESTION,
                "passage": _WIRE_PASSAGE,
                "answer_language": "en",
            },
            "expected_request": cap.call,
        }
    )

    # OpenAI-compatible chat with max_tokens set.
    cap = _Capture(b'{"choices":[{"message":{"content":"x"}}]}')
    OpenAICompatibleGenerator(
        base_url="https://api.example.com/v1", model="qwen2.5", max_tokens=256, transport=cap
    ).answer(_WIRE_QUESTION, _WIRE_PASSAGE, "de")
    requests.append(
        {
            "name": "openai chat answer with max_tokens and non-en language",
            "client": "openai_chat",
            "config": {
                "base_url": "https://api.example.com/v1",
                "model": "qwen2.5",
                "max_tokens": 256,
            },
            "inputs": {
                "question": _WIRE_QUESTION,
                "passage": _WIRE_PASSAGE,
                "answer_language": "de",
            },
            "expected_request": cap.call,
        }
    )

    # Anthropic Messages (/v1/messages): system top-level, required max_tokens.
    cap = _Capture(b'{"content":[{"type":"text","text":"x"}]}')
    AnthropicGenerator(
        base_url="https://api.anthropic.com", model="claude-x", transport=cap
    ).answer(_WIRE_QUESTION, _WIRE_PASSAGE, "en")
    requests.append(
        {
            "name": "anthropic messages: top-level system + default max_tokens 1024",
            "client": "anthropic",
            "config": {"base_url": "https://api.anthropic.com", "model": "claude-x"},
            "inputs": {
                "question": _WIRE_QUESTION,
                "passage": _WIRE_PASSAGE,
                "answer_language": "en",
            },
            "expected_request": cap.call,
        }
    )

    # OpenAI-compatible embeddings (/embeddings): batched input list.
    cap = _Capture(b'{"data":[{"embedding":[0.1]},{"embedding":[0.2]}]}')
    OpenAICompatibleEmbedding(
        base_url="https://api.example.com/v1", model="bge-m3", transport=cap
    ).embed([_WIRE_PASSAGE, "Employees are entitled to annual leave."])
    requests.append(
        {
            "name": "openai embeddings: batched input, order preserved",
            "client": "openai_embed",
            "config": {"base_url": "https://api.example.com/v1", "model": "bge-m3"},
            "inputs": {"texts": [_WIRE_PASSAGE, "Employees are entitled to annual leave."]},
            "expected_request": cap.call,
        }
    )
    return requests


def _wire_responses() -> list[dict[str, Any]]:
    responses: list[dict[str, Any]] = []

    # OpenAI chat: reply = choices[0].message.content.
    chat_body = {
        "choices": [{"message": {"content": _WIRE_ANSWER}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 8},
    }
    chat_out = OpenAICompatibleGenerator(
        base_url="https://x", model="m", transport=lambda _u, _b, _h: json.dumps(chat_body).encode()
    ).answer(_WIRE_QUESTION, _WIRE_PASSAGE, "en")
    responses.append(
        {
            "name": "openai chat parse",
            "client": "openai_chat",
            "response_body": chat_body,
            "expected": chat_out,
        }
    )

    # Anthropic: concat content[].text, non-text blocks ignored, order kept.
    anth_body = {
        "content": [
            {"type": "text", "text": "The employee "},
            {"type": "tool_use", "id": "t1", "name": "x", "input": {}},
            {"type": "text", "text": "shall not disclose."},
        ],
        "usage": {"input_tokens": 20, "output_tokens": 6},
    }
    anth_out = AnthropicGenerator(
        base_url="https://x", model="m", transport=lambda _u, _b, _h: json.dumps(anth_body).encode()
    ).answer(_WIRE_QUESTION, _WIRE_PASSAGE, "en")
    responses.append(
        {
            "name": "anthropic parse multi-block text-only",
            "client": "anthropic",
            "response_body": anth_body,
            "expected": anth_out,
        }
    )

    # Embeddings: data[].embedding as float vectors, input order preserved.
    emb_body = {"data": [{"embedding": [0.1, 0.2, 0.3]}, {"embedding": [0.4, 0.5, 0.6]}]}
    emb_out = OpenAICompatibleEmbedding(
        base_url="https://x", model="m", transport=lambda _u, _b, _h: json.dumps(emb_body).encode()
    ).embed(["a", "b"])
    responses.append(
        {
            "name": "openai embeddings parse",
            "client": "openai_embed",
            "response_body": emb_body,
            "expected": emb_out,
        }
    )
    return responses


def _model_wire_cases() -> dict[str, Any]:
    return {"requests": _wire_requests(), "responses": _wire_responses()}


# --------------------------------------------------------------------------- #
# entry points
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# cases/vision_orchestration.json — the two-phase vision seam (ADR-0005, §9).
#
# Pins the plain-data contract of emit -> fulfill -> assemble so Go/TS/Rust
# reproduce it byte-for-byte. `emit` is the ordered tuple of PendingVisionRequests
# the core produces from vision-routed images (data URI + prompt + source_ref);
# the two images carry PNG vs JPEG magic bytes, pinning that the emitted payload
# declares each image's TRUE media type (sniffed, not hardcoded) so a port that
# POSTs the payload verbatim never mislabels the format. `assembled_eus` is the
# figure EUs the core builds after the host fulfills them (here with the
# deterministic FakeVision). `degrade` shows a request the host left unfulfilled
# yielding no EU — per-request degrade-to-text. Only the raw model call between
# emit and fulfill may differ per language.
# --------------------------------------------------------------------------- #

_VISION_IMAGES: list[dict[str, Any]] = [
    {
        "image_id": "page1-fig0",
        "page": 1,
        "bbox": [10.0, 20.0, 110.0, 220.0],
        "bytes": b"\x89PNG\r\n\x1a\n citenexus conformance png figure",
    },
    {
        "image_id": "page2-fig1",
        "page": 2,
        "bbox": [0.0, 0.0, 50.0, 50.0],
        "bytes": b"\xff\xd8\xff\xe0 citenexus conformance jpeg figure",
    },
]


def _vision_orchestration_cases() -> dict[str, Any]:
    document_id = "annual-report"
    source_uri = "raw/annual-report.pdf"
    requests = [
        build_pending_request(
            document_id=document_id,
            image_id=img["image_id"],
            data=img["bytes"],
            prompt=_VISION_PROMPT,
            page=img["page"],
            bbox=tuple(img["bbox"]),
            source_uri=source_uri,
        )
        for img in _VISION_IMAGES
    ]
    fulfilled = fulfill_vision_requests(requests, FakeVision())
    assembled = build_vision_units(requests, fulfilled, partition=_PARTITION, language="en")

    # Degrade: the host fulfills only the second request; the first yields no EU.
    partial = {requests[1].request_id: fulfilled[requests[1].request_id]}
    degraded = build_vision_units(requests, partial, partition=_PARTITION, language="en")

    return {
        "document_id": document_id,
        "source_uri": source_uri,
        "language": "en",
        "images": [
            {"image_id": img["image_id"], "bytes_b64": base64.b64encode(img["bytes"]).decode()}
            for img in _VISION_IMAGES
        ],
        "emit": [r.model_dump(mode="json") for r in requests],
        "fulfilled": {rid: rec.model_dump(mode="json") for rid, rec in fulfilled.items()},
        "assembled_eus": [eu.model_dump(mode="json") for eu in assembled],
        "degrade": {
            "fulfilled": {rid: rec.model_dump(mode="json") for rid, rec in partial.items()},
            "assembled_eu_ids": [eu.eu_id for eu in degraded],
        },
    }


def _render(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


# --------------------------------------------------------------------------- #
# cases/graph_comention.json — deterministic co-mention graph (§10b).
# Input: EU rows {eu_id, text}. Output: the exact GraphIndex JSON. Nodes are
# content tokens of length >= 4; edges are within-EU co-mentions, weighted.
# --------------------------------------------------------------------------- #

_GRAPH_CORPORA: list[dict[str, Any]] = [
    {
        "name": "two overlapping docs",
        "rows": [
            {
                "eu_id": "d1::0",
                "text": "The employee cannot disclose confidential salary information.",
            },
            {
                "eu_id": "d2::0",
                "text": "Confidential salary information stays private under the policy.",
            },
        ],
    },
    {
        "name": "no long tokens",
        "rows": [{"eu_id": "x::0", "text": "a b to of the it is"}],
    },
    {
        "name": "single doc self co-mention",
        "rows": [{"eu_id": "s::0", "text": "Bitcoin funding funding spike spike bitcoin"}],
    },
]


def _graph_comention_cases() -> dict[str, Any]:
    cases = []
    for spec in _GRAPH_CORPORA:
        index = build_comention_graph(spec["rows"])
        cases.append({**spec, "expected": index.model_dump(mode="json")})
    return {"cases": cases}


# --------------------------------------------------------------------------- #
# cases/structure.json — best-effort document Structure Index (§7b).
# heading_tree nests headings by level; slide_sequence is flat; else zero nodes.
# --------------------------------------------------------------------------- #

_STRUCTURE_DOCS: list[dict[str, Any]] = [
    {
        "name": "heading tree",
        "document_id": "doc-h",
        "structure_type": "heading_tree",
        "blocks": [
            {"order": 0, "kind": "heading", "text": "Chapter 1", "level": 1},
            {"order": 1, "kind": "paragraph", "text": "body text", "level": None},
            {"order": 2, "kind": "heading", "text": "Section 1.1", "level": 2},
            {"order": 3, "kind": "heading", "text": "Section 1.2", "level": 2},
            {"order": 4, "kind": "heading", "text": "Chapter 2", "level": 1},
        ],
    },
    {
        "name": "slide sequence",
        "document_id": "doc-s",
        "structure_type": "slide_sequence",
        "blocks": [
            {"order": 0, "kind": "slide", "text": "Title slide", "level": None},
            {"order": 1, "kind": "slide", "text": "Agenda", "level": None},
        ],
    },
    {
        "name": "no structure",
        "document_id": "doc-n",
        "structure_type": "none",
        "blocks": [{"order": 0, "kind": "paragraph", "text": "just prose", "level": None}],
    },
]


def _structure_cases() -> dict[str, Any]:
    cases = []
    for spec in _STRUCTURE_DOCS:
        doc = ExtractedDoc(
            document_id=spec["document_id"],
            source_type=SourceType.plain,
            structure_type=StructureType(spec["structure_type"]),
            blocks=tuple(
                ExtractedBlock(
                    order=b["order"],
                    kind=BlockKind(b["kind"]),
                    text=b["text"],
                    level=b["level"],
                )
                for b in spec["blocks"]
            ),
        )
        index = build_structure(doc)
        cases.append({**spec, "expected": index.model_dump(mode="json")})
    return {"cases": cases}


# --------------------------------------------------------------------------- #
# cases/multilingual.json — the ADR-0006 anti-drift corpus. The gate, bm25, and
# chunker STAY per host language (not in the Rust core); this Unicode-edge suite
# is what pins them against drift where it actually happens — the tokenizer's
# case-folding and Unicode boundaries. Every case's expected output is computed
# from the SAME reference functions the runtime uses (tokenize / Bm25TextSearch
# / chunk_text / is_supported / has_relevance_overlap), so a port whose
# tokenization diverges on Turkish dotless-I, German ß, NFC vs NFD, CJK, or a
# combining mark FAILS the vector instead of passing silently on ASCII.
# --------------------------------------------------------------------------- #


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _nfd(text: str) -> str:
    return unicodedata.normalize("NFD", text)


# Turkish dotted capital İ (U+0130) is THE canonical trap: Python/JS full case
# mapping lowers it to "i" + combining dot above (U+0307), splitting the ASCII
# run; a simple 1:1 lowercase (e.g. Go's strings.ToLower) drops the dot and
# yields a single "istanbul". These inputs make that divergence observable.
_ML_TOKENIZE_INPUTS: list[str] = [
    "İstanbul Büyükşehir Belediyesi",  # dotted capital I -> "i" + "stanbul"
    "ISPARTA ve Iğdır",  # ASCII I stays "i"; dotless-related caps
    "ıstanbul kışın",  # dotless lowercase i produces no leading token
    "Straße Grüße Weiß",  # German ß is lowercase already, non-ASCII -> splits
    "GROSSE STRASSE ist frei",  # uppercase ss round-trips to "strasse"
    _nfc("Café Résumé Déjà"),  # precomposed accents -> non-ASCII, split tokens
    _nfd("Café Résumé Déjà"),  # decomposed: base ASCII letter survives the mark
    "東京タワー Tokyo Tower 2024",  # CJK yields no tokens; latin/digits do
    _nfd("e") + "́clair na" + "̈" + "ive",  # leading/mid combining marks
    "Αθήνα Athens Ελλάδα",  # Greek script contributes no ASCII tokens
]


def _ml_tokenize_cases() -> list[dict[str, Any]]:
    return [{"input": text, "tokens": tokenize(text)} for text in _ML_TOKENIZE_INPUTS]


_ML_BM25_CASES: list[dict[str, Any]] = [
    {
        "name": "turkish dotted-I: query 'İstanbul' -> one token i+U+0307+stanbul",
        "rows": [
            {"eu_id": "tr::0", "text": "İstanbul Büyükşehir Belediyesi kararı"},
            {"eu_id": "tr::1", "text": "Ankara başkenttir ve merkezdir"},
        ],
        "query": "İstanbul",
    },
    {
        "name": "german ß: query 'Straße' case-folds to one token strasse",
        "rows": [
            {"eu_id": "de::0", "text": "Die große Straße ist heute gesperrt"},
            {"eu_id": "de::1", "text": "Eine kleine Gasse ohne jede Sperrung"},
        ],
        "query": "Straße",
    },
    {
        "name": "cjk text ranks by latin/digit tokens AND its han bigrams",
        "rows": [
            {"eu_id": "cjk::0", "text": "東京 Tokyo 2024 annual report"},
            {"eu_id": "cjk::1", "text": "大阪 Osaka quarterly summary"},
        ],
        "query": "Tokyo 2024",
    },
]


def _ml_bm25_cases() -> list[dict[str, Any]]:
    cases = []
    for case in _ML_BM25_CASES:
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


_ML_CHUNKER_INPUTS: list[dict[str, Any]] = [
    # paragraph boundaries with multilingual content; word counting is
    # Unicode-whitespace aware and must agree across ports.
    {
        "text": "Straße eins zwei\n\nGrüße drei vier\n\n東京 大阪 名古屋\n\nAthens final",
        "max_tokens": 3,
        "overlap": 1,
    },
    # ideographic spaces (U+3000) are whitespace: three CJK "words" then a hard cap.
    {"text": "東京　大阪　名古屋　福岡　札幌", "max_tokens": 2, "overlap": 0},
]


def _ml_chunker_cases() -> list[dict[str, Any]]:
    return [
        {
            **case,
            "chunks": chunk_text(
                case["text"], max_tokens=case["max_tokens"], overlap=case["overlap"]
            ),
        }
        for case in _ML_CHUNKER_INPUTS
    ]


# The gate compares token SETS across answer/passage (and query/passage), so it
# diverges when the two sides tokenize a shared Unicode form differently from
# the reference. An ASCII answer against a Turkish-İ passage is the sharp case:
# the reference splits İ into "i"+"stanbul" so a bare "istanbul" is NOT present.
_ML_SUPPORTED_INPUTS: list[tuple[str, str]] = [
    # reference: passage tokens = {i, stanbul, ...}; ASCII "istanbul" absent -> unsupported
    ("Istanbul is the city", "İstanbul is a coastal city"),
    # decomposed accent: base letter survives, so ASCII faithfulness holds
    (_nfd("Résumé received"), _nfd("The résumé was received on time")),
    # German ß both sides -> supported (identical tokenization on each side)
    ("Große Straße", "Die große Straße wurde gesperrt"),
]

_ML_RELEVANCE_INPUTS: list[tuple[str, str]] = [
    # 'i' is a stopword; İstanbul -> {stanbul,...}; ASCII query 'Istanbul' -> {istanbul}
    # so the reference finds NO overlap, while a dot-dropping tokenizer would.
    ("Istanbul plans", "İstanbul Belediyesi duyurusu"),
    # CJK query shares its latin token with the passage
    ("Tokyo report", "東京 Tokyo annual report"),
    # German ß shared content token 'stra'
    ("Straße update", "Die Straße wurde erneuert"),
]


def _ml_gate_cases() -> dict[str, list[dict[str, Any]]]:
    return {
        "supported": [
            {"answer": answer, "passage": passage, "supported": is_supported(answer, passage)}
            for answer, passage in _ML_SUPPORTED_INPUTS
        ],
        "relevance": [
            {"query": query, "passage": passage, "relevant": has_relevance_overlap(query, passage)}
            for query, passage in _ML_RELEVANCE_INPUTS
        ],
    }


def _multilingual_cases() -> dict[str, Any]:
    return {
        "tokenize": _ml_tokenize_cases(),
        "bm25": _ml_bm25_cases(),
        "chunker": _ml_chunker_cases(),
        "gate": _ml_gate_cases(),
    }


# --------------------------------------------------------------------------- #
# polarity.json / segmentation.json — ADR-0010 tier-2 tables.
# The Python module is the reference (conformance/README.md §0); every port's
# copy is GENERATED from these files, never hand-maintained.
# --------------------------------------------------------------------------- #


def _polarity_table() -> dict[str, Any]:
    from citenexus.answer.tables import POLARITY_LANGUAGES, POLARITY_MARKERS

    return {
        "languages": list(POLARITY_LANGUAGES),
        "markers": sorted(POLARITY_MARKERS),
    }


def _conflict_table() -> dict[str, Any]:
    """ADR-0007 conflict tables + the pinned thresholds.

    ``max_residual`` is data here on purpose: a port that quietly relaxes it to 2
    buys 4pp of recall and pays 15pp of false abstention, and the only way to
    catch that across languages is to pin the number in the shared contract.
    """
    from citenexus.answer import conflict as conflict_module
    from citenexus.answer.tables import (
        CONFLICT_ANTONYMS,
        CONFLICT_NEGATIONS,
        CONFLICT_REPORT_BIGRAMS,
        CONFLICT_SCOPE_MARKERS,
        MEASUREMENT_UNITS,
    )

    return {
        "languages": ["en"],
        "negations": sorted(CONFLICT_NEGATIONS),
        "antonyms": sorted(sorted(pair) for pair in CONFLICT_ANTONYMS),
        "report_bigrams": sorted(list(pair) for pair in CONFLICT_REPORT_BIGRAMS),
        "scope_markers": sorted(CONFLICT_SCOPE_MARKERS),
        "measurement_units": sorted(MEASUREMENT_UNITS),
        "thresholds": {
            "subject_overlap": conflict_module.SUBJECT_OVERLAP,
            "max_symdiff": conflict_module.MAX_SYMDIFF,
            "max_residual": conflict_module.MAX_RESIDUAL,
            "min_content": conflict_module.MIN_CONTENT,
            "duplicate_jaccard": conflict_module.DUPLICATE_JACCARD,
            "duplicate_max_length_delta": conflict_module.DUPLICATE_MAX_LENGTH_DELTA,
            "top_k": conflict_module.CONFLICT_TOP_K,
        },
    }


def _conflict_cases() -> dict[str, Any]:
    """Every ADR-0007 fixture with its expected verdict.

    The hard negatives are the load-bearing half: a port that reproduces the true
    conflicts but not the *declines* has a higher false-abstention rate than this
    one, and nothing inside it would say so.
    """
    import sys

    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from tests.answer.test_conflict import (
        DUPLICATE_CASES,
        HARD_NEGATIVES,
        HELDOUT_CONFLICTS,
        HELDOUT_NEGATIVES,
        NON_LATIN,
        TRUE_CONFLICTS,
        UNRELATED,
    )

    from citenexus.answer.conflict import detect_conflict, is_near_duplicate

    def _pairs(fixtures: list[tuple[str, str, str, str]]) -> list[dict[str, Any]]:
        rows = []
        for domain, label, left, right in fixtures:
            finding = detect_conflict(left, right)
            rows.append(
                {
                    "domain": domain,
                    "label": label,
                    "left": left,
                    "right": right,
                    "conflict": finding is not None,
                    "rule": finding.rule if finding else None,
                }
            )
        return rows

    return {
        "true_conflicts": _pairs(TRUE_CONFLICTS),
        "hard_negatives": _pairs(HARD_NEGATIVES),
        "unrelated": _pairs(UNRELATED),
        "heldout_conflicts": _pairs(HELDOUT_CONFLICTS),
        "heldout_negatives": _pairs(HELDOUT_NEGATIVES),
        # ADR-0011. Conflict ran on the FROZEN v1 tokenizer until this bucket
        # existed, and v1 is ASCII-only by contract — so nearly every pair here
        # scored "no conflict" before a single rule ran, and a Tamil or Telugu
        # corpus holding a filing plus its restatement produced a confident,
        # correctly-cited, one-sided answer with conflicts_detected=0. Moving to
        # tokenize_v2 fixed Tamil, Telugu and Arabic; Japanese and Chinese stayed
        # inert for a SECOND reason — two Unicode-blind guards (the number
        # pattern's letter boundary, and the identifier exception in the content
        # filter) treated kana/kanji/Han as identifier context, so a digit
        # written flush against a character never became a value. Both are now
        # ASCII-scoped. The expected `rule` is asserted from INTENT in the source
        # fixture, not echoed from the detector, so a port cannot pass by
        # reproducing a bug.
        "non_latin": [
            {
                "domain": domain,
                "label": label,
                "left": left,
                "right": right,
                "conflict": rule is not None,
                "rule": rule,
            }
            for domain, label, left, right, rule in NON_LATIN
        ],
        "near_duplicates": [
            {
                "label": label,
                "left": left,
                "right": right,
                "collapses": is_near_duplicate(left, right) is not None,
            }
            for label, left, right, _ in DUPLICATE_CASES
        ],
        # The tokenization trap, with its own vector: a digit-LEADING token is a
        # measured value, a letter-leading token containing digits is an
        # IDENTIFIER and must stay in the content set.
        "identifier_tokenization": [
            {
                "left": "The p50 latency budget is 200 ms.",
                "right": "The p99 latency budget is 900 ms.",
                "conflict": detect_conflict(
                    "The p50 latency budget is 200 ms.", "The p99 latency budget is 900 ms."
                )
                is not None,
            },
            {
                "left": "The latency budget is 200 ms.",
                "right": "The latency budget is 900 ms.",
                "conflict": detect_conflict(
                    "The latency budget is 200 ms.", "The latency budget is 900 ms."
                )
                is not None,
            },
        ],
    }


def _segmentation_table() -> dict[str, Any]:
    from citenexus.answer.tables import ABBREVIATIONS, TERMINATORS

    return {
        "terminators": list(TERMINATORS),
        "abbreviations": sorted(ABBREVIATIONS),
    }


# --------------------------------------------------------------------------- #
# cases/faithful_v2.json — ADR-0009 ordered containment + polarity guard.
# The nine adversarial fixtures (each answer FALSE w.r.t. its passage) and the
# control set. Ports must reproduce every verdict exactly.
# --------------------------------------------------------------------------- #


def _faithful_v2_cases() -> dict[str, Any]:
    import sys

    # The fixtures live with the tests so they stay human-readable in one place;
    # this file is the generator, not a second copy of the data.
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from tests.answer.test_verify_v2 import ATTACKS, CONTROLS

    from citenexus.answer.verify import is_supported_v2

    return {
        "attacks": [
            {"name": n, "passage": p, "answer": a, "supported": is_supported_v2(a, p)}
            for n, p, a in ATTACKS
        ],
        "controls": [
            {"name": n, "passage": p, "answer": a, "supported": is_supported_v2(a, p)}
            for n, p, a in CONTROLS
        ],
    }


_SEGMENTATION_INPUTS = [
    "Art. 5 applies to all tenants.",
    "See Dr. Smith for details.",
    "J. Smith signed the agreement.",
    "The dose is 500.00 milligrams daily.",
    "The contractor maintains insurance. The term is five years.",
    "Is it approved? It is not.",
    "Really?! Yes.",
    "The window opens at 02:00 UTC",
    "\u5f93\u696d\u54e1\u306f\u958b\u793a\u3057\u3066\u306f\u306a\u3089\u306a\u3044\u3002\u671f\u9593\u306f\u4e94\u5e74\u3067\u3042\u308b\u3002",
    "The parties are (a) the tenant; (b) the landlord.",
    "france is in europe\nparis is the capital",
    "   ",
]


def _segmentation_cases() -> list[dict[str, Any]]:
    from citenexus.answer.segment import split_claims

    return [{"text": t, "claims": split_claims(t)} for t in _SEGMENTATION_INPUTS]


def generate() -> dict[str, str]:
    """All fixtures as {relative path under conformance/: rendered JSON text}."""
    return {
        "stopwords.json": _render(_stopwords()),
        "prompts.json": _render(_prompts()),
        "cases/tokenize.json": _render(_tokenize_cases()),
        "cases/bm25.json": _render(_bm25_cases()),
        "cases/rrf.json": _render(_rrf_cases()),
        "cases/faithful.json": _render(_faithful_cases()),
        "polarity.json": _render(_polarity_table()),
        "conflict.json": _render(_conflict_table()),
        "cases/conflict.json": _render(_conflict_cases()),
        "segmentation.json": _render(_segmentation_table()),
        "cases/faithful_v2.json": _render(_faithful_v2_cases()),
        "cases/segmentation.json": _render(_segmentation_cases()),
        "cases/chunker.json": _render(_chunker_cases()),
        "cases/language.json": _render(_language_cases()),
        "cases/eu_ids.json": _render(_eu_id_cases()),
        "cases/e2e_hermetic.json": _render(_e2e_hermetic_cases()),
        "cases/result_roundtrip.json": _render(_result_roundtrip_cases()),
        "cases/model_wire.json": _render(_model_wire_cases()),
        "cases/graph_comention.json": _render(_graph_comention_cases()),
        "cases/structure.json": _render(_structure_cases()),
        "cases/vision_orchestration.json": _render(_vision_orchestration_cases()),
        "cases/multilingual.json": _render(_multilingual_cases()),
        "cases/tokenize_v2.json": _render(_tokenize_v2_cases()),
        "cases/languages.json": _render(_language_code_cases()),
        "cases/vector_validation.json": _render(_vector_validation_cases()),
    }


# --------------------------------------------------------------------------- #
# cases/tokenize_v2.json — the Unicode tokenizer, PER SCRIPT (ADR-0011).
#
# The rule this file exists to enforce: **no script may be claimed as supported
# without a golden fixture.** `supported` below is generated from
# `SUPPORTED_SCRIPTS`, and every entry in it carries three assertions a port must
# reproduce — tokens are produced, a verbatim quote of the passage is accepted by
# the gate, and unrelated text is still rejected. Adding a script to
# SUPPORTED_SCRIPTS without adding it here fails `_tokenize_v2_cases`, which is
# the mechanism that makes the claim and the evidence for it the same artifact.
#
# `unsupported` pins the other half: scripts the tokenizer will process
# mechanically but that CiteNexus does not claim, which must be REPORTED rather
# than silently half-served.
# --------------------------------------------------------------------------- #

# One sentence of plausible evidence per claimed script.
_V2_SCRIPT_SAMPLES: dict[str, str] = {
    "arabic": "لا يجوز للموظف إفشاء المعلومات السرية.",
    "bengali": "কর্মচারী গোপনীয় তথ্য প্রকাশ করবেন না।",
    "cyrillic": "Работник не должен раскрывать конфиденциальную информацию.",
    "devanagari": "कर्मचारी गोपनीय जानकारी प्रकट नहीं करेगा।",
    "greek": "Ο εργαζόμενος δεν πρέπει να αποκαλύπτει εμπιστευτικές πληροφορίες.",
    "han": "员工不得披露机密信息。",
    "hangul": "직원은 기밀 정보를 공개해서는 안 된다.",
    "hebrew": "העובד לא יגלה מידע סודי.",
    "hiragana": "従業員は機密情報を開示してはならない。",
    "katakana": "コンフィデンシャルナジョウホウ",
    "latin": "The employee shall not disclose confidential information.",
    "tamil": "ஊழியர் ரகசியத் தகவலை வெளியிடக் கூடாது.",
    "telugu": "ఉద్యోగి రహస్య సమాచారాన్ని వెల్లడించకూడదు.",
    "thai": "พนักงานต้องไม่เปิดเผยข้อมูลที่เป็นความลับ",
}

# Scripts the range table can NAME but that carry no claim. A port must report
# these, not quietly bigram them and pretend. Telugu's Indic neighbours are here
# because NAMING a script is what stops the next one reading as a neighbour plus
# "unknown" — which is precisely how Telugu read as Devanagari.
_V2_UNCLAIMED_SAMPLES: dict[str, str] = {
    "armenian": "Աշխատողը չպետք է բացահայտի",
    "georgian": "თანამშრომელმა არ უნდა გაამჟღავნოს",
    "gujarati": "કર્મચારી ગોપનીય માહિતી જાહેર કરશે નહીં",
    "gurmukhi": "ਕਰਮਚਾਰੀ ਗੁਪਤ ਜਾਣਕਾਰੀ ਜ਼ਾਹਰ ਨਹੀਂ ਕਰੇਗਾ",
    "kannada": "ಉದ್ಯೋಗಿ ಗೌಪ್ಯ ಮಾಹಿತಿಯನ್ನು ಬಹಿರಂಗಪಡಿಸಬಾರದು",
    "khmer": "បុគ្គលិកមិនត្រូវបង្ហាញព័ត៌មានសម្ងាត់",
    "lao": "ພະນັກງານບໍ່ຄວນເປີດເຜີຍຂໍ້ມູນລັບ",
    "malayalam": "ജീവനക്കാരൻ രഹസ്യ വിവരങ്ങൾ വെളിപ്പെടുത്തരുത്",
    "myanmar": "ဝန်ထမ်းသည် လျှို့ဝှက်ချက်ကို မဖော်ထုတ်ရ",
    "oriya": "କର୍ମଚାରୀ ଗୋପନୀୟ ସୂଚନା ପ୍ରକାଶ କରିବେ ନାହିଁ",
    "sinhala": "සේවකයා රහස්‍ය තොරතුරු හෙළි නොකළ යුතුය",
}

# The Unicode mechanics that differ from v1, plus the ASCII inputs that must NOT.
# The ASCII half is why moving BM25, the structure retriever and the gate onto v2
# left every pinned ASCII vector unchanged.
_V2_UNICODE_INPUTS: list[str] = [
    *_TOKENIZE_INPUTS,  # every v1 vector, re-pinned under v2
    "Café Münster naïve résumé",
    "Straße",
    "STRASSE",
    "ＡＢＣ１２３",  # NFKC fullwidth -> ASCII
    "İstanbul",  # Turkish dotted capital I
    _nfc("Déjà"),
    _nfd("Déjà"),
    "東京tokyo",  # script boundary inside a word run
    "日本語。中国",  # punctuation separates two Han runs
    "従業員は",  # Han/Hiragana boundary: bigrams do not cross it
    "木",  # single-character continuous run
    "직원은 기밀 정보를",  # Hangul is space-delimited, NOT bigrammed
    "ఉద్యోగి రహస్య సమాచారాన్ని",  # Telugu is space-delimited too
    # A script ABSENT from the range table produces NO tokens: there is no
    # validated segmentation rule for it, and answering through an unvalidated
    # one is worse than refusing (ADR-0011). Telugu was absent and still emitted
    # six delimited tokens, so BM25 ranked a script no fixture had validated.
    "የሰራተኛው ሚስጥራዊ መረጃ",  # Ethiopic — unknown, so []
    "ᏗᏙᎳᏅᏍᏗ ᎠᏓᏅᏙ",  # Cherokee — unknown, so []
    "የሰራተኛው 2026 policy",  # only the unknown RUN is dropped
]

_V2_UNRELATED = "Employees are entitled to thirty days of annual leave."


def _tokenize_v2_cases() -> dict[str, Any]:
    missing = SUPPORTED_SCRIPTS - set(_V2_SCRIPT_SAMPLES)
    if missing:  # the golden-fixture-per-script rule, enforced mechanically
        raise AssertionError(f"claimed scripts with no golden fixture: {sorted(missing)}")
    extra = set(_V2_SCRIPT_SAMPLES) - SUPPORTED_SCRIPTS
    if extra:
        raise AssertionError(f"fixture for unclaimed script: {sorted(extra)}")

    supported = []
    for script in sorted(_V2_SCRIPT_SAMPLES):
        text = _V2_SCRIPT_SAMPLES[script]
        supported.append(
            {
                "script": script,
                "text": text,
                "tokens": tokenize_v2(text),
                "v1_tokens": tokenize(text),  # the defect, pinned for contrast
                "self_supported": is_supported_v2(text, text),
                "unrelated_supported": is_supported_v2(text, _V2_UNRELATED),
                "unsupported_scripts": list(unsupported_scripts(text)),
            }
        )
    unclaimed = [
        {
            "script": script,
            "text": text,
            "unsupported_scripts": list(unsupported_scripts(text)),
        }
        for script, text in sorted(_V2_UNCLAIMED_SAMPLES.items())
    ]
    return {
        "tokenizer_version": TOKENIZER_VERSION,
        "supported_scripts": sorted(SUPPORTED_SCRIPTS),
        "continuous_scripts": sorted(CONTINUOUS_SCRIPTS),
        "unrelated_passage": _V2_UNRELATED,
        "supported": supported,
        "unclaimed": unclaimed,
        "unicode": [{"input": text, "tokens": tokenize_v2(text)} for text in _V2_UNICODE_INPUTS],
    }


# --------------------------------------------------------------------------- #
# cases/languages.json — the NAMED code sets (change: language-enums).
#
# Python's `Language` / `Script`, Go's `lang.Language` / `lang.Script` and JS's
# `Language` / `Script` const objects each assert themselves against this file,
# so the 41 codes cannot diverge across ports by review error. Exactly the pin
# `cases/tokenize_v2.json` already gives the script CLAIM — this one covers the
# whole naming vocabulary, including the languages we deliberately REFUSE.
#
# `supported` is derived, never hand-listed: it is `SearchLanguage.is_supported`,
# i.e. every script the language needs is in ADR-0011's fixture-backed claim.
# --------------------------------------------------------------------------- #


def _language_code_cases() -> dict[str, Any]:
    languages = [
        {
            "code": str(entry.code),
            "name": entry.name,
            "scripts": [str(s) for s in entry.scripts],
            "supported": entry.is_supported,
        }
        for entry in SEARCH_LANGUAGES.values()
    ]
    codes = {row["code"] for row in languages}
    members = {m.value for m in Language} - {str(AUTO_ANSWER_LANGUAGE)}
    if codes != members:  # one definition, mechanically enforced
        raise AssertionError(f"Language members diverged from SEARCH_LANGUAGES: {codes ^ members}")
    named = {s for row in languages for s in row["scripts"]}
    if not named <= {m.value for m in Script}:
        raise AssertionError(f"search table names a script Script does not: {named}")
    return {
        # The one value of answer_language that is NOT a language, and is
        # deliberately absent from the table below.
        "auto_sentinel": str(AUTO_ANSWER_LANGUAGE),
        "scripts": sorted(m.value for m in Script),
        "supported_scripts": sorted(SUPPORTED_SCRIPTS),
        "continuous_scripts": sorted(CONTINUOUS_SCRIPTS),
        # Caller order preserved: the table is read top-to-bottom by every port.
        "languages": languages,
    }


def main() -> None:
    base = _REPO_ROOT.parent / "conformance"
    for rel_path, text in generate().items():
        path = base / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(_REPO_ROOT.parent)}")


# --------------------------------------------------------------------------- #
# cases/vector_validation.json — what a VALID EMBEDDING BATCH is (ADR-0010 t1).
#
# The contract every port enforces before a vector may be indexed or scored. It
# exists because the three ports disagreed: Python validated NOTHING (a provider
# returning fewer vectors than texts shifted every text->vector pairing and
# silently corrupted the index), Go rejected empty/dimension/zero, and JS
# rejected those PLUS non-finite — so two ports pinned "byte-for-byte identical"
# did not agree on what a valid vector is.
#
# `expect` is the CONTRACT: ports read it, they must never re-derive it by
# calling the code under test. Re-derivation is exactly how this class of bug
# survived — a test that asks the implementation what it does can only ever agree
# with it.
#
# The REJECTION ORDER is pinned, not incidental. Several cases below fail more
# than one rule at once (`dimension-beats-non-finite`, `non-finite-beats-zero`,
# `empty-beats-dimension`), and they are the cases that catch a port that has all
# five rules but applies them in a different sequence — which reports a different
# error for the same vector, so a caller cannot act on the message.
#
# NUMBER ENCODING: JSON has no NaN/Infinity literal, so a non-finite component is
# written as one of the strings "NaN" / "Infinity" / "-Infinity". Every port
# decodes those three tokens and nothing else. The `non_vector` bucket is
# deliberately exempt — it carries RAW JSON that is not a numeric array at all,
# so no decoding is applied to it and no case in it uses those tokens.
# --------------------------------------------------------------------------- #

#: The rejection reasons, in the order they are applied. A port must both reject
#: the same vectors AND report the same reason.
_VECTOR_REASONS = ["non_vector", "empty", "dimension", "non_finite", "zero"]

_NAN = "NaN"
_INF = "Infinity"
_NEG_INF = "-Infinity"

#: (name, vector, dim, valid, reason) over numeric vectors — every port.
_VECTOR_CHECK_CASES: list[tuple[str, list[Any], int, bool, str | None]] = [
    # --- accepted -----------------------------------------------------------
    ("ok-first-vector-defines-dim", [0.1, 0.2, 0.3], 0, True, None),
    ("ok-dim-matches-run", [0.1, 0.2, 0.3], 3, True, None),
    ("ok-single-component", [1.0], 0, True, None),
    ("ok-single-component-dim-1", [1.0], 1, True, None),
    ("ok-negative-components", [-1.0, -2.0], 2, True, None),
    ("ok-mixed-sign", [-1.0, 0.0, 1.0], 3, True, None),
    ("ok-one-tiny-signal-among-zeros", [0.0, 0.0, 0.0, 1e-09], 4, True, None),
    ("ok-large-magnitude", [1e300, -1e300], 2, True, None),
    ("ok-high-dimension", [0.0] * 1023 + [1.0], 1024, True, None),
    # --- empty --------------------------------------------------------------
    ("empty-vector-dim-undefined", [], 0, False, "empty"),
    # Order: empty is reported as EMPTY, never as a 0-vs-3 dimension mismatch.
    ("empty-beats-dimension", [], 3, False, "empty"),
    # --- dimension ----------------------------------------------------------
    ("dim-too-short", [1.0, 2.0], 3, False, "dimension"),
    ("dim-too-long", [1.0, 2.0, 3.0, 4.0], 3, False, "dimension"),
    ("dim-off-by-one-long", [1.0, 2.0], 1, False, "dimension"),
    # Order: a ragged vector is reported by its dimension, not by its contents.
    ("dimension-beats-non-finite", [_NAN, 1.0], 3, False, "dimension"),
    ("dimension-beats-zero", [0.0, 0.0], 3, False, "dimension"),
    # --- non-finite ---------------------------------------------------------
    ("nan-first-component", [_NAN, 1.0, 2.0], 3, False, "non_finite"),
    ("nan-last-component", [1.0, 2.0, _NAN], 3, False, "non_finite"),
    ("nan-only-component", [_NAN], 0, False, "non_finite"),
    ("positive-infinity", [_INF, 1.0, 2.0], 3, False, "non_finite"),
    ("negative-infinity", [1.0, _NEG_INF, 2.0], 3, False, "non_finite"),
    ("all-non-finite", [_NAN, _INF, _NEG_INF], 3, False, "non_finite"),
    # Order: NaN among zeros is NON-FINITE, not zero — the components are not
    # all zero, so the zero rule does not even apply, but a port that tested
    # "any non-zero component" instead of "all zero" would report it as zero.
    ("non-finite-beats-zero", [0.0, 0.0, _NAN], 3, False, "non_finite"),
    # --- zero ---------------------------------------------------------------
    ("all-zeros-dim-undefined", [0.0, 0.0, 0.0], 0, False, "zero"),
    ("all-zeros-dim-matches", [0.0, 0.0, 0.0], 3, False, "zero"),
    # The exact shape of ingest/pipeline.py's _PLACEHOLDER_VECTOR. Written by the
    # library itself when no embedder is configured, and never scored — but a
    # PROVIDER handing this back is claiming it embedded the text.
    ("all-zeros-single-component", [0.0], 0, False, "zero"),
    # -0.0 == 0.0 in IEEE-754, so a vector of negative zeros carries no signal
    # either. A port comparing bit patterns rather than values gets this wrong.
    ("negative-zeros", [-0.0, -0.0], 0, False, "zero"),
    ("mixed-signed-zeros", [0.0, -0.0, 0.0], 3, False, "zero"),
    ("all-zeros-high-dimension", [0.0] * 64, 64, False, "zero"),
]

#: Payloads that are not numeric arrays at all. Python and JS both accept `any`
#: from an untyped provider and must refuse; Go's []float64 makes these
#: unrepresentable, so its replay asserts the bucket's shape and documents why it
#: cannot execute the cases. RAW JSON — the NaN/Infinity string encoding used by
#: `check_vector` does NOT apply here.
_VECTOR_NON_VECTOR_CASES: list[tuple[str, Any, int]] = [
    ("null", None, 0),
    ("string", "0.1,0.2", 0),
    ("bare-number", 1.0, 0),
    ("object", {"0": 1.0}, 0),
    ("object-embedding-envelope", {"embedding": [1.0, 2.0]}, 0),
    ("array-of-strings", ["1.0", "2.0"], 0),
    ("array-with-null", [1.0, None], 0),
    ("array-with-string", [1.0, "2.0"], 0),
    ("nested-array", [[1.0, 2.0]], 0),
    ("array-of-booleans", [True, False], 0),
]

#: (name, texts, vectors, valid, reason) for the batch-arity contract — the rule
#: whose absence in Python silently mis-paired a real corpus.
_VECTOR_ARITY_CASES: list[tuple[str, int, int, bool, str | None]] = [
    ("ok-one-for-one", 1, 1, True, None),
    ("ok-many-for-many", 5, 5, True, None),
    ("ok-empty-batch", 0, 0, True, None),
    ("ok-large-batch", 64, 64, True, None),
    ("short-by-one", 3, 2, False, "cardinality"),
    ("short-by-many", 64, 1, False, "cardinality"),
    ("short-to-empty", 2, 0, False, "cardinality"),
    ("long-by-one", 2, 3, False, "cardinality"),
    ("long-by-many", 1, 4, False, "cardinality"),
]


def _encode_vector_component(value: Any) -> Any:
    """Numbers stay numbers; NaN/±Inf become their pinned string tokens."""
    if isinstance(value, str):
        return value
    return float(value)


def _vector_validation_cases() -> dict[str, Any]:
    """The cross-port contract for "a valid embedding batch"."""
    return {
        "reason_order": list(_VECTOR_REASONS),
        "non_finite_tokens": [_NAN, _INF, _NEG_INF],
        "check_vector": [
            {
                "name": name,
                "vector": [_encode_vector_component(v) for v in vector],
                "dim": dim,
                "valid": valid,
                "reason": reason,
            }
            for name, vector, dim, valid, reason in _VECTOR_CHECK_CASES
        ],
        "non_vector": [
            {"name": name, "vector": payload, "dim": dim, "valid": False,
             "reason": "non_vector"}
            for name, payload, dim in _VECTOR_NON_VECTOR_CASES
        ],
        "batch_arity": [
            {
                "name": name,
                "texts": texts,
                "vectors": vectors,
                "valid": valid,
                "reason": reason,
            }
            for name, texts, vectors, valid, reason in _VECTOR_ARITY_CASES
        ],
    }


if __name__ == "__main__":
    main()
