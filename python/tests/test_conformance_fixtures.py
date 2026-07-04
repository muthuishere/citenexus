"""Drift guard for the cross-language conformance fixtures (SPEC-PORTS-v1 §10).

The committed files under ``conformance/`` are the contract that Go/TS/Rust
ports test against. This regenerates every fixture in-memory from the Python
reference internals and asserts the committed files match EXACTLY — so any
behavior change in a pinned algorithm or prompt forces a conscious
``uv run python scripts/gen_conformance.py`` (and a spec-version bump when the
change is intentional).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import cast

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "scripts" / "gen_conformance.py"
_CONFORMANCE = _REPO_ROOT.parent / "conformance"


def _regenerate() -> dict[str, str]:
    spec = importlib.util.spec_from_file_location("gen_conformance", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast("dict[str, str]", module.generate())


def test_committed_fixtures_match_regeneration() -> None:
    fixtures = _regenerate()
    assert fixtures, "generator produced no fixtures"
    for rel_path, expected_text in fixtures.items():
        path = _CONFORMANCE / rel_path
        assert path.is_file(), f"missing committed fixture: conformance/{rel_path}"
        actual = path.read_text(encoding="utf-8")
        assert actual == expected_text, (
            f"conformance/{rel_path} is stale — behavior drifted from the committed "
            "contract. If intentional, regenerate with "
            "`uv run python scripts/gen_conformance.py` and review the diff."
        )


def test_no_orphan_fixture_files() -> None:
    """Every committed JSON fixture must be produced by the generator."""
    generated = set(_regenerate())
    committed = {str(p.relative_to(_CONFORMANCE)) for p in _CONFORMANCE.rglob("*.json")}
    assert committed == generated
