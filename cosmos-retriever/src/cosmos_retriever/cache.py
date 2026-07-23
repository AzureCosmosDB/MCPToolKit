from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

K = TypeVar("K")
V = TypeVar("V")


@dataclass(frozen=True)
class CacheStats:
    entries: int
    max_entries: int
    ttl_seconds: float
    hits: int
    misses: int
    evictions: int
    expirations: int


class BoundedTTLCache(Generic[K, V]):
    def __init__(
        self,
        *,
        max_entries: int = 128,
        ttl_seconds: float = 900.0,
        time_source: Callable[[], float] = time.monotonic,
        on_evict: Callable[[K, V], None] | None = None,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")
        self._max = max_entries
        self._ttl = ttl_seconds
        self._now = time_source
        self._on_evict = on_evict
        self._lock = threading.RLock()
        self._data: OrderedDict[K, tuple[float, V]] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0

    def get(self, key: K) -> V | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return None
            stamp, value = entry
            if self._now() - stamp >= self._ttl:
                del self._data[key]
                self._expirations += 1
                self._misses += 1
                self._dispose(key, value)
                return None
            self._data.move_to_end(key)
            self._hits += 1
            return value

    def put(self, key: K, value: V) -> None:
        with self._lock:
            existing = self._data.get(key)
            if existing is not None:
                self._data[key] = (self._now(), value)
                self._data.move_to_end(key)
                if existing[1] is not value:
                    self._dispose(key, existing[1])
                return
            self._data[key] = (self._now(), value)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                old_key, (_, old_value) = self._data.popitem(last=False)
                self._evictions += 1
                self._dispose(old_key, old_value)

    def invalidate(self, key: K) -> bool:
        with self._lock:
            entry = self._data.pop(key, None)
            if entry is None:
                return False
            self._dispose(key, entry[1])
            return True

    def clear(self) -> None:
        with self._lock:
            items = list(self._data.items())
            self._data.clear()
        for key, (_, value) in items:
            self._dispose(key, value)

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(
                entries=len(self._data),
                max_entries=self._max,
                ttl_seconds=self._ttl,
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
                expirations=self._expirations,
            )

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def _dispose(self, key: K, value: V) -> None:
        if self._on_evict is None:
            return
        try:
            self._on_evict(key, value)
        except Exception:  # noqa: BLE001
            pass


__all__ = ["BoundedTTLCache", "CacheStats"]
