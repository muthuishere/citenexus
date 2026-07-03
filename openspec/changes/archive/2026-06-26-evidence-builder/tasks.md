## 1. Tests first (red)

- [x] 1.1 Write `tests/evidence/test_builder.py`: one-EU-per-block, full `BlockKind`→`EUType` mapping (parametrized), `eu_id` scheme, verbatim citation (passage+page+bbox), structure_path carried, language stamped, partition + source_uri carried, acl carried opaque (object identity), acl defaults to None, empty/whitespace block skipped, empty doc → `[]`, deterministic
- [x] 1.2 Confirm red: `uv run pytest tests/evidence -q` fails to import `citenexus.evidence.builder`

## 2. Implementation (green)

- [x] 2.1 `src/citenexus/evidence/builder.py`: closed `_KIND_TO_TYPE` table + `build_evidence_units(doc, *, partition, language, acl=None)` mapping each non-empty block to one `EvidenceUnit` in order
- [x] 2.2 Build the bbox-faithful `Citation` and carry structure_path / language / partition / source_uri / opaque acl; leave embedding/checksum fields default
- [x] 2.3 Do NOT edit `evidence/__init__.py`; the builder is imported by full path

## 3. Verify (scoped)

- [x] 3.1 `uv run pytest tests/evidence -q` passes (incl. existing `test_unit.py`)
- [x] 3.2 `uv run ruff check src/citenexus/evidence tests/evidence` clean
- [x] 3.3 `uv run mypy src/citenexus/evidence tests/evidence` clean (strict)

## 4. Spec artifacts

- [x] 4.1 Author proposal, spec delta (4-hashtag scenarios), design, tasks
- [x] 4.2 `npx -y @fission-ai/openspec@latest validate evidence-builder` passes
