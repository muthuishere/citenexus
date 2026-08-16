## MODIFIED Requirements

### Requirement: Answer-language fallback chain for the short query

**BREAKING.** This replaces the five-rung §11a chain with a four-rung one and
**removes the evidence-dominant rung entirely**. `conformance/cases/language.json`
must be regenerated and the Go / JS / Rust ports must follow.

The library SHALL provide `resolve_answer_language(...)` implementing the §11a
chain over the **short query only**. It SHALL select the answer language in this
exact order: (1) an explicit `answer_language` override; otherwise (2) the
detected language when detection is reliable; otherwise (3) the established
conversation language; otherwise (4) the configured `default_answer_language`.

The retrieved evidence SHALL NOT influence the answer language. The
`languages_in_evidence` argument SHALL remain accepted, for port and vector
signature stability, and SHALL be ignored. Evidence languages remain REPORTED on
`EvidenceSignals.languages_in_evidence`.

Documents SHALL NOT be re-detected here.

#### Scenario: An explicit override wins over a reliable detection

- **WHEN** detection is reliable for `ta`, and an explicit `answer_language` of
  `fr` is supplied
- **THEN** `resolve_answer_language` returns `fr` (the caller's stated intent
  outranks the classifier)

#### Scenario: An explicit override wins over everything else

- **WHEN** an explicit `answer_language` of `ta` is supplied together with a
  conversation language, evidence languages, and a configured default
- **THEN** `resolve_answer_language` returns `ta`

#### Scenario: A reliable detection is used when nothing is explicit

- **WHEN** detection is reliable for `ja`, no override and no conversation
  language are supplied, and the evidence languages are `["ta", "ta"]`
- **THEN** `resolve_answer_language` returns `ja`

#### Scenario: No override falls to conversation language

- **WHEN** detection is unreliable, no override is supplied, and the established
  conversation language is `es`
- **THEN** `resolve_answer_language` returns `es`

#### Scenario: Evidence languages are ignored

- **WHEN** detection is unreliable or absent, no override and no conversation
  language are supplied, and the retrieved evidence languages are
  `["te", "te", "ta"]` with a configured default of `en`
- **THEN** `resolve_answer_language` returns `en` (the configured default, NOT
  the dominant evidence language)

#### Scenario: Nothing else falls to the configured default

- **WHEN** detection is unreliable and no override or conversation language is
  supplied
- **THEN** `resolve_answer_language` returns the configured
  `default_answer_language`

## ADDED Requirements

### Requirement: The `"auto"` answer-language sentinel detects from the question

`CiteNexus.ask` and both answer flows SHALL treat `answer_language="auto"` as a
request to detect the answer language **from the question**, using the injected
language detector. An unreliable detection, or no configured detector, SHALL fall
through to the configured `default_answer_language` — never to the evidence.

`answer_language=None` (unspecified) SHALL NOT detect: it resolves directly to
the configured `default_answer_language`. `"auto"` SHALL NEVER be returned as an
answer language.

#### Scenario: Auto detects the question language

- **GIVEN** a client with a language detector and a Japanese question
- **WHEN** the question is asked with `answer_language="auto"`
- **THEN** the Result's `answer_language` is `ja`

#### Scenario: Auto without a detector falls to the default

- **GIVEN** a client with no language detector configured
- **WHEN** any question is asked with `answer_language="auto"`
- **THEN** the Result's `answer_language` is the configured default

#### Scenario: Unspecified never detects and never reads the evidence

- **GIVEN** a corpus whose retrieved candidates are all Telugu and a client whose
  default answer language is `en`
- **WHEN** an English question is asked with no `answer_language`
- **THEN** the Result's `answer_language` is `en`

#### Scenario: The sentinel is never a language code

- **WHEN** a question is asked with `answer_language="auto"`
- **THEN** the Result's `answer_language` is never the string `"auto"`

### Requirement: Configured default answer language

`MultilingualConfig` SHALL expose `default_answer_language` (default `"en"`) as
the named knob for the chain's final rung. The pre-existing `fallback_language`
key SHALL remain accepted as a deprecated alias, and SHALL win when a caller has
set it to a non-default value, so existing configs keep their behaviour.

#### Scenario: The new knob is used

- **WHEN** a config sets `multilingual.default_answer_language: "hi"`
- **THEN** an unspecified `answer_language` resolves to `hi`

#### Scenario: The deprecated alias still works

- **WHEN** a config sets only `multilingual.fallback_language: "fr"`
- **THEN** an unspecified `answer_language` resolves to `fr`
