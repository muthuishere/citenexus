"""Python-side BINDING assertions for the cross-port conformance vectors.

``tests/test_conformance_fixtures.py`` is a *drift guard*: it re-derives every
fixture by calling the same reference internals that generated it, so it can
catch a STALE file but never a WRONG verdict, and it cannot notice a file that
shrank (the generator would shrink with it). Go and JS, by contrast, read the
committed JSON as opaque data — which is why they, not Python, have been the
only ports genuinely held to the contract.

Every module here reads a committed case file as opaque data, pins its vector
COUNT in an ``EXPECTED_COUNTS`` constant, and asserts each vector against the
shipped public API. Same shape as ``tests/answer/test_conflict_conformance.py``,
``golang/answer/conflict_test.go`` and ``js/src/answer/conflict.test.ts``.
"""
