"""Browse a Cosmos DB account and remember what each container can do.

This module is the single place the rest of the system asks "what databases and
containers exist, and what kind of search does this one support?". It talks to
Cosmos DB to list databases and containers, reads a container's settings when
asked, and hands back either the raw description or a ready made judgement of
which search strategies the container supports.

Because reading a container's settings is a network round trip, answers are
cached and shared. Each cached entry expires after a set time, and the cache
keeps only a fixed number of the most recently used containers so it never grows
without bound. The cache can be cleared or refreshed at any time, and every
operation on it is safe to call from multiple threads at once.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Protocol

from cosmos_retriever.retrieval.discovery.models import CapabilityProfile, ContainerMetadata
from cosmos_retriever.retrieval.discovery.profiler import (
    CapabilityProfiler,
    parse_container_metadata,
)


class _Connection(Protocol):
    def client(self) -> Any: ...


class ResourceCatalog:
    def __init__(
        self,
        connection: _Connection,
        *,
        ttl_seconds: float = 300.0,
        max_entries: int = 256,
        profiler: CapabilityProfiler | None = None,
    ) -> None:
        self._conn = connection
        self._ttl = ttl_seconds
        self._max = max_entries
        self._profiler = profiler or CapabilityProfiler()
        self._meta: OrderedDict[tuple[str, str], ContainerMetadata] = OrderedDict()
        self._lock = threading.RLock()

    def databases(self) -> list[str]:
        return [db["id"] for db in self._conn.client().list_databases()]

    def containers(self, database: str) -> list[str]:
        db = self._conn.client().get_database_client(database)
        return [c["id"] for c in db.list_containers()]

    def container_metadata(
        self, database: str, container: str, *, force: bool = False
    ) -> ContainerMetadata:
        key = (database, container)
        now = time.time()
        with self._lock:
            hit = self._meta.get(key)
            if hit is not None and not force and (now - hit.fetched_at) < self._ttl:
                self._meta.move_to_end(key)
                return hit

        props, etag = self._read_props(database, container)
        meta = parse_container_metadata(database, container, props, etag)

        with self._lock:
            self._meta[key] = meta
            self._meta.move_to_end(key)
            while len(self._meta) > self._max:
                self._meta.popitem(last=False)
        return meta

    def profile(self, database: str, container: str, *, force: bool = False) -> CapabilityProfile:
        return self._profiler.profile(
            self.container_metadata(database, container, force=force)
        )

    def refresh(self, database: str | None = None, container: str | None = None) -> None:
        with self._lock:
            if database is None:
                self._meta.clear()
            elif container is None:
                for k in [k for k in self._meta if k[0] == database]:
                    self._meta.pop(k, None)
            else:
                self._meta.pop((database, container), None)

    def invalidate(self, database: str, container: str) -> None:
        with self._lock:
            self._meta.pop((database, container), None)

    def cached_container_count(self) -> int:
        with self._lock:
            return len(self._meta)

    def _read_props(self, database: str, container: str) -> tuple[dict[str, Any], str | None]:
        c = self._conn.client().get_database_client(database).get_container_client(container)
        props = c.read()
        etag: str | None = None
        try:
            etag = c.client_connection.last_response_headers.get("etag")
        except Exception:
            etag = None
        return dict(props), etag
