"""Query language detection + the §11a answer-language chain."""

from citenexus.lang.detect import (
    DEFAULT_THRESHOLD,
    FastTextDetector,
    HeuristicDetector,
    LanguageResult,
)
from citenexus.lang.fallback import (
    AUTO_ANSWER_LANGUAGE,
    flag_code_mixing,
    resolve_answer_language,
    resolve_requested_answer_language,
)

__all__ = [
    "AUTO_ANSWER_LANGUAGE",
    "DEFAULT_THRESHOLD",
    "FastTextDetector",
    "HeuristicDetector",
    "LanguageResult",
    "flag_code_mixing",
    "resolve_answer_language",
    "resolve_requested_answer_language",
]
