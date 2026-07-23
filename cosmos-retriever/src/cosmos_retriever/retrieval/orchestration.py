from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import NamedTuple

import structlog

from cosmos_retriever.retrieval.models import (
    GrepRequest,
    NormalizedDocument,
    ReadDocumentRequest,
    RetrievedItem,
    SearchRequest,
)
from cosmos_retriever.retrieval.retriever import CorpusRetriever

logger = structlog.get_logger("cosmos_retriever.orchestration")

RRF_K = 60


class ContainerTarget(NamedTuple):
    database: str
    container: str


RetrieverResolver = Callable[[ContainerTarget], CorpusRetriever]


@dataclass
class MultiSearchResult:
    items: list[RetrievedItem]
    searched: list[ContainerTarget] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    per_container_counts: dict[str, int] = field(default_factory=dict)
    elapsed_s: float = 0.0


def _qualify(target: ContainerTarget, item: RetrievedItem) -> str:
    return f"{target.database}/{target.container}:{item.item_id}"


def fuse_rrf(
    ranked_lists: Sequence[tuple[ContainerTarget, list[RetrievedItem]]],
    *,
    k: int = RRF_K,
    limit: int | None = None,
) -> list[RetrievedItem]:
    scores: dict[str, float] = {}
    chosen: dict[str, RetrievedItem] = {}
    for target, items in ranked_lists:
        for position, item in enumerate(items):
            key = _qualify(target, item)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + position)
            if key not in chosen:
                tagged = item.model_copy(deep=True)
                tagged.metadata = {
                    **tagged.metadata,
                    "container": target.container,
                    "database": target.database,
                }
                chosen[key] = tagged
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    fused: list[RetrievedItem] = []
    for rank, (key, score) in enumerate(ordered):
        item = chosen[key]
        item.rank = rank
        item.raw_scores = {**item.raw_scores, "rrf": score}
        fused.append(item)
        if limit is not None and len(fused) >= limit:
            break
    return fused


class MultiContainerRetriever:
    def __init__(
        self,
        resolver: RetrieverResolver,
        *,
        max_workers: int = 8,
    ) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        self._resolve = resolver
        self._max_workers = max_workers

    def search(
        self,
        targets: Sequence[ContainerTarget],
        request: SearchRequest,
        *,
        per_container_limit: int | None = None,
        final_limit: int | None = None,
    ) -> MultiSearchResult:
        targets = list(dict.fromkeys(targets))
        if not targets:
            return MultiSearchResult(items=[])

        per_request = request
        if per_container_limit is not None:
            per_request = request.model_copy(update={"limit": per_container_limit})

        start = time.perf_counter()
        result = MultiSearchResult(items=[])
        ranked_lists: list[tuple[ContainerTarget, list[RetrievedItem]]] = []

        workers = min(self._max_workers, len(targets))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self._search_one, target, per_request): target
                for target in targets
            }
            for future in futures:
                target = futures[future]
                label = f"{target.database}/{target.container}"
                try:
                    items = future.result()
                except Exception as exc:  # noqa: BLE001
                    result.errors[label] = f"{type(exc).__name__}: {exc}"
                    logger.warning(
                        "container_search_failed",
                        database=target.database,
                        container=target.container,
                        error=str(exc),
                    )
                    continue
                result.searched.append(target)
                result.per_container_counts[label] = len(items)
                ranked_lists.append((target, items))

        result.items = fuse_rrf(ranked_lists, limit=final_limit)
        result.elapsed_s = round(time.perf_counter() - start, 3)
        return result

    def _search_one(
        self, target: ContainerTarget, request: SearchRequest
    ) -> list[RetrievedItem]:
        retriever = self._resolve(target)
        return retriever.search(request)


def select_search_targets(
    catalog,
    database: str,
    *,
    containers: Sequence[str] | None = None,
    require_capability: bool = True,
) -> list[ContainerTarget]:
    names = list(containers) if containers is not None else catalog.containers(database)
    targets: list[ContainerTarget] = []
    for name in names:
        if require_capability:
            profile = catalog.profile(database, name)
            if not (profile.can_full_text.value or profile.can_vector.value):
                continue
        targets.append(ContainerTarget(database=database, container=name))
    return targets


class CrossCollectionRetriever:
    """Duck-types the ``CorpusRetriever`` interface (``schema`` / ``search`` /
    ``grep_candidates`` / ``read_document``) but fans every operation out across
    all target collections of a database and fuses the hits with RRF. Drops in
    wherever a single-container ``CorpusRetriever`` is expected (e.g. the agent
    ``ToolSet``)."""

    def __init__(
        self,
        targets: Sequence[ContainerTarget],
        retrievers: dict[ContainerTarget, CorpusRetriever],
        *,
        per_container_limit: int | None = None,
        max_workers: int = 16,
    ) -> None:
        targets = list(dict.fromkeys(targets))
        if not targets:
            raise ValueError("CrossCollectionRetriever requires at least one target")
        self._targets = targets
        self._retrievers = retrievers
        self._per_container = per_container_limit
        self._max_workers = max(1, min(max_workers, len(targets)))
        self._mcr = MultiContainerRetriever(
            lambda t: self._retrievers[t], max_workers=self._max_workers
        )
        # Representative schema so the tools can build their JSON tool schema.
        self.schema = retrievers[targets[0]].schema

    def search(self, request: SearchRequest) -> list[RetrievedItem]:
        # Track the fused output depth (final_limit) by default: truncating a
        # collection below what fusion can keep silently drops recoverable gold
        # docs that rank between per_container_limit and final_limit within
        # their own collection. An explicit per_container_limit still overrides.
        per_container = self._per_container if self._per_container is not None else request.limit
        result = self._mcr.search(
            self._targets,
            request,
            per_container_limit=per_container,
            final_limit=request.limit,
        )
        return result.items

    def grep_candidates(self, request: GrepRequest) -> list[RetrievedItem]:
        out: list[RetrievedItem] = []
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = [
                pool.submit(self._retrievers[t].grep_candidates, request)
                for t in self._targets
            ]
            for fut in futures:
                try:
                    out.extend(fut.result())
                except Exception as exc:  # noqa: BLE001
                    logger.warning("cross_grep_failed", error=str(exc))
        return out[: request.candidate_limit]

    def read_document(self, request: ReadDocumentRequest) -> NormalizedDocument:
        # A document id can live in any collection; probe until one yields text.
        first: NormalizedDocument | None = None
        for target in self._targets:
            try:
                doc = self._retrievers[target].read_document(request)
            except Exception:  # noqa: BLE001
                continue
            if first is None:
                first = doc
            if doc.assembled.strip():
                return doc
        if first is not None:
            return first
        return self._retrievers[self._targets[0]].read_document(request)


__all__ = [
    "ContainerTarget",
    "CrossCollectionRetriever",
    "MultiContainerRetriever",
    "MultiSearchResult",
    "RRF_K",
    "RetrieverResolver",
    "fuse_rrf",
    "select_search_targets",
]
