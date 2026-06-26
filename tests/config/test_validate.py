"""Warn-only validation against trustrag.validate.yaml (spec §15)."""

import warnings
from pathlib import Path

import pytest

from trustrag.config.schema import TrustRAGConfig
from trustrag.config.validate import validate_client


def _config(signals: list[str], doc_types: list[str] | None = None) -> TrustRAGConfig:
    payload: dict[str, object] = {"storage": {"bucket": "s3://b"}, "signals": signals}
    if doc_types is not None:
        payload["doc_types"] = doc_types
    return TrustRAGConfig.model_validate(payload)


def test_disallowed_signal_warns_but_proceeds(tmp_path: Path) -> None:
    validate_path = tmp_path / "trustrag.validate.yaml"
    validate_path.write_text(
        "allowed_signals: [embedding, text]\n", encoding="utf-8"
    )
    config = _config(["embedding", "text", "graph"])
    with pytest.warns(UserWarning, match="graph"):
        result = validate_client(config, validate_path)
    # construction succeeds and the graph layer remains enabled
    assert result is config
    assert "graph" in {s.value for s in config.signals}


def test_disallowed_doc_type_warns(tmp_path: Path) -> None:
    validate_path = tmp_path / "trustrag.validate.yaml"
    validate_path.write_text(
        "allowed_doc_types: [pdf, txt]\n", encoding="utf-8"
    )
    config = _config(["embedding"], doc_types=["pdf", "docx"])
    with pytest.warns(UserWarning, match="docx"):
        validate_client(config, validate_path)


def test_within_allowlist_emits_no_warning(tmp_path: Path) -> None:
    validate_path = tmp_path / "trustrag.validate.yaml"
    validate_path.write_text(
        "allowed_signals: [embedding, text]\n", encoding="utf-8"
    )
    config = _config(["embedding", "text"])
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = validate_client(config, validate_path)
    assert result is config


def test_missing_validation_file_means_no_check(tmp_path: Path) -> None:
    config = _config(["embedding", "graph"])
    missing = tmp_path / "does-not-exist.yaml"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        validate_client(config, missing)
    assert caught == []


def test_no_validation_path_means_no_check() -> None:
    config = _config(["embedding", "graph"])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        validate_client(config, None)
    assert caught == []
