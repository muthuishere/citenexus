## ADDED Requirements

### Requirement: Concrete LanguageResult type

The library SHALL provide a concrete, frozen `LanguageResult` as the return type
of the `LanguageDetectorPlugin.detect` contract. It SHALL carry `language` (an
ISO language code string), `confidence` (a float), and `is_reliable` (a bool that
is true exactly when `confidence` meets or exceeds the detector's threshold).

#### Scenario: LanguageResult is frozen and typed

- **WHEN** a `LanguageResult(language="en", confidence=0.9, is_reliable=True)` is
  constructed
- **THEN** its `language`, `confidence`, and `is_reliable` fields are accessible
  and the instance is immutable (assigning to a field raises)

### Requirement: Threshold gates reliability

A detector SHALL mark a result reliable only when its confidence meets or exceeds
the configured threshold (default `0.50`, the §17
`detect_confidence_threshold`). A confidence below the threshold SHALL yield
`is_reliable = False`.

#### Scenario: Confidence below threshold is unreliable

- **WHEN** a detector with threshold `0.50` produces a top language at confidence
  `0.30`
- **THEN** the returned `LanguageResult.is_reliable` is `False`

#### Scenario: Confidence at or above threshold is reliable

- **WHEN** a detector with threshold `0.50` produces a top language at confidence
  `0.92`
- **THEN** the returned `LanguageResult.is_reliable` is `True`

### Requirement: FastText detector with lazy model download

The library SHALL provide `FastTextDetector`, a `LanguageDetectorPlugin` backed
by fastText `lid.176`. It SHALL lazily fetch the compressed model
(`lid.176.ftz`) into `assets/models/` via `urllib` on first use, cache it on disk
and in memory, and on `detect(text)` return the top predicted language (ISO code,
fastText `__label__` prefix stripped) and its probability as the confidence, with
reliability gated by the threshold. No model SHALL be bundled or added as a pip
dependency.

#### Scenario: First use downloads and caches the model

- **WHEN** `FastTextDetector.detect` is called for the first time and the model
  file is absent from `assets/models/`
- **THEN** the model is downloaded to `assets/models/lid.176.ftz`, loaded once,
  and reused (in memory and on disk) on subsequent calls without re-downloading

#### Scenario: Real model detects a clearly-English query

- **WHEN** the real `lid.176` model is loaded and asked to detect a clearly
  English sentence
- **THEN** the returned `LanguageResult.language` is `en`

### Requirement: Hermetic heuristic detector

The library SHALL provide `HeuristicDetector`, a `LanguageDetectorPlugin` that
detects language from unicode-script majority (plus light cues) with no network
access and fully deterministic output, usable as the default detector in unit
tests and as an offline fallback.

#### Scenario: Single-script text gets a plausible code

- **WHEN** `HeuristicDetector.detect` is given text written clearly in one script
  (e.g. Latin, Cyrillic, or Han)
- **THEN** it returns a plausible ISO code for that script with confidence
  reflecting the dominant-script fraction, without any network call

### Requirement: Answer-language fallback chain for the short query

The library SHALL provide `resolve_answer_language(...)` implementing the §11a
chain over the **short query only**. It SHALL select the answer language in this
exact order: (1) the detected language when detection is reliable; otherwise
(2) an explicit `answer_language` override; otherwise (3) the established
conversation language; otherwise (4) the dominant language among the retrieved
evidence (`languages_in_evidence`); otherwise (5) the configured
`default_answer_language`. Documents SHALL NOT be re-detected here; their
languages enter only as the evidence-dominant fallback signal.

#### Scenario: Reliable detection wins

- **WHEN** detection is reliable for the query language `de`, and an override,
  conversation language, and evidence languages are all also present
- **THEN** `resolve_answer_language` returns `de` (detection short-circuits the
  chain)

#### Scenario: Unreliable detection falls to explicit override

- **WHEN** detection is unreliable and an explicit `answer_language` override of
  `fr` is supplied
- **THEN** `resolve_answer_language` returns `fr`

#### Scenario: No override falls to conversation language

- **WHEN** detection is unreliable, no override is supplied, and the established
  conversation language is `es`
- **THEN** `resolve_answer_language` returns `es`

#### Scenario: No conversation language falls to evidence-dominant

- **WHEN** detection is unreliable, no override and no conversation language are
  supplied, and the retrieved evidence languages are `["ta", "ta", "en"]`
- **THEN** `resolve_answer_language` returns `ta` (the dominant evidence language)

#### Scenario: Nothing else falls to the configured default

- **WHEN** detection is unreliable and no override, conversation language, or
  evidence languages are supplied
- **THEN** `resolve_answer_language` returns the configured
  `default_answer_language`

### Requirement: Code-mixing flag

The library SHALL expose a helper that flags likely code-mixing: when the top two
language candidates are both strong (each at or above a strong threshold), the
text has no single reliable label and the helper SHALL report it as code-mixed.

#### Scenario: Two strong candidates are flagged code-mixed

- **WHEN** the candidate set has the top two languages both at or above the strong
  threshold (e.g. `en` at `0.55` and `ta` at `0.44` with strong `0.40`)
- **THEN** the helper reports the text as code-mixed (not a single reliable label)

#### Scenario: One dominant candidate is not flagged

- **WHEN** the top candidate is strong and the second is weak (e.g. `en` at `0.95`
  and `fr` at `0.03`)
- **THEN** the helper reports the text as NOT code-mixed
