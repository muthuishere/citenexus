## Context

§7 defines the Evidence Unit as the atomic retrievable object; §8 extraction emits
ordered `ExtractedBlock`s. This change is the join: a pure function that turns one
document's blocks into EUs. It builds only on already-shipped types —
`EvidenceUnit`/`Citation`/`EUType` (§7), `ExtractedDoc`/`ExtractedBlock`/`BlockKind`
(§8), `PartitionPath` (§6b) — and adds no model call, so it is hashable and
rebuildable per the §4c DAG.

## Goals / Non-Goals

**Goals:**
- One block → one EU, in document order, deterministically.
- A closed, total `BlockKind`→`EUType` mapping with a stable `eu_id` scheme.
- Bbox-faithful `Citation` whose `passage` is the verbatim block text.
- Carry `structure_path`, `language`, `partition`, and opaque `acl` without
  interpreting them.

**Non-Goals:**
- No language detection (the caller passes `language`; detection is §11a).
- No structure building (that is the sibling `structure-index` change, §7b).
- No embedding, checksum, or entity extraction (later stages populate those EU
  fields).
- No `acl`/`partition` enforcement — carried, never evaluated (§7c).

## Decisions

- **`eu_id = f"{document_id}::{order}"`.** `order` is the block's stable position
  in the extracted document, so the id is deterministic and collision-free within a
  document, and reproducible across rebuilds. The same scheme is the link target
  for `structure-index` node `eu_ref`s, keeping the two changes consistent.
- **Closed `BlockKind`→`EUType` table.** A `dict[BlockKind, EUType]` keyed on every
  `BlockKind` member makes the mapping total and explicit. `slide`→`page_summary`
  (a slide is a page-level summary unit), `thread_turn`→`paragraph` (a chat turn
  reads as a paragraph), `heading`→`section`. `ocr_block` keeps its own
  provenance-bearing `EUType`. A missing member would `KeyError` loudly rather than
  silently mistype evidence.
- **Verbatim passage = block text.** `Citation.passage` is the exact block text with
  its `page`+`bbox`, satisfying the "citations stay verbatim" invariant (§11). The
  EU `text` and the citation `passage` are the same string at build time; later
  stages may summarize `text` but the citation stays verbatim.
- **Skip empty/whitespace-only blocks.** A block with no visible text carries no
  evidence; emitting an EU for it would pollute retrieval with an un-citable unit.
  The skip is on `block.text.strip()`, so the surviving EUs keep their original
  (verbatim, un-stripped) text.
- **Opaque carry of `partition` and `acl`.** Both are passed straight onto the EU.
  The builder never inspects them — `acl` is `Any` and handed through by identity,
  matching the deferred-RBAC seam (§7c).

## Risks / Trade-offs

- **Order depends on the extractor.** EUs inherit the extractor's block order; a
  mis-ordered extraction yields mis-ordered EUs. → Out of scope here; the contract
  is "preserve order," and extractor correctness is §8's responsibility.
- **One-block-one-EU is intentionally flat.** No merging or splitting of blocks.
  Coarser/finer granularity (e.g. table-row EUs) is a future extractor or builder
  option, not this change. → Keeps the mapping pure and predictable.

## Open Questions

- Whether `checksum`/`source_checksum` should be stamped here or by the ingest
  stage that owns content hashing — deferred to `ingest-pipeline`; the builder
  leaves them `None`.
