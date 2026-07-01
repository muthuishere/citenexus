"""Config loader: dict / YAML / env with defined precedence (spec §17)."""

from pathlib import Path

from trustrag.config.loader import from_config
from trustrag.config.schema import LexicalSignal
from trustrag.domain.trust import TrustMode

SECTION17_YAML = """
storage:
  bucket: s3://my-bucket
  partition_hierarchy: [org, product_line, product]
llm:
  model: qwen2.5
  endpoint: http://localhost:11434/v1
embedding:
  model: bge-m3
reranker:
  model: bge-reranker-v2-m3
vision:
  enabled: true
  prefilter:
    enabled: true
vector_store:
  backend: lancedb
graph:
  enabled: true
  community_algorithm: leiden
retrieval:
  rrf_k: 60
  top_k: 11
  lexical_signal: bge_m3_sparse
trust:
  default_mode: strict
multilingual:
  detector: fasttext-lid176
  detect_confidence_threshold: 0.5
  answer_in_query_language: true
access_control:
  enabled: false
provenance:
  enabled: true
worker:
  max_retries: 3
telemetry:
  enabled: true
memory:
  enabled: false
judge:
  enabled: false
streaming:
  enabled: false
signals: [embedding, text]
"""


def test_from_dict() -> None:
    config = from_config({"storage": {"bucket": "s3://b"}}, env={})
    assert config.storage.bucket == "s3://b"
    assert config.trust.default_mode is TrustMode.strict


def test_from_yaml_string() -> None:
    config = from_config(SECTION17_YAML, env={})
    assert config.storage.bucket == "s3://my-bucket"
    assert config.storage.partition_hierarchy == ("org", "product_line", "product")
    assert config.retrieval.lexical_signal is LexicalSignal.bge_m3_sparse


def test_from_yaml_path(tmp_path: Path) -> None:
    path = tmp_path / "trustrag.yaml"
    path.write_text(SECTION17_YAML, encoding="utf-8")
    config = from_config(path, env={})
    assert config.storage.bucket == "s3://my-bucket"
    assert config.graph.community_algorithm == "leiden"


def test_environment_override_wins_over_file(tmp_path: Path) -> None:
    path = tmp_path / "trustrag.yaml"
    path.write_text(
        "storage:\n  bucket: s3://b\ntrust:\n  default_mode: normal\n",
        encoding="utf-8",
    )
    config = from_config(path, env={"TRUSTRAG_TRUST__DEFAULT_MODE": "strict"})
    assert config.trust.default_mode is TrustMode.strict


def test_dict_override_wins_over_yaml() -> None:
    config = from_config(
        SECTION17_YAML,
        overrides={"trust": {"default_mode": "normal"}},
        env={},
    )
    assert config.trust.default_mode is TrustMode.normal


def test_precedence_env_beats_dict_beats_yaml(tmp_path: Path) -> None:
    path = tmp_path / "trustrag.yaml"
    path.write_text("storage:\n  bucket: s3://b\nretrieval:\n  top_k: 5\n", encoding="utf-8")
    # yaml says 5, dict override says 7, env says 9 -> env wins
    config = from_config(
        path,
        overrides={"retrieval": {"top_k": 7}},
        env={"TRUSTRAG_RETRIEVAL__TOP_K": "9"},
    )
    assert config.retrieval.top_k == 9
