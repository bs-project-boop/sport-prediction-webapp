from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


@dataclass
class _Bucket:
    failures: int = 0
    first_failure: datetime | None = None
    locked_until: datetime | None = None


class RateLimiter:
    def __init__(self, max_failures: int = 5, window_seconds: int = 300, lockout_seconds: int = 300):
        self.max_failures = max_failures
        self.window = timedelta(seconds=window_seconds)
        self.lockout = timedelta(seconds=lockout_seconds)
        self._buckets: dict[str, _Bucket] = {}

    def allow(self, key: str) -> bool:
        now = datetime.now(timezone.utc)
        bucket = self._buckets.get(key)
        if not bucket:
            return True
        if bucket.locked_until and bucket.locked_until > now:
            return False
        if bucket.first_failure and now - bucket.first_failure > self.window:
            self.reset(key)
        return True

    def record_failure(self, key: str) -> None:
        now = datetime.now(timezone.utc)
        bucket = self._buckets.setdefault(key, _Bucket())
        if not bucket.first_failure or now - bucket.first_failure > self.window:
            bucket.failures = 0
            bucket.first_failure = now
        bucket.failures += 1
        if bucket.failures >= self.max_failures:
            bucket.locked_until = now + self.lockout

    def reset(self, key: str) -> None:
        self._buckets.pop(key, None)
