## 1. Tests first (red)

- [x] 1.1 `tests/provenance/test_stamp.py`: a `ProducedBy` with all five stage
      stamps serializes to JSON and parses back equal (round-trip); each stage
      exposes `plugin` + `plugin_version`.
- [x] 1.2 `tests/provenance/test_rebuild_planner.py`: identical current-vs-stamp ⇒
      `plan()` returns an empty set (idempotent).
- [x] 1.3 `tests/provenance/test_rebuild_planner.py`: a parametrized test encoding
      the §4c matrix — one case per row, asserting both the rebuilt set AND the
      untouched set:
      - embedding-swap ⇒ `{embedding}`; not OCR/vision/eu/graph/community.
      - vision-swap ⇒ includes `{vision, eu, embedding}`; not text-only eu/graph of
        unaffected docs (modelled at layer granularity).
      - chunker-swap ⇒ `{eu, embedding, structure, graph, community}`; not
        extract/ocr.
      - graph-extractor-swap ⇒ `{graph, community}`; not eu/embedding/structure.
      - reranker/LLM-swap ⇒ empty set.
- [x] 1.4 `tests/provenance/test_rebuild_planner.py`: DAG property — changing an
      upstream stage marks all downstream layers stale and no upstream layer.

## 2. Implement (green)

- [x] 2.1 `src/trustrag/provenance/stamp.py`: `from __future__ import annotations`;
      `StageStamp`, `ProducedBy`, `ModelManifest` pydantic v2 models (frozen),
      `endpoint_model`/`dim` optional.
- [x] 2.2 `src/trustrag/provenance/rebuild_planner.py`: `Layer` enum; the DAG
      adjacency map + downstream-closure helper; the stage→seed-layer map (reranker/
      LLM → none); `plan(current, stamp) -> set[Layer]` doing diff → seed → closure.
- [x] 2.3 `src/trustrag/provenance/__init__.py`: export the stamp models + `plan`/`Layer`.

## 3. Verify

- [ ] 3.1 `task check` green (ruff + mypy --strict + unit tests).
- [ ] 3.2 `npx -y @fission-ai/openspec@latest validate provenance-and-rebuild` passes
      and `status` shows all artifacts done.
