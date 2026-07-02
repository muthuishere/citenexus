"""CiteNexus runnable example — ingest → ask → evaluate over real endpoints.

THE APPLICATION OWNS ITS ENVIRONMENT: this file reads os.environ and builds
typed endpoints; the library never touches env vars. Default stack is cheap +
hosted (Jina embeddings/rerank + Gemini LLMs + LocalFs storage) — no GPU, no
containers. Secrets come from the vsync vault (infra/vault/dev/.env.dev),
loaded by `task local:example`.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

from citenexus import CiteNexus, GeminiHttpEndpoint, OpenAIHttpEndpoint
from citenexus.answer.result import Result
from citenexus.config.schema import (
    CiteNexusConfig,
    ContextModelConfig,
    EmbeddingConfig,
    LLMConfig,
    MultilingualConfig,
    ReformulationConfig,
    RerankerConfig,
    StorageConfig,
)
from citenexus.config.signals import Signal
from citenexus.storage.lance_store import StorageOptions

_HERE = Path(__file__).resolve().parent
_CORPUS = _HERE / "corpus"
_GOLDEN = _HERE / "golden.csv"


def _bool_env(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes"}


def _config() -> CiteNexusConfig:
    """Typed endpoints, declared once and reused — keys read HERE, by the app."""
    jina = OpenAIHttpEndpoint(
        base_url=os.environ.get("CITENEXUS_EMBED_BASE_URL", "https://api.jina.ai/v1"),
        api_key=os.environ.get("CITENEXUS_EMBED_API_KEY"),
    )
    gemini = GeminiHttpEndpoint(api_key=os.environ.get("CITENEXUS_LLM_API_KEY"))

    base_uri = os.environ.get("CITENEXUS_BASE_URI", "./.citenexus-data")
    return CiteNexusConfig(
        storage=StorageConfig(
            bucket=base_uri,
            endpoint_url=os.environ.get("CITENEXUS_S3_ENDPOINT_URL"),
        ),
        embedding=EmbeddingConfig(
            endpoint=jina,
            model=os.environ.get("CITENEXUS_EMBED_MODEL", "jina-embeddings-v3"),
        ),
        llm=LLMConfig(
            endpoint=gemini,
            model=os.environ.get("CITENEXUS_LLM_MODEL", "gemini-2.5-flash"),
            temperature=0.0,  # grounded answers are deterministic (§4b)
        ),
        reranker=RerankerConfig(
            enabled=_bool_env("CITENEXUS_RERANK_ENABLED", True),
            endpoint=jina,  # same Jina connection serves embeddings AND rerank
            model=os.environ.get("CITENEXUS_RERANK_MODEL", "jina-reranker-v2-base-multilingual"),
        ),
        # Contextual retrieval: a small model situates each chunk before
        # embedding/BM25; the citation passage stays verbatim.
        context_model=ContextModelConfig(
            enabled=_bool_env("CITENEXUS_CONTEXT_ENABLED", True),
            endpoint=gemini,  # the SAME gemini connection, smaller model
            model=os.environ.get("CITENEXUS_CONTEXT_MODEL", "gemini-2.5-flash-lite"),
        ),
        # EN dual-query RRF — the cross-lingual abstention fix.
        reformulation=ReformulationConfig(
            enabled=_bool_env("CITENEXUS_REFORMULATE_ENABLED", True),
            endpoint=gemini,
            model=os.environ.get("CITENEXUS_REFORMULATE_MODEL", "gemini-2.5-flash-lite"),
        ),
        multilingual=MultilingualConfig(fallback_language="en"),
        signals=(Signal.embedding, Signal.text),
    )


def _storage_options() -> StorageOptions | None:
    endpoint = os.environ.get("CITENEXUS_S3_ENDPOINT_URL")
    if not endpoint:
        return None
    return {
        "endpoint": endpoint,
        "allow_http": "true",
        "access_key_id": os.environ.get("AWS_ACCESS_KEY_ID", "minioadmin"),
        "secret_access_key": os.environ.get("AWS_SECRET_ACCESS_KEY", "minioadmin"),
        "region": os.environ.get("AWS_REGION", "us-east-1"),
    }


def _print_answer(question: str, result: Result) -> None:
    print(f"\nQ: {question}")
    print(f"   decision : {result.evidence.decision.value}  ({result.answer_language})")
    print(f"   answer   : {result.answer}")
    for source in result.sources:
        page = "" if source.page is None else f" p.{source.page}"
        print(f"   source   : {source.document}{page} [{source.passage_language}]")


def main() -> None:
    rag = CiteNexus.from_config(_config(), storage_options=_storage_options())

    print("== Ingest ==")
    for path in sorted(_CORPUS.glob("*.txt")):
        result = rag.ingest(path, document_id=path.stem)
        print(f"   {path.name:16} -> {result.status}")

    print("\n== Ask ==")
    with _GOLDEN.open(newline="", encoding="utf-8") as handle:
        questions = [row["question"] for row in csv.DictReader(handle)]
    for question in questions:
        _print_answer(question, rag.ask(question))

    print("\n== Evaluate ==")
    report = rag.evaluate(_GOLDEN)
    print(f"   total            : {report.total}")
    print(f"   answered/refused : {report.answered}/{report.refused}")
    print(f"   groundedness     : {report.groundedness_rate:.0%}")
    print(f"   citation rate    : {report.citation_rate:.0%}")
    print(f"   expected support : {report.expected_support_rate:.0%}")


if __name__ == "__main__":
    main()
