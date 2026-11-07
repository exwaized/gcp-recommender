"""
Minimal in-memory fixed-window rate limiter, keyed per client.
Per-process: with N containers the effective limit is N x the configured value.
Put a shared limiter (Caddy plugin / OCI WAF) in front if you need a global cap.
"""
import time


class RateLimiter:
    def __init__(self, limit: int, window_s: float = 60.0, max_keys: int = 10_000):
        self.limit = limit
        self.window_s = window_s
        self.max_keys = max_keys
        self._hits: dict[str, tuple[float, int]] = {}

    def allow(self, key: str, now: float | None = None) -> bool:
        if self.limit <= 0:
            return True
        now = time.monotonic() if now is None else now
        start, count = self._hits.get(key, (now, 0))
        if now - start >= self.window_s:
            start, count = now, 0
        if count >= self.limit:
            return False
        self._hits[key] = (start, count + 1)
        if len(self._hits) > self.max_keys:
            self._evict(now)
        return True

    def _evict(self, now: float):
        self._hits = {k: v for k, v in self._hits.items() if now - v[0] < self.window_s}
        if len(self._hits) > self.max_keys:  # still too many live keys: drop oldest half
            for k in sorted(self._hits, key=lambda k: self._hits[k][0])[: len(self._hits) // 2]:
                del self._hits[k]
