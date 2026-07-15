from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from cosmos_retriever.retrieval.capabilities import RetrievalCapabilities
from cosmos_retriever.retrieval.compiler import CosmosQueryCompiler
from cosmos_retriever.retrieval.errors import (
    CrossPartitionQueryDisabled,
    UnboundedScanRejected,
)
from cosmos_retriever.retrieval.executor import CosmosExecutor
from cosmos_retriever.retrieval.models import (
    GrepRequest,
    PartitionQueryPolicy,
    RetrievedItem,
    SearchRequest,
)
from cosmos_retriever.retrieval.normalization import normalize_rows
from cosmos_retriever.retrieval.schema import CorpusSchema


@dataclass
class RetrievalContext:
    schema: CorpusSchema
    compiler: CosmosQueryCompiler
    executor: CosmosExecutor
    capabilities: RetrievalCapabilities
    policy: PartitionQueryPolicy


def _resolve_cross_partition(req_partition_key, policy: PartitionQueryPolicy) -> bool:
    """Return whether the query must run cross-partition, or raise if disallowed."""

    if req_partition_key is not None:
        return False
    if not policy.allow_cross_partition_search:
        raise CrossPartitionQueryDisabled(
            "search requires a partition key or cross-partition permission"
        )
    return True



class SearchStrategy(ABC):
    name: str = ""
    requires_embedding: bool = False

    @abstractmethod
    def execute(self, req: SearchRequest, ctx: RetrievalContext) -> list[RetrievedItem]: ...


class NativeHybridStrategy(SearchStrategy):
    name = "native_hybrid"
    requires_embedding = True

    def execute(self, req: SearchRequest, ctx: RetrievalContext) -> list[RetrievedItem]:
        vector_path = ctx.schema.resolve_vector_field(req.vector_field)
        text_paths = ctx.schema.resolve_text_fields(req.text_fields)
        cross = _resolve_cross_partition(req.partition_key, ctx.policy)
        compiled = ctx.compiler.compile_hybrid(
            query=req.query,
            query_vector=req.query_vector or [],
            limit=req.limit,
            ignored_item_ids=req.ignored_item_ids,
            filters=req.filters,
            partition_key=req.partition_key,
            cross_partition=cross,
            vector_path=vector_path,
            text_paths=text_paths,
        )
        rows = ctx.executor.run(compiled)
        return normalize_rows(
            rows,
            strategy=self.name,
            channels=["vector", "full_text"],
            projected_aliases=compiled.projected_aliases,
            queried_text_fields=req.text_fields,
            primary_text_field=ctx.schema.primary_text_field_name(),
        )


class VectorSearchStrategy(SearchStrategy):
    name = "vector"
    requires_embedding = True

    def execute(self, req: SearchRequest, ctx: RetrievalContext) -> list[RetrievedItem]:
        vector_path = ctx.schema.resolve_vector_field(req.vector_field)
        cross = _resolve_cross_partition(req.partition_key, ctx.policy)
        compiled = ctx.compiler.compile_vector(
            query_vector=req.query_vector or [],
            limit=req.limit,
            ignored_item_ids=req.ignored_item_ids,
            filters=req.filters,
            partition_key=req.partition_key,
            cross_partition=cross,
            vector_path=vector_path,
        )
        rows = ctx.executor.run(compiled)
        return normalize_rows(
            rows,
            strategy=self.name,
            channels=["vector"],
            projected_aliases=compiled.projected_aliases,
            primary_text_field=ctx.schema.primary_text_field_name(),
        )


