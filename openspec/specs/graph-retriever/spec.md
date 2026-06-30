# graph-retriever Specification

## Purpose

Build a deterministic, rebuildable graph cache for a partition and expose it as a
retrieval signal. Graph hits are navigation only; they resolve to Evidence Units
before fusion and citation.

## Requirements

### Requirement: Graph artifacts are rebuildable from indexed EUs

The graph store SHALL build a JSON graph artifact from indexed Evidence Units and
persist it under the partition graph layer.

#### Scenario: Graph is built from EU text

- **GIVEN** indexed Evidence Units in a leaf partition
- **WHEN** the graph store builds from the leaf store
- **THEN** graph nodes reference the EUs that mention them

### Requirement: Graph retrieval returns citable EU candidates

The graph retriever SHALL match query terms to graph nodes and return candidates
whose payload comes from the underlying Evidence Units.

#### Scenario: Graph hit resolves to EU

- **WHEN** a query matches a graph node
- **THEN** the returned candidate has `signal = graph`
- **AND** includes the EU text, document id, checksum, and raw URI when present
