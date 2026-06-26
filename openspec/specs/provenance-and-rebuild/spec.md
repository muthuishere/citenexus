# provenance-and-rebuild Specification

## Purpose
TBD - created by archiving change provenance-and-rebuild. Update Purpose after archive.
## Requirements
### Requirement: Every artifact carries a producing-stamp

Every generated artifact SHALL carry a `produced_by` stamp that records the
`artifact_version` and, for each stage that produced it, the producing plugin name,
its `plugin_version`, and the endpoint model and embedding dimension where relevant
(extractor, chunker, vision, embedding, graph_extractor) per §4c.

#### Scenario: Stamp round-trips losslessly

- **WHEN** a `produced_by` stamp with extractor, chunker, vision, embedding, and
  graph_extractor entries is serialized to JSON and parsed back
- **THEN** the resulting stamp equals the original, including each stage's plugin
  name and `plugin_version`.

#### Scenario: Stamp captures plugin version

- **WHEN** a stamp is built from the current plugin set
- **THEN** each stage entry exposes the registered plugin's `plugin_version`, so the
  planner can later detect a version change.

### Requirement: Rebuild planner diffs current set against the stamp

The rebuild planner SHALL compare the current plugin/model set against an artifact's
stamp and return the set of layers that are stale; when the current set matches the
stamp exactly the planner SHALL return an empty set (idempotent — no rebuild).

#### Scenario: No change yields no rebuild

- **WHEN** the current plugin/model set is identical to an artifact's stamp
- **THEN** the planner returns an empty rebuild set.

### Requirement: Rebuilds respect the dependency DAG

The planner SHALL respect the dependency order
`extract → OCR/vision → EU/chunk → {embedding, structure, graph} → community/summary`,
so that changing an upstream stage marks all downstream layers stale and never marks
an upstream layer stale for a downstream-only change.

#### Scenario: Downstream layers follow an upstream change

- **WHEN** an upstream stage (chunk) changes
- **THEN** every layer downstream of it is included in the rebuild set and no layer
  upstream of it is included.

### Requirement: Embedding model/plugin change rebuilds embeddings only

When only the embedding plugin or its endpoint model changes, the planner SHALL mark
the embeddings layer stale and SHALL leave OCR, vision descriptions, Evidence Units,
graph, and communities untouched.

#### Scenario: Swap the embedder

- **WHEN** the embedding plugin/model differs from the stamp and all other stages match
- **THEN** the rebuild set is exactly `{embedding}` and excludes OCR, vision, EUs,
  graph, and communities.

### Requirement: Vision plugin change rebuilds vision and its dependents

When the vision plugin changes, the planner SHALL mark the vision descriptions, the
Evidence Units derived from them, and the embeddings of those EUs stale, while
leaving text-only EUs and the graph of unaffected documents untouched.

#### Scenario: Swap the vision model

- **WHEN** the vision plugin differs from the stamp
- **THEN** the rebuild set includes vision descriptions, their dependent EUs, and the
  embeddings of those EUs, and excludes text-only EUs and the graph of unaffected
  documents.

### Requirement: Chunker change rebuilds EUs and everything downstream

When the chunker changes, the planner SHALL mark Evidence Units and every downstream
layer (embedding, structure, graph, community/summary) stale, while leaving raw
extraction and OCR untouched.

#### Scenario: Swap the chunker

- **WHEN** the chunker differs from the stamp
- **THEN** the rebuild set includes EUs, embeddings, structure, graph, and
  community/summary, and excludes raw extraction and OCR.

### Requirement: Graph extractor change rebuilds the graph layers only

When the graph extractor changes, the planner SHALL mark entities, relations,
communities, and summaries stale, while leaving Evidence Units, embeddings, and
structure untouched.

#### Scenario: Swap the graph extractor

- **WHEN** the graph extractor differs from the stamp
- **THEN** the rebuild set includes entities/relations/communities/summaries and
  excludes EUs, embeddings, and structure.

### Requirement: Query-time-only changes rebuild nothing

When only the reranker or the generation LLM changes, the planner SHALL return an
empty rebuild set, because those plugins act at query time and produce no stored
artifact.

#### Scenario: Swap the reranker or LLM

- **WHEN** only the reranker or LLM plugin/model differs from the stamp
- **THEN** the rebuild set is empty and all stored indexes are left untouched.

