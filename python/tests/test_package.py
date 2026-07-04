"""Toolchain smoke test — proves the package imports and the harness runs."""

import citenexus


def test_version_exposed() -> None:
    assert citenexus.__version__ == "0.2.0"
