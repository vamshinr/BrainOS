from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar


T = TypeVar("T")


class SlackRateLimitError(RuntimeError):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


def with_backoff(fn: Callable[[], T], attempts: int = 3, base_delay: float = 1.0) -> T:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except SlackRateLimitError as e:
            last_error = e
            if attempt == attempts - 1:
                break
            time.sleep(e.retry_after or base_delay * (2 ** attempt))
    if last_error:
        raise last_error
    raise RuntimeError("Slack MCP call failed before execution.")

