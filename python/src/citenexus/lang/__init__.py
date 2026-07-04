"""Query language detection + the §11a answer-language fallback chain."""

from citenexus.lang.detect import (
    DEFAULT_THRESHOLD,
    FastTextDetector,
    HeuristicDetector,
    LanguageResult,
)
from citenexus.lang.fallback import flag_code_mixing, resolve_answer_language

__all__ = [
    "DEFAULT_THRESHOLD",
    "FastTextDetector",
    "HeuristicDetector",
    "LanguageResult",
    "flag_code_mixing",
    "resolve_answer_language",
]
