"""RetryPolicy — bounded attempts + pure exponential backoff (spec §5b)."""

from __future__ import annotations

from citenexus.worker import RetryPolicy


def test_backoff_delay_grows_exponentially() -> None:
    policy = RetryPolicy(max_attempts=5, base_delay=1.0, factor=2.0)
    assert policy.backoff_delay(1) == 1.0
    assert policy.backoff_delay(2) == 2.0
    assert policy.backoff_delay(3) == 4.0
    assert policy.backoff_delay(4) == 8.0


def test_backoff_delay_is_capped_by_max_delay() -> None:
    policy = RetryPolicy(max_attempts=10, base_delay=1.0, factor=2.0, max_delay=5.0)
    assert policy.backoff_delay(1) == 1.0
    assert policy.backoff_delay(4) == 5.0  # 8.0 capped to 5.0
    assert policy.backoff_delay(9) == 5.0


def test_backoff_delay_is_pure_no_side_effects() -> None:
    policy = RetryPolicy(max_attempts=3, base_delay=2.0, factor=3.0)
    assert policy.backoff_delay(2) == policy.backoff_delay(2) == 6.0


def test_should_retry_respects_bounded_attempts() -> None:
    policy = RetryPolicy(max_attempts=3, base_delay=1.0)
    assert policy.should_retry(1) is True
    assert policy.should_retry(2) is True
    assert policy.should_retry(3) is False  # attempts exhausted
    assert policy.should_retry(4) is False


def test_policy_is_frozen() -> None:
    policy = RetryPolicy(max_attempts=3, base_delay=1.0)
    try:
        policy.max_attempts = 9  # type: ignore[misc]
    except (TypeError, ValueError, AttributeError):
        return
    raise AssertionError("RetryPolicy must be immutable")
