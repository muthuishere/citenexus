## Context

CiteNexus is a framework, not a fixed product (v6 §4b): the built-in stages are
just defaults, and every stage must be replaceable by a typed plugin so new
extractors/models/retrievers can be added without changing core, and so §4c can
stamp each artifact with exactly what produced it. This change lays the protocol
+ registry seam that every later stage (ingest, embedding, retrieval, …) plugs
into. It depends on nothing except the standard library; the domain types it
references in method signatures (`EvidenceUnit`, `ExtractedDoc`, `Embedding`,
`Candidate`, `VisionResult`, `LanguageResult`, …) are forward contracts owned by
`core-domain-types` and the later stage changes — here they appear only as type
annotations on abstract methods.

## Goals / Non-Goals

**Goals:**
- A common `Plugin` base carrying `plugin_version` (feeds §4c stamps).
- The 11 typed protocol ABCs with their contract methods.
- A registry that enforces type-conformant registration, supports single-slot
  replacement and a retriever fusion set, and exposes one `use()` verb.
- Built-ins register through the identical mechanism (no privileged path).

**Non-Goals:**
- Any concrete plugin implementation (each lands in its own later change).
- The fusion algorithm, grounding, or answer flow (these stay in core; the
  retriever protocol is deliberately limited so it cannot reach them).
- Plugin discovery/entry-points / dynamic loading (future).

## Decisions

- **ABCs (`abc.ABC` + `@abstractmethod`), not `typing.Protocol`.** Registration
  must *reject* non-conforming objects at runtime; `isinstance` against an ABC is
  a reliable runtime gate, whereas structural `Protocol` checks are weaker and
  `runtime_checkable` ignores method signatures. ABCs also force subclasses to
  implement the contract method (instantiation raises `TypeError` otherwise),
  which is exactly the "typed, not duck-typed" rule. Trade-off: plugins must
  subclass our base rather than merely match a shape — acceptable and intended.
- **`plugin_version` on the common base**, validated at registration (non-empty
  string). This is the single field §4c's `produced_by` stamp reads, so the
  registry is the right choke point to enforce it.
- **Registry data structure:** a dict keyed by protocol type for single-slot
  stages (`{EmbeddingPlugin: instance, …}`) plus a separate ordered list for the
  retriever fusion set. `resolve(protocol)` reads the dict; the retriever set is
  read by the (later) fusion core. `use(plugin)` inspects `isinstance` against
  each known protocol to pick the slot — retrievers routed to the set, everything
  else to its single slot.
- **Single-slot replace semantics:** registering a second plugin for the same
  protocol replaces the first (last-wins), so swapping an embedder is one call.
  Retrievers append, because fusion needs all of them.
- **`plugin_version` → provenance seam:** `provenance-and-rebuild` reads
  `plugin.plugin_version` (and the resolved endpoint model, where the plugin
  wraps an injected endpoint) to build each artifact's `produced_by` stamp. The
  registry exposes the resolved plugin per stage so the stamp can be assembled at
  artifact-write time.

## Risks / Trade-offs

- [Forward type references in method signatures create import-order coupling] →
  Use `from __future__ import annotations` so annotations are lazy strings;
  protocols don't import the concrete domain modules at definition time.
- [ABC subclassing is stricter than structural typing, raising the bar for
  third-party authors] → Acceptable: the §4c guarantee requires a known base; we
  document the base clearly and keep contract methods minimal.
- [`use()` type-dispatch must handle a plugin that satisfies two protocols] →
  Define protocols as mutually exclusive bases; if an object matches more than
  one, registration raises rather than guessing.

## Open Questions

- Whether to support named multiple instances of a single-slot stage later
  (e.g. two embedders for A/B benchmarking, §20). Out of scope for L1; the
  registry shape leaves room to add a keyed variant without breaking callers.
