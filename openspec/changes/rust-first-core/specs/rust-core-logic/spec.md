## ADDED Requirements

### Requirement: Pure fusion computation lives once in the Rust core

Reciprocal-rank fusion (`rrf`) — rank arithmetic over candidate IDs and scores,
with no tokenization and no credentials — SHALL be implemented in the Rust core and
exposed via the FFI, so every SDK (Go, JS, Python) shares one implementation. The
fused ordering MUST be byte-parity-tested against the Python reference and be
identical across SDKs for identical input. The gate, tokenizer, and orchestration
MUST NOT move into the core in this change (ADR-0006).

#### Scenario: Fused ordering is byte-identical across SDKs

- **WHEN** the same candidate lists are fused through the core from any SDK
- **THEN** the fused ranking is byte-identical
- **AND** a parity test asserts the core output matches the Python reference

### Requirement: A shared conformance-vector suite pins the per-host logic

The grounding gate, `bm25`, and `chunker` — which STAY per host language — SHALL be
pinned against drift by a shared, language-agnostic conformance-vector suite:
golden `input → expected output` fixtures that every port (Python, Go, JS, and any
future Rust) MUST pass. The suite MUST include a multilingual/Unicode-edge corpus
(at least Turkish dotless-I, German ß, NFC vs NFD, CJK segmentation, and combining
marks). Python is the behavior reference that generates the vectors.

#### Scenario: Every port passes the same gate vectors

- **WHEN** the conformance suite runs against the grounding gate in Python, Go, and
  JS
- **THEN** each port produces the expected output for every vector

#### Scenario: A Unicode-edge vector catches divergence

- **WHEN** a gate vector uses a Turkish/German/NFC-NFD/CJK input
- **THEN** any port whose tokenization diverges fails that vector rather than
  passing silently on ASCII

### Requirement: Public appearance is deprecated, not removed

Where a port exposed its own fusion/bm25/chunker helper publicly, that public
appearance SHALL be preserved as a **deprecated** shim delegating to the new path,
with a pointer, and MUST NOT be deleted in this change. Each helper's actual
public/internal exposure MUST be verified before it is replaced, so a user-imported
helper is not silently removed under an "internal" label.

#### Scenario: A previously-public helper still works, marked deprecated

- **WHEN** existing code calls a port helper that moved or was pinned
- **THEN** it still works via the deprecated shim, which signals deprecation and
  points to the replacement
