
from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import TYPE_CHECKING, NamedTuple

import anyio
import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from cosmos_retriever.cache import BoundedTTLCache
from cosmos_retriever.config import (
    RetrieverSettings,
    RuntimeConfig,
    ServerConfigUpdate,
    get_settings,
)
from cosmos_retriever.retriever import CosmosRetriever

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = structlog.get_logger("cosmos_retriever.server")


class RetrievalScope(NamedTuple):
    database: str | None
    container: str | None

    @classmethod
    def resolve(cls, settings: RetrieverSettings, database: str | None, container: str | None):
        # Container is optional: when unspecified, search the WHOLE database
        # (every searchable collection) via cross-collection mode ("*"). The
        # database is what the agent reasons about; a specific container is only
        # an optional narrowing override. Database has no default and is required.
        return cls(
            database=database or settings.cosmos_database,
            container=container or settings.cosmos_corpus_container or "*",
        )


class SearchRequest(BaseModel):

    query: str = Field(..., min_length=1, description="Natural-language information need.")
    max_documents: int = Field(
        default=20,
        ge=1,
        le=30,
        alias="maxDocuments",
        description="Cap on the number of curated documents to return.",
    )
    database: str | None = Field(
        default=None,
        description="Cosmos database name to query (required; selected per request).",
    )
    container: str | None = Field(
        default=None,
        description="Optional Cosmos container to narrow to; omit to search the whole database.",
    )
    overrides: RuntimeConfig | None = Field(
        default=None,
        description="Per-request runtime overrides (model endpoint, backend, turns, budgets, etc.).",
    )

    model_config = {"populate_by_name": True}


class _RetrieverPool:

    def __init__(self, settings: RetrieverSettings) -> None:
        self._settings = settings
        self._cache: BoundedTTLCache[tuple, CosmosRetriever] = BoundedTTLCache(
            max_entries=settings.cosmos_retriever_cache_max_entries,
            ttl_seconds=settings.cosmos_retriever_cache_ttl_seconds,
        )
        self._locks: dict[tuple, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._build_lock = asyncio.Lock()

    async def get(
        self,
        database: str | None,
        container: str | None,
        overrides: RuntimeConfig | None = None,
    ) -> tuple[CosmosRetriever, asyncio.Lock]:
        scope = RetrievalScope.resolve(self._settings, database, container)
        key: tuple = (scope, overrides.structural_key() if overrides is not None else None)
        retriever = self._cache.get(key)
        if retriever is None:
            async with self._build_lock:
                retriever = self._cache.get(key)
                if retriever is None:
                    retriever = await anyio.to_thread.run_sync(
                        lambda: self._build(scope, overrides)
                    )
                    self._cache.put(key, retriever)
        return retriever, self._locks[key]

    def stats(self) -> dict[str, object]:
        s = self._cache.stats()
        return {
            "entries": s.entries,
            "max_entries": s.max_entries,
            "ttl_seconds": s.ttl_seconds,
            "hits": s.hits,
            "misses": s.misses,
            "evictions": s.evictions,
            "expirations": s.expirations,
        }

    @property
    def settings(self) -> RetrieverSettings:
        return self._settings

    async def update_settings(self, new_settings: RetrieverSettings) -> None:
        """Swap the server-level settings and drop all cached retrievers so the
        next request rebuilds them with the new configuration. Rebuilds the
        cache itself if its sizing changed."""
        async with self._build_lock:
            size_changed = (
                new_settings.cosmos_retriever_cache_max_entries
                != self._settings.cosmos_retriever_cache_max_entries
                or new_settings.cosmos_retriever_cache_ttl_seconds
                != self._settings.cosmos_retriever_cache_ttl_seconds
            )
            self._settings = new_settings
            if size_changed:
                self._cache = BoundedTTLCache(
                    max_entries=new_settings.cosmos_retriever_cache_max_entries,
                    ttl_seconds=new_settings.cosmos_retriever_cache_ttl_seconds,
                )
            else:
                self._cache.clear()
            self._locks.clear()

    def _build(
        self, scope: RetrievalScope, overrides: RuntimeConfig | None
    ) -> CosmosRetriever:
        settings = self._settings.apply_structural_overrides(overrides)
        if settings is self._settings:
            settings = settings.model_copy(deep=True)
        if scope.database:
            settings.cosmos_database = scope.database
        return CosmosRetriever(settings=settings, corpus_name=scope.container)


def create_app(settings: RetrieverSettings | None = None) -> FastAPI:

    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.pool = _RetrieverPool(resolved)
        logger.info(
            "cosmos_retriever_server_started",
            host=resolved.host,
            port=resolved.port,
            default_container=resolved.cosmos_corpus_container,
        )
        yield

    app = FastAPI(
        title="Cosmos Retriever",
        version="0.1.0",
        description="HTTP service running the multi-turn Cosmos search agent.",
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health() -> dict[str, object]:
        pool: _RetrieverPool | None = getattr(app.state, "pool", None)
        return {"status": "ok", "retriever_cache": pool.stats() if pool is not None else {}}

    @app.get("/config")
    async def get_config() -> JSONResponse:
        pool: _RetrieverPool = app.state.pool
        return JSONResponse(
            content={"config": pool.settings.redacted_config(), "pool": pool.stats()}
        )

    @app.patch("/config")
    async def patch_config(update: ServerConfigUpdate) -> JSONResponse:
        pool: _RetrieverPool = app.state.pool
        try:
            new_settings = pool.settings.apply_server_updates(update)
        except Exception as exc:
            return JSONResponse(
                status_code=400,
                content={"error": str(exc), "type": type(exc).__name__},
            )
        await pool.update_settings(new_settings)
        changed = sorted(update.model_dump(exclude_none=True).keys())
        logger.info("server_config_updated", changed=changed)
        return JSONResponse(
            content={
                "status": "ok",
                "changed": changed,
                "config": new_settings.redacted_config(),
                "pool": pool.stats(),
            }
        )

    @app.post("/search")
    async def search(request: SearchRequest) -> JSONResponse:
        pool: _RetrieverPool = app.state.pool
        scope = RetrievalScope.resolve(pool.settings, request.database, request.container)
        if not scope.database:
            return JSONResponse(
                status_code=400,
                content={
                    "error": (
                        "Missing required field: database. The database must be "
                        "specified on each request (container is optional — omit "
                        "it to search the whole database)."
                    ),
                    "type": "ValueError",
                },
            )
        try:
            retriever, lock = await pool.get(
                request.database, request.container, request.overrides
            )
            async with lock:
                result = await anyio.to_thread.run_sync(
                    lambda: retriever.search(
                        request.query,
                        max_documents=request.max_documents,
                        overrides=request.overrides,
                    )
                )
        except Exception as exc:
            logger.error(
                "search_failed",
                query=request.query[:200],
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return JSONResponse(
                status_code=500,
                content={"error": str(exc), "type": type(exc).__name__},
            )
        return JSONResponse(content=asdict(result))

    return app