class FullTextSearchStrategy(SearchStrategy):
    name = "full_text"
    requires_embedding = False

    def execute(self, req: SearchRequest, ctx: RetrievalContext) -> list[RetrievedItem]:
        text_paths = ctx.schema.resolve_text_fields(req.text_fields)
        cross = _resolve_cross_partition(req.partition_key, ctx.policy)
        compiled = ctx.compiler.compile_full_text(
            query=req.query,
            limit=req.limit,
            ignored_item_ids=req.ignored_item_ids,
            filters=req.filters,
            partition_key=req.partition_key,
            cross_partition=cross,
            text_paths=text_paths,
        )
        rows = ctx.executor.run(compiled)
        return normalize_rows(
            rows,
            strategy=self.name,
            channels=["full_text"],
            projected_aliases=compiled.projected_aliases,
            queried_text_fields=req.text_fields,
            primary_text_field=ctx.schema.primary_text_field_name(),
        )


class ClientSideFusionStrategy(SearchStrategy):

    name = "client_fusion"
    requires_embedding = True
    _RRF_K = 60

    def execute(self, req: SearchRequest, ctx: RetrievalContext) -> list[RetrievedItem]:
        vector_hits = VectorSearchStrategy().execute(req, ctx)
        fts_hits = FullTextSearchStrategy().execute(req, ctx)
        scores: dict[str, float] = {}
        channels: dict[str, list[str]] = {}
        item_by_id: dict[str, RetrievedItem] = {}
        for hits, channel in ((vector_hits, "vector"), (fts_hits, "full_text")):
            for rank, item in enumerate(hits):
                scores[item.item_id] = scores.get(item.item_id, 0.0) + 1.0 / (self._RRF_K + rank)
                channels.setdefault(item.item_id, []).append(channel)
                item_by_id.setdefault(item.item_id, item)
        ranked_ids = sorted(scores, key=lambda i: scores[i], reverse=True)[: req.limit]
        out: list[RetrievedItem] = []
        for rank, item_id in enumerate(ranked_ids):
            base = item_by_id[item_id]
            out.append(
                base.model_copy(
                    update={
                        "rank": rank,
                        "retrieval_strategy": self.name,
                        "retrieval_channels": channels[item_id],
                        "raw_scores": {"rrf": scores[item_id]},
                    }
                )
            )
        return out


class BoundedScanStrategy(SearchStrategy):
    

    name = "bounded_scan"
    requires_embedding = False

    def execute(self, req: SearchRequest, ctx: RetrievalContext) -> list[RetrievedItem]:
        if not ctx.policy.allow_bounded_scan:
            raise UnboundedScanRejected("bounded scan is not enabled")
        cross = _resolve_cross_partition(req.partition_key, ctx.policy)
        compiled = ctx.compiler.compile_structured(
            limit=req.limit,
            filters=req.filters,
            ignored_item_ids=req.ignored_item_ids,
            partition_key=req.partition_key,
            cross_partition=cross,
        )
        compiled.warnings.append("bounded scan active")
        rows = ctx.executor.run(compiled)
        return normalize_rows(rows, strategy=self.name)



class GrepCandidateStrategy(ABC):
    @abstractmethod

    def candidates(self, req: GrepRequest, ctx: RetrievalContext) -> list[RetrievedItem]: ...


class FullTextGrepCandidateStrategy(GrepCandidateStrategy):
    

    def candidates(self, req: GrepRequest, ctx: RetrievalContext) -> list[RetrievedItem]:
        from cosmos_retriever.retrieval.expressions import tokenize_for_fts

        if not tokenize_for_fts(req.pattern):
            return []
        text_paths = ctx.schema.resolve_text_fields(
            [req.text_field] if req.text_field else None
        )
        cross = _resolve_cross_partition(req.partition_key, ctx.policy)
        compiled = ctx.compiler.compile_full_text(
            query=req.pattern,
            limit=req.candidate_limit,
            ignored_item_ids=[],
            filters=req.filters,
            partition_key=req.partition_key,
            cross_partition=cross,
            text_paths=text_paths,
            strategy="grep_full_text",
        )
        rows = ctx.executor.run(compiled)
        return normalize_rows(
            rows,
            strategy="grep_full_text",
            channels=["full_text"],
            projected_aliases=compiled.projected_aliases,
            queried_text_fields=[req.text_field] if req.text_field else None,
            primary_text_field=ctx.schema.primary_text_field_name(),
        )
