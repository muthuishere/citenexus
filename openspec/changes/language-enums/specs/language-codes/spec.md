## ADDED Requirements

### Requirement: Language and Script are named, discoverable code sets

The library SHALL expose a `Language` type naming every language code it
recognises, and a `Script` type naming every script its script table classifies.
Both SHALL be string-valued: a member SHALL compare equal to its own code and
SHALL serialize as that code.

The `"auto"` answer-language sentinel SHALL be a member of `Language`, and SHALL
NOT be a member of the search-language table.

#### Scenario: A member equals and serializes as its code

- **GIVEN** the language member for Tamil
- **THEN** it compares equal to `"ta"`
- **AND** it hashes equal to `"ta"`, so it is interchangeable as a mapping key
- **AND** JSON-encoding it yields `"ta"`, not a type name

#### Scenario: The auto sentinel is named but is not searchable

- **GIVEN** the `"auto"` sentinel is exposed as a language member
- **WHEN** it is passed as a search language
- **THEN** the call raises the unsupported-search-language error, naming it

### Requirement: Plain strings remain first-class at every entry point

Every public entry point that takes a language or script SHALL accept **both** a
plain `str` and the corresponding member, with identical behaviour. Passing a
plain string SHALL NOT emit a deprecation warning or any other warning, and SHALL
NOT be documented as superseded.

This applies to `ask`, `retrieve`, `stream`, the answer-language chain, the
search-language resolver, and the multilingual configuration fields.

#### Scenario: A string call site is unchanged and un-warned

- **GIVEN** a call passing `answer_language="ta"` and `search_languages=("en",)`
- **WHEN** it runs
- **THEN** the result is identical to the same call passing the members
- **AND** no warning of any category is emitted

#### Scenario: Configuration accepts either form

- **GIVEN** a multilingual configuration whose default answer language is set
- **THEN** setting it to a plain string and setting it to a member produce the
  same resolved value

### Requirement: One definition of the code set, expressed in the types

The search-language table and the claimed/continuous script sets SHALL be
expressed in terms of `Language` and `Script` rather than repeating the code
strings. A code SHALL NOT appear as a bare literal in more than one place per
port.

#### Scenario: The search table is keyed by the language type

- **THEN** every key of the search-language table is a `Language` member
- **AND** every script it names is a `Script` member
- **AND** lookup by the equivalent plain string still succeeds

### Requirement: Unknown codes still raise before any model call

An unrecognised search language SHALL raise `UnsupportedSearchLanguageError`
naming the offending code, and a recognised language whose script is unclaimed
SHALL raise naming both the language and the script — in both cases **before**
any reformulation, embedding or generation call is made. The error messages SHALL
be unchanged by the introduction of the types.

#### Scenario: A typo raises by name, spending nothing

- **GIVEN** a search language `"tamiil"`
- **WHEN** `ask` is called
- **THEN** `UnsupportedSearchLanguageError` names `"tamiil"`
- **AND** no model endpoint was called

#### Scenario: A named-but-unclaimed script raises naming the script

- **GIVEN** a search language whose script carries no golden fixture
- **THEN** the error names the language and the script as plain code strings

### Requirement: The code set is pinned across ports by a conformance vector

The language table, the script sets and the `"auto"` sentinel SHALL be published
as a conformance fixture. Each port SHALL assert its own constant set against
that fixture, so the three ports cannot diverge without a failing test.

Introducing the types SHALL NOT change any previously committed fixture.

#### Scenario: Every port pins to the same table

- **GIVEN** the committed language conformance fixture
- **THEN** the Python, Go and JS constant sets each equal it exactly

#### Scenario: No previously committed fixture moves

- **WHEN** the conformance drift guard regenerates every fixture
- **THEN** every fixture committed before this change is byte-identical
