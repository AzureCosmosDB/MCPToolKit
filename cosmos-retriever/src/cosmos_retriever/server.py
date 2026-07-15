
from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import TYPE_CHECKING

import anyio
import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from cosmos_retriever.config import RetrieverSettings, get_settings
from cosmos_retriever.retriever import CosmosRetriever

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = structlog.get_logger("cosmos_retriever.server")


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
        description="Override Cosmos database name (else COSMOS_DATABASE env var).",
    )
    container: str | None = Field(
        default=None,
        description="Override Cosmos corpus container name (else COSMOS_CORPUS_CONTAINER).",
    )

    model_config = {"populate_by_name": True}


class _RetrieverPool:

    def __init__(self, settings: RetrieverSettings) -> None:
        self._settings = settings
        self._retrievers: dict[tuple[str | None, str | None], CosmosRetriever] = {}
        self._locks: dict[tuple[str | None, str | None], asyncio.Lock] = defaultdict(asyncio.Lock)
        self._build_lock = asyncio.Lock()

    async def get(
        self, database: str | None, container: str | None
    ) -> tuple[CosmosRetriever, asyncio.Lock]:
        key = (database, container)
        retriever = self._retrievers.get(key)
        if retriever is None:
            async with self._build_lock:
                retriever = self._retrievers.get(key)
                if retriever is None:
                    retriever = await anyio.to_thread.run_sync(
                        lambda: self._build(database, container)
                    )
                    self._retrievers[key] = retriever
        return retriever, self._locks[key]

    def _build(self, database: str | None, container: str | None) -> CosmosRetriever:
        settings = self._settings.model_copy(deep=True)
        if database:
            settings.cosmos_database = database
        return CosmosRetriever(settings=settings, corpus_name=container)


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
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/search")
    async def search(request: SearchRequest) -> JSONResponse:
        pool: _RetrieverPool = app.state.pool
        try:
            retriever, lock = await pool.get(request.database, request.container)
            async with lock:
                result = await anyio.to_thread.run_sync(
                    lambda: retriever.search(
                        request.query, max_documents=request.max_documents
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
