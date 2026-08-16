"""Toolchain smoke test — proves the package imports and the harness runs."""

import citenexus


def test_version_exposed() -> None:
    """The package exposes a version at all.

    This used to assert the literal "0.2.0", which is why __version__ stayed at
    0.2.0 through eight releases: the test was pinning the drift rather than
    catching it. A hardcoded expected version can only ever be right once.
    The real check -- that it equals pyproject's version -- lives in
    tests/test_version_matches_pyproject.py.
    """
    assert isinstance(citenexus.__version__, str)
    assert citenexus.__version__.count(".") == 2
