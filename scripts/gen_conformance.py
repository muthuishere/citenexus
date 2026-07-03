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
from citenexus.answer.result import (
    Claim,
    Decision,
    EvidenceSignals,
    ProvenanceEntry,
    Result,
    SourceRef,
)
from citenexus.answer.verify import (
    _STOPWORDS,
    content_tokens,
    has_relevance_overlap,
    is_supported,
)
from citenexus.answer.anthropic import AnthropicGenerator
from citenexus.answer.generator import OpenAICompatibleGenerator
from citenexus.domain.trust import TrustMode
from citenexus.embed.client import OpenAICompatibleEmbedding
from citenexus.testing.fakes import FakeEmbedding, FakeLLM
from citenexus.domain.partition import PartitionPath
from citenexus.evidence.builder import build_evidence_units
from citenexus.evidence.chunked_builder import build_chunked_units
from citenexus.evidence.chunker import chunk_text
from citenexus.evidence.contextualize import _PROMPT as _CONTEXTUALIZE_PROMPT
from citenexus.extract.types import BlockKind, ExtractedBlock, ExtractedDoc, SourceType
from citenexus.graph.distill import _PROMPT as _GRAPH_DISTILL_PROMPT
from citenexus.lang.detect import LanguageResult
from citenexus.lang.fallback import resolve_answer_language
from citenexus.retrieve.fusion import rrf_fuse
from citenexus.retrieve.reformulate import _PROMPT as _REFORMULATE_PROMPT
from citenexus.retrieve.types import Candidate, RetrievalSignal
from citenexus.storage.bm25 import Bm25TextSearch
from citenexus.testing.fakes import tokenize
from citenexus.vision.client import _VISION_PROMPT
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
    grounding (relevance gate), the extractive FakeLLM, and is_supported (the
    faithfulness gate). Vectors are L2-normalized, so cosine == dot product.
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
        return {"decision": Decision.refused.value, "answer": _REFUSAL,
                "document": None, "passage": None, "eu_id": None}
    top = grounded[0]
    passage = str(top["text"])
    answer = llm.answer(question, passage)
    if not is_supported(answer, passage):
        return {"decision": Decision.refused.value, "answer": _REFUSAL,
                "document": None, "passage": None, "eu_id": None}
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
            "inputs": {"question": _WIRE_QUESTION, "passage": _WIRE_PASSAGE, "answer_language": "en"},
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
            "config": {"base_url": "https://api.example.com/v1", "model": "qwen2.5", "max_tokens": 256},
            "inputs": {"question": _WIRE_QUESTION, "passage": _WIRE_PASSAGE, "answer_language": "de"},
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
            "inputs": {"question": _WIRE_QUESTION, "passage": _WIRE_PASSAGE, "answer_language": "en"},
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
    chat_body = {"choices": [{"message": {"content": _WIRE_ANSWER}}], "usage": {"prompt_tokens": 12, "completion_tokens": 8}}
    chat_out = OpenAICompatibleGenerator(
        base_url="https://x", model="m", transport=lambda _u, _b, _h: json.dumps(chat_body).encode()
    ).answer(_WIRE_QUESTION, _WIRE_PASSAGE, "en")
    responses.append({"name": "openai chat parse", "client": "openai_chat", "response_body": chat_body, "expected": chat_out})

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
    responses.append({"name": "anthropic parse multi-block text-only", "client": "anthropic", "response_body": anth_body, "expected": anth_out})

    # Embeddings: data[].embedding as float vectors, input order preserved.
    emb_body = {"data": [{"embedding": [0.1, 0.2, 0.3]}, {"embedding": [0.4, 0.5, 0.6]}]}
    emb_out = OpenAICompatibleEmbedding(
        base_url="https://x", model="m", transport=lambda _u, _b, _h: json.dumps(emb_body).encode()
    ).embed(["a", "b"])
    responses.append({"name": "openai embeddings parse", "client": "openai_embed", "response_body": emb_body, "expected": emb_out})
    return responses


def _model_wire_cases() -> dict[str, Any]:
    return {"requests": _wire_requests(), "responses": _wire_responses()}


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
        "cases/e2e_hermetic.json": _render(_e2e_hermetic_cases()),
        "cases/result_roundtrip.json": _render(_result_roundtrip_cases()),
        "cases/model_wire.json": _render(_model_wire_cases()),
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
