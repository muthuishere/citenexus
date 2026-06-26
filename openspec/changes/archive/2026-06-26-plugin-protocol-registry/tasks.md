## 1. Tests first (red)

- [x] 1.1 `tests/plugins/test_base.py`: assert all 11 protocol classes import, are
      abstract (direct instantiation raises `TypeError`), and that a subclass
      omitting the contract method cannot instantiate.
- [x] 1.2 `tests/plugins/test_base.py`: assert a concrete plugin exposes a
      non-empty `plugin_version`.
- [x] 1.3 `tests/plugins/test_registry.py`: conforming plugin registers and
      `resolve(Protocol)` returns it; non-conforming object is rejected (raises).
- [x] 1.4 `tests/plugins/test_registry.py`: re-registering a single-slot stage
      replaces it (last-wins); `register_retriever` keeps a set with both, in
      order.
- [x] 1.5 `tests/plugins/test_registry.py`: `use()` routes a retriever to the
      fusion set and a single-slot plugin to its slot; missing/empty
      `plugin_version` is rejected; an object matching two protocols is rejected.
- [x] 1.6 `tests/plugins/test_registry.py`: a "built-in" default registers via the
      same `use()`/`register_*` API and resolves identically.

## 2. Implement (green)

- [x] 2.1 `src/trustrag/plugins/base.py`: `from __future__ import annotations`;
      common `Plugin` ABC with `plugin_version`; the 11 protocol ABCs with their
      abstract contract methods (signatures per the spec). `RetrieverPlugin`
      limited to returning ranked candidates — no fusion/grounding hook.
- [x] 2.2 `src/trustrag/plugins/registry.py`: `PluginRegistry` with the
      single-slot dict + retriever fusion list; `register_plugin`,
      `register_retriever`, `resolve`, and `use(plugin)` type-dispatch; enforce
      type-conformance and non-empty `plugin_version`; reject multi-protocol
      objects.
- [x] 2.3 `src/trustrag/plugins/__init__.py`: export the protocols + registry.

## 3. Verify

- [ ] 3.1 `task check` green (ruff + mypy --strict + unit tests).
- [ ] 3.2 `npx -y @fission-ai/openspec@latest validate --change plugin-protocol-registry` (if available) and `status` shows artifacts done.
