"""TrustRAG runnable example — ingest → ask → evaluate over real endpoints.

Wires the real OpenAI-compatible plugins (embedding, answering LLM, reranker)
from environment variables. The default stack is cheap + hosted, so it runs with
no local GPU and no containers:

- **Storage**  LocalFs (a folder). Point ``TRUSTRAG_S3_ENDPOINT_URL`` at MinIO
  or Cloudflare R2 to exercise the real S3 path instead.
- **Embedding + reranker**  Jina (``/v1/embeddings`` + ``/rerank``, one key).
- **Answering LLM**  Gemini's OpenAI-compatible endpoint (temperature 0).

This is the README quickstart and the single opt-in integration proof:
everything the library promises, end to end, on a tiny multilingual corpus.

Config + secrets come from the vsync vault (``infra/vault/dev/.env.dev``), which
``task local:example`` loads. Secrets are referenced by env-var *name* only and
never read or printed here.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

from trustrag import TrustRAG
from trustrag.answer.result import Result
from trustrag.config.schema import (
    EmbeddingConfig,
    LLMConfig,
    MultilingualConfig,
    RerankerConfig,
    StorageConfig,
    TrustRAGConfig,
)
from trustrag.config.signals import Signal
from trustrag.storage.lance_store import StorageOptions

_HERE = Path(__file__).resolve().parent
_CORPUS = _HERE / "corpus"
_GOLDEN = _HERE / "golden.csv"


def _bool_env(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes"}


def _config() -> TrustRAGConfig:
    """Build the typed config from the vault's env values.

    ``storage.bucket`` doubles as the base URI: a plain path selects LocalFs; an
    ``s3://bucket`` value (with ``TRUSTRAG_S3_ENDPOINT_URL``) selects S3/MinIO/R2.
    """
    base_uri = os.environ.get("TRUSTRAG_BASE_URI", "./.trustrag-data")
    return TrustRAGConfig(
        storage=StorageConfig(
            bucket=base_uri,
            endpoint_url=os.environ.get("TRUSTRAG_S3_ENDPOINT_URL"),
        ),
        embedding=EmbeddingConfig(
            endpoint=os.environ.get("TRUSTRAG_EMBED_BASE_URL", "https://api.jina.ai/v1"),
            model=os.environ.get("TRUSTRAG_EMBED_MODEL", "jina-embeddings-v3"),
            api_key_env="TRUSTRAG_EMBED_API_KEY",
        ),
        llm=LLMConfig(
            endpoint=os.environ.get(
                "TRUSTRAG_LLM_BASE_URL",
                "https://generativelanguage.googleapis.com/v1beta/openai",
            ),
            model=os.environ.get("TRUSTRAG_LLM_MODEL", "gemini-2.5-flash"),
            api_key_env="TRUSTRAG_LLM_API_KEY",
            temperature=0.0,  # grounded answers are deterministic (§4b)
        ),
        reranker=RerankerConfig(
            enabled=_bool_env("TRUSTRAG_RERANK_ENABLED", True),
            endpoint=os.environ.get("TRUSTRAG_RERANK_BASE_URL", "https://api.jina.ai/v1"),
            model=os.environ.get(
                "TRUSTRAG_RERANK_MODEL", "jina-reranker-v2-base-multilingual"
            ),
            api_key_env="TRUSTRAG_RERANK_API_KEY",
        ),
        multilingual=MultilingualConfig(fallback_language="en"),
        # Fast-path signals for the example: dense vectors + lexical.
        signals=(Signal.embedding, Signal.text),
    )


def _storage_options() -> StorageOptions | None:
    """LanceDB-over-S3 options so the vector store talks to MinIO/R2 too.

    ``None`` when no S3 endpoint is set — LocalFs needs no options.
    """
    endpoint = os.environ.get("TRUSTRAG_S3_ENDPOINT_URL")
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
    config = _config()
    rag = TrustRAG.from_config(config, storage_options=_storage_options())

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
