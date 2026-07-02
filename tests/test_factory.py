"""``TrustRAG.from_config`` — wire real OpenAI-compatible plugins from config.

The factory is the one place that turns a typed ``TrustRAGConfig`` (endpoints,
models, temperature, signals) into a ready ``TrustRAG`` client with the real
embedding / generator / reranker plugins. Transports are injected so this stays
hermetic: no network, no models.
"""

from __future__ import annotations

import json
from pathlib import Path

from trustrag.answer.result import Decision
from trustrag.client import TrustRAG
from trustrag.config.schema import (
    EmbeddingConfig,
    LLMConfig,
    LLMProvider,
    RerankerConfig,
    StorageConfig,
    TrustRAGConfig,
)
from trustrag.config.signals import Signal
from trustrag.lang.detect import HeuristicDetector


def _embed_transport(url: str, body: bytes, headers: dict[str, str]) -> bytes:
    """Deterministic dense vectors keyed by shared tokens (so retrieval works)."""
    payload = json.loads(body)
    vocab = ["employee", "disclose", "confidential", "termination", "notice"]
    data = []
    for text in payload["input"]:
        low = text.lower()
        vec = [1.0 if term in low else 0.0 for term in vocab]
        if not any(vec):
            vec = [0.01] * len(vocab)
        data.append({"embedding": vec})
    return json.dumps({"data": data}).encode("utf-8")


def _llm_transport(url: str, body: bytes, headers: dict[str, str]) -> bytes:
    """Extractive fake: echo the passage so the faithfulness gate passes."""
    payload = json.loads(body)
    user = payload["messages"][-1]["content"]
    passage = user.split("Passage:\n", 1)[1].split("\n\nQuestion:", 1)[0]
    return json.dumps({"choices": [{"message": {"content": passage}}]}).encode("utf-8")


def _config(bucket_path: Path) -> TrustRAGConfig:
    return TrustRAGConfig(
        storage=StorageConfig(bucket=str(bucket_path)),
        llm=LLMConfig(endpoint="http://llm.test/v1", model="qwen2.5"),
        embedding=EmbeddingConfig(endpoint="http://embed.test/v1", model="bge-m3"),
        reranker=RerankerConfig(enabled=False),
        signals=(Signal.embedding, Signal.text),
    )


def _rag(tmp_path: Path) -> TrustRAG:
    return TrustRAG.from_config(
        _config(tmp_path),
        detector=HeuristicDetector(),
        embed_transport=_embed_transport,
        llm_transport=_llm_transport,
    )


def test_from_config_builds_working_client(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(
        text="The employee shall not disclose confidential information.",
        document_id="nda",
    )
    result = rag.ask("Can the employee disclose confidential information?")
    assert result.evidence.decision is Decision.answered
    assert result.sources[0].document == "nda"
    assert result.claims[0].supported


def test_from_config_abstains_when_irrelevant(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    rag.ingest(text="Termination requires thirty days notice.", document_id="c")
    result = rag.ask("What is the capital of France?")
    assert result.evidence.decision is Decision.refused


def test_from_config_honours_temperature(tmp_path: Path) -> None:
    captured: list[dict[str, object]] = []

    def capturing_llm(url: str, body: bytes, headers: dict[str, str]) -> bytes:
        captured.append(json.loads(body))
        return _llm_transport(url, body, headers)

    cfg = _config(tmp_path).model_copy(
        update={"llm": LLMConfig(endpoint="http://llm.test/v1", temperature=0.0)}
    )
    rag = TrustRAG.from_config(
        cfg,
        detector=HeuristicDetector(),
        embed_transport=_embed_transport,
        llm_transport=capturing_llm,
    )
    rag.ingest(text="The employee shall not disclose secrets.", document_id="nda")
    rag.ask("Can the employee disclose secrets?")
    assert captured
    assert captured[-1]["temperature"] == 0.0


def _anthropic_transport(url: str, body: bytes, headers: dict[str, str]) -> bytes:
    """Extractive Anthropic-shaped fake: echo the passage from the user turn."""
    payload = json.loads(body)
    user = payload["messages"][-1]["content"]
    passage = user.split("Passage:\n", 1)[1].split("\n\nQuestion:", 1)[0]
    return json.dumps({"content": [{"type": "text", "text": passage}]}).encode("utf-8")


def test_from_config_builds_vision_client_when_enabled(tmp_path: Path) -> None:
    from trustrag.config.schema import VisionConfig

    cfg = _config(tmp_path).model_copy(
        update={
            "vision": VisionConfig(
                enabled=True, endpoint="http://vl.test/v1", model="gemini-2.5-flash"
            )
        }
    )
    rag = TrustRAG.from_config(
        cfg,
        detector=HeuristicDetector(),
        embed_transport=_embed_transport,
        llm_transport=_llm_transport,
    )
    # A vision plugin was wired into the ingest pipeline.
    assert rag._ingest._vision is not None


def test_from_config_no_vision_when_disabled(tmp_path: Path) -> None:
    rag = TrustRAG.from_config(
        _config(tmp_path),
        detector=HeuristicDetector(),
        embed_transport=_embed_transport,
        llm_transport=_llm_transport,
    )
    assert rag._ingest._vision is None


def test_from_config_builds_reformulator_when_enabled(tmp_path: Path) -> None:
    from trustrag.config.schema import ReformulationConfig

    cfg = _config(tmp_path).model_copy(
        update={"reformulation": ReformulationConfig(enabled=True, endpoint="http://small.test/v1")}
    )
    rag = TrustRAG.from_config(
        cfg,
        detector=HeuristicDetector(),
        embed_transport=_embed_transport,
        llm_transport=_llm_transport,
    )
    assert rag._reformulator is not None


def test_from_config_no_reformulator_by_default(tmp_path: Path) -> None:
    rag = _rag(tmp_path)
    assert rag._reformulator is None


def test_from_config_anthropic_provider(tmp_path: Path) -> None:
    cfg = _config(tmp_path).model_copy(
        update={
            "llm": LLMConfig(
                provider=LLMProvider.anthropic,
                endpoint="https://api.anthropic.test",
                model="claude-opus-4-8",
            )
        }
    )
    rag = TrustRAG.from_config(
        cfg,
        detector=HeuristicDetector(),
        embed_transport=_embed_transport,
        llm_transport=_anthropic_transport,
    )
    rag.ingest(
        text="The employee shall not disclose confidential information.",
        document_id="nda",
    )
    result = rag.ask("Can the employee disclose confidential information?")
    assert result.evidence.decision is Decision.answered
    assert result.claims[0].supported
