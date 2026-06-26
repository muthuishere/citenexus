"""Toolchain smoke test — proves the package imports and the harness runs."""

import trustrag


def test_version_exposed() -> None:
    assert trustrag.__version__ == "0.0.0"
