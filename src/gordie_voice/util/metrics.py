"""Simple latency and counter metrics tracker."""

from __future__ import annotations

import time

import structlog

log = structlog.get_logger()


class MetricsTracker:
    """Tracks per-stage latencies and event counters for each interaction."""

    def __init__(self) -> None:
        self._start_time: float = 0.0
        self._marks: dict[str, float] = {}
        self._counters: dict[str, int] = {}

    def start_interaction(self) -> None:
        self._start_time = time.monotonic()
        self._marks.clear()

    def mark(self, stage: str) -> None:
        elapsed_ms = (time.monotonic() - self._start_time) * 1000
        self._marks[stage] = elapsed_ms
        log.info("metric_mark", stage=stage, elapsed_ms=round(elapsed_ms, 1))

    def increment(self, counter: str) -> None:
        self._counters[counter] = self._counters.get(counter, 0) + 1

    def get_latencies(self) -> dict[str, float]:
        return dict(self._marks)

    def get_counters(self) -> dict[str, int]:
        return dict(self._counters)
