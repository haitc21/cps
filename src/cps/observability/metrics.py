"""Small dependency-free metrics registry for operational probes."""

from __future__ import annotations

from collections import Counter
from threading import Lock


class MetricsRegistry:
    """Process-local counters; deployment can scrape or aggregate them externally."""

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()
        self._lock = Lock()

    def increment(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counts[name] += amount

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)

    def render_prometheus(self) -> str:
        values = self.snapshot()
        return "".join(f"{name} {values[name]}\n" for name in sorted(values))


metrics = MetricsRegistry()
