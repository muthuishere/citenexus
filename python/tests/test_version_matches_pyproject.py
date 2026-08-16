"""`citenexus.__version__` must equal pyproject's version.

It had drifted to "0.2.0" while the package shipped 0.9.0 on PyPI, and was caught
by eye one commit before tagging 0.10.0 — not by anything that would fail. A
released package that misreports its own version is a debugging trap: a user
pasting `citenexus.__version__` into an issue sends you to the wrong source.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import citenexus

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_dunder_version_matches_pyproject() -> None:
    declared = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
    assert citenexus.__version__ == declared
