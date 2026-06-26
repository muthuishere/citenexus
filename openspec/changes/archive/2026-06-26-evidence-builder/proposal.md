## Why

Extraction (§8) produces ordered `ExtractedBlock`s, but retrieval, the graph, and
every cited answer operate on **Evidence Units** (§7) — the atomic, bbox-cited,
partition-tagged objects TrustRAG is built on. The library needs the pure,
deterministic seam that turns blocks into EUs so ingest can hash, cache, and
partially rebuild them (§4c) without any model call.

## What Changes

- Add `build_evidence_units(doc, *, partition, language, acl=None) -> list[EvidenceUnit]`:
  map each `ExtractedBlock` to exactly one `EvidenceUnit`, in document order.
- `eu_id` is `f"{document_id}::{order}"`; `BlockKind` maps to `EUType` by a closed
  table (paragraph→paragraph, heading→section, table→table, code→code_block,
  image→image, slide→page_summary, thread_turn→paragraph, ocr_block→ocr_block).
- The verbatim block text becomes both the unit `text` and its
  `Citation(passage, page, bbox)`; the block's `structure_path` is carried through.
- The caller-detected `language` (§11a) is stamped on every unit; the `partition`
  (§6b) and opaque `acl` (§7c) are carried verbatim — never parsed or enforced.
- Blocks whose text is empty or whitespace-only are skipped. The mapping is pure
  and deterministic: same document in, same units out.

## Capabilities

### New Capabilities
- `evidence-builder`: the deterministic block→Evidence Unit mapping (id scheme,
  `BlockKind`→`EUType` table, bbox-faithful citation, structure-path/language/
  partition/opaque-acl carry, empty-block skip) that produces the §7 objects
  retrieval and grounding depend on.

### Modified Capabilities
<!-- None: purely additive. EvidenceUnit/Citation/EUType (§7) and ExtractedDoc/
ExtractedBlock/BlockKind (§8) already ship and are reused unchanged. -->

## Impact

- New module `src/trustrag/evidence/builder.py`, building only on the existing
  `trustrag.evidence.unit` (§7) and `trustrag.extract.types` (§8) and
  `trustrag.domain.partition` (§6b). `evidence/__init__.py` is unchanged; the
  builder is imported by full path.
- New tests under `tests/evidence/test_builder.py`. No new dependencies, no
  public-API verb change (this is an internal ingest stage, not a fourth verb).
