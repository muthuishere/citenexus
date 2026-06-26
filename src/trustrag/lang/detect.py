"""Query language detection — the concrete `LanguageResult` + two detectors (§11a).

§11a makes language detection a *defined method*, not an assumption: fastText
`lid.176` plus a confidence threshold. This module supplies the concrete
`LanguageResult` (the type the `LanguageDetectorPlugin` protocol left as a forward
alias) and two implementations:

- `FastTextDetector` — the real `lid.176` model, **lazily downloaded** to
  `assets/models/` on first use and cached on disk + in memory. It is never
  bundled and is not a pip dependency.
- `HeuristicDetector` — a deterministic, network-free unicode-script detector used
  as the default in hermetic unit tests and as an offline fallback.

Detection here targets the **short query only**. Documents are not re-scanned at
query time — each Evidence Unit already carries its own ingest-time `language`;
those enter the answer-language decision only as a fallback signal (§11a chain,
see `fallback.py`).
"""

from __future__ import annotations

import threading
import unicodedata
import urllib.request
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from trustrag.plugins import LanguageDetectorPlugin

# §17 `multilingual.detect_confidence_threshold` default.
DEFAULT_THRESHOLD = 0.50

# Published fastText compressed language-id model (lid.176).
_MODEL_URL = "https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz"
_MODEL_FILENAME = "lid.176.ftz"

# `assets/models/` at the repo root (gitignored). Resolved relative to this file:
# src/trustrag/lang/detect.py -> repo root is three parents up from `src`.
_ASSETS_DIR = Path(__file__).resolve().parents[3] / "assets" / "models"


class LanguageResult(BaseModel):
    """A detected language with its confidence and a threshold-gated reliability.

    `is_reliable` is the single bit the §11a fallback chain reads: a reliable
    result is used as-is; an unreliable one (typical for very short queries) drops
    through to the explicit / contextual fallback signals.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    language: str
    confidence: float
    is_reliable: bool

    @classmethod
    def from_prediction(
        cls, language: str, confidence: float, *, threshold: float = DEFAULT_THRESHOLD
    ) -> LanguageResult:
        """Build a result, gating reliability on ``confidence >= threshold``."""
        return cls(
            language=language,
            confidence=confidence,
            is_reliable=confidence >= threshold,
        )


def _ensure_model(path: Path, url: str) -> Path:
    """Download the model to ``path`` if absent (atomic-ish); return ``path``."""
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(path)
    return path


def _predict_top(model: object, text: str) -> tuple[str, float]:
    """Top (label, probability) — NumPy-2-safe.

    `fasttext-wheel`'s `model.predict` does `np.array(probs, copy=False)`, which
    raises on NumPy 2.x. We try it, then fall back to the C binding (`model.f`),
    which returns `(prob, label)` pairs directly and never touches NumPy.
    """
    try:
        labels, probs = model.predict(text, k=1)  # type: ignore[attr-defined]
        return labels[0], float(probs[0])
    except ValueError:
        preds = model.f.predict(text, 1, 0.0, "strict")  # type: ignore[attr-defined]
        prob, label = preds[0]
        return label, float(prob)


class FastTextDetector(LanguageDetectorPlugin):
    """`lid.176` language detector — lazily downloaded + cached (§11a).

    Construction does no IO: the model is fetched and loaded on the first
    `detect()` call. Because that needs the network, tests exercising the real
    model are `@pytest.mark.integration`.
    """

    plugin_version = "fasttext-lid176-v1"

    def __init__(
        self,
        *,
        threshold: float = DEFAULT_THRESHOLD,
        model_dir: Path | None = None,
        model_url: str = _MODEL_URL,
    ) -> None:
        self.threshold = threshold
        self._model_path = (model_dir or _ASSETS_DIR) / _MODEL_FILENAME
        self._model_url = model_url
        self._model: object | None = None
        self._lock = threading.Lock()

    def _load(self) -> object:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    import fasttext  # local import: heavy, optional at import time

                    path = _ensure_model(self._model_path, self._model_url)
                    self._model = fasttext.load_model(str(path))
        return self._model

    def detect(self, text: str) -> LanguageResult:
        model = self._load()
        # fastText cannot handle embedded newlines in `predict`.
        cleaned = text.replace("\n", " ").strip()
        label, confidence = _predict_top(model, cleaned)
        language = label.removeprefix("__label__")
        return LanguageResult.from_prediction(
            language, confidence, threshold=self.threshold
        )


# Dominant-script → ISO code. Order matters only for documentation; lookup is by
# the script *name* prefix produced by `unicodedata.name`.
_SCRIPT_TO_ISO: dict[str, str] = {
    "CYRILLIC": "ru",
    "DEVANAGARI": "hi",
    "ARABIC": "ar",
    "HEBREW": "he",
    "GREEK": "el",
    "HANGUL": "ko",
    "HIRAGANA": "ja",
    "KATAKANA": "ja",
    "CJK": "zh",  # `unicodedata.name` gives "CJK UNIFIED IDEOGRAPH-..."
    "THAI": "th",
    "LATIN": "en",
}

# A few light Latin-script cues so the heuristic can separate the most common
# Latin languages without a model. Deliberately tiny — this is a test default,
# not the shipping detector.
_LATIN_CUES: dict[str, frozenset[str]] = {
    "es": frozenset({"el", "la", "que", "de", "hola", "gracias", "por", "es"}),
    "fr": frozenset({"le", "la", "les", "que", "bonjour", "merci", "est", "vous"}),
    "de": frozenset({"der", "die", "das", "und", "ist", "nicht", "danke", "ein"}),
}


def _script_of(char: str) -> str | None:
    """The leading script token of a letter's unicode name, or None."""
    try:
        name = unicodedata.name(char)
    except ValueError:
        return None
    head = name.split(" ", 1)[0]
    if head == "CJK":
        return "CJK"
    return head


class HeuristicDetector(LanguageDetectorPlugin):
    """Deterministic, network-free script-majority detector (§11a test default).

    Counts letters by unicode script, maps the dominant script to a plausible ISO
    code (with light Latin cues), and sets confidence to the dominant-script
    fraction. Never touches the network — safe in hermetic unit tests.
    """

    plugin_version = "heuristic-script-v1"

    def __init__(
        self,
        *,
        threshold: float = DEFAULT_THRESHOLD,
        default_language: str = "en",
    ) -> None:
        self.threshold = threshold
        self.default_language = default_language

    def detect(self, text: str) -> LanguageResult:
        scripts: Counter[str] = Counter()
        for char in text:
            if not char.isalpha():
                continue
            script = _script_of(char)
            if script is not None:
                scripts[script] += 1

        total = sum(scripts.values())
        if total == 0:
            return LanguageResult.from_prediction(
                self.default_language, 0.0, threshold=self.threshold
            )

        dominant, count = scripts.most_common(1)[0]
        confidence = count / total
        language = _SCRIPT_TO_ISO.get(dominant, self.default_language)
        if dominant == "LATIN":
            language = self._latin_language(text, language)
        return LanguageResult.from_prediction(
            language, confidence, threshold=self.threshold
        )

    @staticmethod
    def _latin_language(text: str, default: str) -> str:
        tokens = {tok for tok in text.lower().split() if tok.isalpha()}
        best_lang = default
        best_hits = 0
        for lang, cues in _LATIN_CUES.items():
            hits = len(tokens & cues)
            if hits > best_hits:
                best_hits, best_lang = hits, lang
        return best_lang
