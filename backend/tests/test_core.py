import pytest

from app.core.rate_limit import RateLimiter
from app.core.security import generate_session_token, hash_pin, verify_pin


def test_pin_hash_and_verify():
    hashed = hash_pin("123456")
    assert hashed != "123456"
    assert verify_pin("123456", hashed)
    assert not verify_pin("123457", hashed)


@pytest.mark.parametrize("pin", ["", "12345", "1234567", "abcdef", "12 4567"])
def test_invalid_pin_rejected(pin):
    with pytest.raises(ValueError):
        hash_pin(pin)


def test_session_token_is_opaque_and_unique():
    a, b = generate_session_token(), generate_session_token()
    assert len(a) >= 32
    assert a != b


def test_rate_limiter_locks_after_failures_and_resets():
    limiter = RateLimiter(max_failures=3, window_seconds=60, lockout_seconds=30)
    key = "client-a"
    assert limiter.allow(key)
    limiter.record_failure(key)
    limiter.record_failure(key)
    limiter.record_failure(key)
    assert not limiter.allow(key)
    limiter.reset(key)
    assert limiter.allow(key)
