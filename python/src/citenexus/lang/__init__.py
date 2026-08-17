"""Query language detection + the §11a answer-language chain.

Also the home of the named code sets — :class:`Language` and :class:`Script`.
They are imported FIRST and have no library imports of their own, so
``citenexus.tokenize`` can build its script tables from them without a cycle.
"""

# Must stay first: tokenize imports citenexus.lang.codes, so codes has to be
# fully initialized before this package pulls in anything that touches tokenize.
from citenexus.lang.codes import (
    AUTO,
    Language,
    LanguageCode,
    LanguageLike,
    Script,
    ScriptCode,
    ScriptLike,
)
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
    "AUTO",
    "AUTO_ANSWER_LANGUAGE",
    "DEFAULT_THRESHOLD",
    "FastTextDetector",
    "HeuristicDetector",
    "Language",
    "LanguageCode",
    "LanguageLike",
    "LanguageResult",
    "Script",
    "ScriptCode",
    "ScriptLike",
    "flag_code_mixing",
    "resolve_answer_language",
    "resolve_requested_answer_language",
]
