## ADDED Requirements

### Requirement: Search fans out to the requested languages, keeping the original

`ask()` and `retrieve()` SHALL accept `search_languages`, an ordered sequence of
ISO-639-1 codes, defaulting to `("en",)`. For each requested language the library
SHALL obtain one reformulation of the question in that language and issue
retrieval for it in addition to the original question.

The original question SHALL always be one of the issued queries and SHALL never be
replaced by a reformulation. Translation is lossy exactly where lexical retrieval
is precise — names, statute and clause numbers, identifiers — so fan-out SHALL be
strictly additive at retrieval.

All resulting lists SHALL be merged through the single existing RRF fusion. No
second fusion SHALL be introduced.

The order of the issued queries SHALL follow the caller's `search_languages`
order, de-duplicated preserving first occurrence.

#### Scenario: Default is today's behaviour

- **GIVEN** a client with a reformulator configured
- **WHEN** `ask()` is called without `search_languages`
- **THEN** exactly one reformulation is requested, targeting English
- **AND** the retrieval queries are identical to those issued before this change

#### Scenario: Fan-out reaches evidence in another language

- **GIVEN** a corpus containing the answer only in a non-Latin-script language
- **WHEN** an English question is asked with that language in `search_languages`
- **THEN** the fused candidates include the non-Latin-script Evidence Unit

#### Scenario: Fan-out never loses a candidate

- **GIVEN** a question that retrieves a set of Evidence Units with `("en",)`
- **WHEN** the same question is asked with additional search languages
- **THEN** every Evidence Unit retrieved by the single-language path is still present

#### Scenario: Query order is deterministic

- **GIVEN** two search languages
- **WHEN** the fan-out queries are issued
- **THEN** the original question is issued first, followed by the reformulations in
  `search_languages` order
- **AND** repeating the call issues the same queries in the same order

### Requirement: One model call per (question, language)

Reformulations SHALL be cached by the pair of question and target language, so
`ask`, `retrieve` and `evaluate` on the same question pay at most one model call
per language.

Failures SHALL be cached under the same key, so an unreachable endpoint is not
retried per call site.

A reformulation that fails, returns empty, or equals the original SHALL contribute
no extra query, and retrieval SHALL proceed with whatever queries remain — never
an error.

#### Scenario: Repeat questions do not pay again

- **GIVEN** a reformulator backed by a counting transport
- **WHEN** the same question is reformulated three times for the same language
- **THEN** the transport is called once

#### Scenario: Distinct languages are cached separately

- **WHEN** the same question is reformulated for two different languages
- **THEN** the transport is called twice, once per language

#### Scenario: A dead endpoint degrades to single-query retrieval

- **GIVEN** a reformulation endpoint that raises on every call
- **WHEN** a question is asked with two search languages
- **THEN** no error is raised to the caller
- **AND** retrieval is issued for the original question alone

### Requirement: An unsupported search language refuses explicitly

The library SHALL refuse a requested search language whose script is not in the
tokenizer's supported-script set, raising an error that names the language and the
script. It SHALL NOT return an empty result, a partial result, or a silent
downgrade to fewer languages.

The refusal SHALL be raised before any model call is made.

An unrecognised language code SHALL be refused rather than guessed.

Requesting more than one search language with no reformulator configured SHALL be
refused, because it would otherwise fan out to nothing and be indistinguishable
from a search that found nothing.

The refusal SHALL be a capability signal and SHALL NOT be reported through the
evidence-absent abstention channel.

#### Scenario: Telugu is refused by name

- **WHEN** `ask()` is called with a search language whose script is unsupported
- **THEN** an unsupported-search-language error is raised
- **AND** the error names both the language and the script
- **AND** no reformulation model call was made

#### Scenario: An unknown language code is refused

- **WHEN** `retrieve()` is called with a code that is not in the language table
- **THEN** an unsupported-search-language error is raised

#### Scenario: Fan-out without a reformulator is refused

- **GIVEN** a client with no reformulator configured
- **WHEN** `ask()` is called with two search languages
- **THEN** an unsupported-search-language error is raised

#### Scenario: The default needs no reformulator

- **GIVEN** a client with no reformulator configured
- **WHEN** `ask()` is called with the default `search_languages`
- **THEN** the call succeeds and behaves exactly as before this change

### Requirement: Fan-out changes retrieval only, never the guarantee

Fan-out SHALL affect only which passages are retrieved. The per-claim faithfulness
gate SHALL verify each claim against a single cited passage exactly as before, and
citations SHALL remain verbatim in the source language.

A reformulation SHALL be used as a retrieval key only. It SHALL NOT appear in the
answer, in a citation, or in the input to the faithfulness gate.

#### Scenario: A citation stays in its source language

- **GIVEN** a corpus whose answer exists only in a non-Latin-script language
- **WHEN** an English question is answered via fan-out to that language
- **THEN** the cited text is the source passage verbatim, in its own script
- **AND** it is not a translation of that passage

#### Scenario: Ungrounded content is still refused

- **GIVEN** fan-out retrieves a passage that does not support the generated answer
- **WHEN** the faithfulness gate runs
- **THEN** the result is an abstention, exactly as without fan-out

### Requirement: `answer_language` supports an explicit auto sentinel

`answer_language` SHALL accept the literal `"auto"`, meaning "answer in the
question's detected language". `"auto"` and `None` SHALL be the same behaviour.

`answer_language=None` SHALL continue to follow the existing answer-language
fallback chain unchanged.

An explicit language code SHALL continue to force that answer language.

#### Scenario: auto and None agree

- **WHEN** the same question is asked with `answer_language=None` and with
  `answer_language="auto"`
- **THEN** the two results carry the same answer language

#### Scenario: An explicit language still forces the answer language

- **WHEN** a question is asked with an explicit `answer_language`
- **THEN** the answer language resolves through the unchanged fallback chain with
  that override
