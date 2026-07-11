"""LanguageResult + the two LanguageDetectorPlugin implementations (spec §11a)."""

from __future__ import annotations

import hashlib
import socket
from pathlib import Path

import pytest
from pydantic import ValidationError

from citenexus.lang import FastTextDetector, HeuristicDetector, LanguageResult
from citenexus.lang.detect import _ensure_model
from citenexus.plugins import LanguageDetectorPlugin


def test_language_result_is_frozen_and_typed() -> None:
    r = LanguageResult(language="en", confidence=0.9, is_reliable=True)
    assert r.language == "en"
    assert r.confidence == pytest.approx(0.9)
    assert r.is_reliable is True
    with pytest.raises(ValidationError):
        r.language = "fr"  # type: ignore[misc]


def test_from_prediction_gates_reliability_on_threshold() -> None:
    below = LanguageResult.from_prediction("en", 0.30, threshold=0.50)
    at = LanguageResult.from_prediction("en", 0.50, threshold=0.50)
    above = LanguageResult.from_prediction("en", 0.92, threshold=0.50)
    assert below.is_reliable is False
    assert at.is_reliable is True
    assert above.is_reliable is True


def test_heuristic_detector_is_a_plugin() -> None:
    det = HeuristicDetector()
    assert isinstance(det, LanguageDetectorPlugin)
    assert det.plugin_version


def test_heuristic_detects_latin_script() -> None:
    det = HeuristicDetector()
    r = det.detect("the quick brown fox jumps over the lazy dog")
    assert r.language == "en"
    assert r.is_reliable is True


def test_heuristic_detects_cyrillic_script() -> None:
    det = HeuristicDetector()
    r = det.detect("Привет мир как дела сегодня")
    assert r.language == "ru"
    assert r.confidence > 0.5


def test_heuristic_detects_han_script() -> None:
    det = HeuristicDetector()
    r = det.detect("这是一个清楚的中文句子")
    assert r.language == "zh"


def test_heuristic_threshold_makes_ambiguous_text_unreliable() -> None:
    # Mixed-script text yields a fractional dominant-script confidence; a
    # threshold above that fraction marks it unreliable — exactly the §11a
    # ambiguous-query case that triggers the fallback chain.
    det = HeuristicDetector(threshold=0.60)
    r = det.detect("hello привет")  # half Latin, half Cyrillic -> ~0.5
    assert r.confidence < 0.60
    assert r.is_reliable is False


def test_fasttext_detector_is_a_plugin_without_loading() -> None:
    # Constructing the detector must NOT download or load anything.
    det = FastTextDetector()
    assert isinstance(det, LanguageDetectorPlugin)
    assert det.plugin_version


def test_ensure_model_verifies_sha256_and_caches(tmp_path: Path) -> None:
    # A local "model" served over file:// so the fetch-cache logic is hermetic.
    payload = b"pretend fasttext model bytes"
    digest = hashlib.sha256(payload).hexdigest()
    src = tmp_path / "src.ftz"
    src.write_bytes(payload)
    dst = tmp_path / "cache" / "lid.176.ftz"

    # fresh fetch + verify
    out = _ensure_model(dst, src.as_uri(), digest)
    assert out == dst and dst.read_bytes() == payload
    # cache hit returns without re-fetching
    assert _ensure_model(dst, src.as_uri(), digest) == dst


def test_ensure_model_rejects_sha256_mismatch(tmp_path: Path) -> None:
    payload = b"pretend fasttext model bytes"
    src = tmp_path / "src.ftz"
    src.write_bytes(payload)
    dst = tmp_path / "cache" / "lid.176.ftz"
    wrong = "0" * 64

    with pytest.raises(ValueError, match="SHA256 mismatch"):
        _ensure_model(dst, src.as_uri(), wrong)
    # a failed-verification download must NOT leave a model in place
    assert not dst.exists()


def test_ensure_model_refetches_corrupt_cache(tmp_path: Path) -> None:
    payload = b"pretend fasttext model bytes"
    digest = hashlib.sha256(payload).hexdigest()
    src = tmp_path / "src.ftz"
    src.write_bytes(payload)
    dst = tmp_path / "cache" / "lid.176.ftz"
    dst.parent.mkdir(parents=True)
    dst.write_bytes(b"corrupted")  # wrong bytes already cached

    out = _ensure_model(dst, src.as_uri(), digest)
    assert out == dst and dst.read_bytes() == payload  # re-fetched good bytes


def _online() -> bool:
    try:
        socket.create_connection(("dl.fbaipublicfiles.com", 443), timeout=5).close()
        return True
    except OSError:
        return False


@pytest.mark.integration
def test_fasttext_real_model_detects_english() -> None:
    if not _online():
        pytest.skip("offline: cannot fetch lid.176 model")
    det = FastTextDetector()
    r = det.detect("This is clearly an English sentence about contracts.")
    assert r.language == "en"
    assert r.is_reliable is True
