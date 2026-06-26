## 1. Tests first (red)

- [x] 1.1 Write `tests/access/test_scope.py`: full→leaf, partial→prefix, root-only, empty→root, prefix-of-descendant, gap rejected, unknown key rejected
- [x] 1.2 Write `tests/access/test_prefilter.py`: exact allow, descendant-of-prefix allowed, sibling rejected, ancestor-not-allowed, empty set deny-all, `filter_partitions` order-preserving + union, acl predicate filters, default-no-predicate keeps all, acl never parsed (opaque object identity)
- [x] 1.3 Confirm red: `uv run pytest tests/access -q` fails to import the new module

## 2. Implementation (green)

- [x] 2.1 `src/trustrag/access/scope.py`: `resolve_scope(scope, hierarchy)` → contiguous-prefix `PartitionPath`, rejecting gaps and unknown keys
- [x] 2.2 `src/trustrag/access/prefilter.py`: `allowed_partition`, `filter_partitions`, `apply_acl_predicate` (opaque acl, optional predicate)
- [x] 2.3 `src/trustrag/access/__init__.py`: export the four public callables

## 3. Verify (scoped)

- [x] 3.1 `uv run pytest tests/access -q` passes
- [x] 3.2 `uv run ruff check src/trustrag/access tests/access` clean
- [x] 3.3 `uv run mypy src/trustrag/access tests/access` clean (strict)

## 4. Spec artifacts

- [x] 4.1 Author proposal, spec deltas (4-hashtag scenarios), design, tasks
- [x] 4.2 `npx -y @fission-ai/openspec@latest validate access-prefilter` passes
