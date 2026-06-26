## ADDED Requirements

### Requirement: Deterministic fakes stand in for injected endpoints

The system SHALL provide deterministic, offline fakes: a `FakeEmbedding` that maps
text to a fixed-dimension L2-normalized bag-of-tokens vector (so shared words
produce nearby vectors), an extractive `FakeLLM` that answers with the cited
passage verbatim, and an identity `FakeReranker`.

#### Scenario: Embedding is deterministic and token-sensitive

- **WHEN** `FakeEmbedding` embeds the same text twice
- **THEN** the two vectors are identical, and a text sharing tokens embeds nearer
  than a text sharing none.

### Requirement: Ingest stores an Evidence Unit and indexes it

`SmokePipeline.ingest(text, document_id)` SHALL store the raw bytes
content-addressed, upsert one Evidence Unit (id + vector + payload) into the
partition's leaf vector store, record the document checksum in the etag manifest,
and return the `eu_id`.

#### Scenario: Ingest is idempotent

- **WHEN** the same document is ingested twice
- **THEN** the leaf store holds a single Evidence Unit for it and the etag manifest
  records its checksum.

### Requirement: Ask cites evidence or abstains

`SmokePipeline.ask(question)` SHALL retrieve from the leaf store, apply a
faithfulness gate (the answer's tokens must be supported by the cited passage),
and return a `Result`: when grounded, `decision = answered` with a `SourceRef` and
a full provenance chain (`eu_id → document → s3_object → checksum`); when no
sufficiently relevant evidence exists, `decision = refused` with no claims and no
fabricated answer.

#### Scenario: A grounded question is answered with a citation

- **WHEN** a document is ingested and a question sharing its terms is asked
- **THEN** `decision = answered`, the answer is supported by the cited passage, and
  the provenance entry resolves to a content-addressed object.

#### Scenario: An unanswerable question abstains

- **WHEN** `ask` is called against an empty or irrelevant corpus
- **THEN** `decision = refused`, `claims` is empty, and no ungrounded answer is
  produced.
