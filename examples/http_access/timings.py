"""SPDX-License-Identifier: Apache-2.0. Optional local phase observations.

Scopes overlap and run concurrently: their sums are not a wall-time breakdown.
No request contents, credentials or keys are retained.
"""

from collections import defaultdict
from contextlib import contextmanager
import math
import threading
import time


class Timings:
    def __init__(self, enabled=False):
        self.enabled = enabled
        self.lock = threading.Lock()
        self.values = defaultdict(list)

    @contextmanager
    def phase(self, name):
        if not self.enabled:
            yield
            return
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = (time.perf_counter() - start) * 1000
            with self.lock:
                self.values[name].append(elapsed)

    def reset(self):
        with self.lock:
            self.values.clear()

    def snapshot(self):
        with self.lock:
            return {name: {"count": len(values), "total_ms": sum(values),
                           "p50_ms": sorted(values)[math.ceil(.5 * len(values)) - 1],
                           "p95_ms": sorted(values)[math.ceil(.95 * len(values)) - 1],
                           "max_ms": max(values)} for name, values in sorted(self.values.items())}
