from __future__ import annotations

from collections import defaultdict, deque
from threading import Lock
import time


class UploadRateLimiter:
    def __init__(
        self,
        *,
        max_requests: int,
        window_seconds: int,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, *, now: float | None = None) -> bool:
        if self.max_requests == 0:
            return True
        timestamp = time.monotonic() if now is None else now
        cutoff = timestamp - self.window_seconds
        with self._lock:
            requests = self._requests[key]
            while requests and requests[0] <= cutoff:
                requests.popleft()
            if len(requests) >= self.max_requests:
                return False
            requests.append(timestamp)
            return True
