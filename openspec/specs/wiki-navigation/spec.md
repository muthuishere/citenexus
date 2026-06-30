# wiki-navigation Specification

## Purpose

Build S3-native wiki/navigation pages over partition evidence. Wiki pages guide
retrieval, but they are never cited directly.

## Requirements

### Requirement: Wiki pages are navigation artifacts

The wiki store SHALL build pages from indexed Evidence Units and persist them as
rebuildable JSON under the partition knowledge layer.

#### Scenario: Page references source EUs

- **GIVEN** a document with indexed Evidence Units
- **WHEN** wiki pages are built
- **THEN** each page carries the EU refs it summarizes

### Requirement: Wiki retrieval resolves down to Evidence Units

The wiki retriever SHALL match query terms against page title, summary, and
keywords, then return the underlying EU candidates.

#### Scenario: Wiki hit is not a citation target

- **WHEN** a query matches a wiki page
- **THEN** the returned candidate has `signal = wiki`
- **AND** its text and provenance fields come from the underlying EU
