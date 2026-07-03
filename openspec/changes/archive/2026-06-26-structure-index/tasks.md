## 1. Tests first (red)

- [x] 1.1 Write `tests/evidence/test_structure.py`: heading_tree → nested nodes with correct parent links (incl. level-3→level-2 re-parent), heading node `eu_ref` resolves to `document_id::order`, `none` → zero nodes (no error), heading_tree with no headings → zero nodes, slide_sequence → one flat node per slide in order, uniform node shape across types, `StructureIndex` is frozen
- [x] 1.2 Confirm red: `uv run pytest tests/evidence -q` fails to import `citenexus.evidence.structure`

## 2. Implementation (green)

- [x] 2.1 `src/citenexus/evidence/structure.py`: frozen `StructureNode` (node_id, parent_id, label, kind, eu_ref) + frozen `StructureIndex` (document_id, structure_type, nodes)
- [x] 2.2 `build_structure(doc)` dispatch: `_heading_tree` (level-stack nesting), `_slide_sequence` (flat, in order); every other type → zero nodes
- [x] 2.3 Anchor each node `eu_ref` to `document_id::order`; do NOT edit `evidence/__init__.py` (import by full path)

## 3. Verify (scoped)

- [x] 3.1 `uv run pytest tests/evidence -q` passes (incl. existing `test_unit.py`)
- [x] 3.2 `uv run ruff check src/citenexus/evidence tests/evidence` clean
- [x] 3.3 `uv run mypy src/citenexus/evidence tests/evidence` clean (strict)

## 4. Spec artifacts

- [x] 4.1 Author proposal, spec delta (4-hashtag scenarios), design, tasks
- [x] 4.2 `npx -y @fission-ai/openspec@latest validate structure-index` passes
