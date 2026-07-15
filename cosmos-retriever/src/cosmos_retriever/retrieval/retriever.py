


from __future__ import annotations

import structlog

from cosmos_retriever.retrieval.capabilities import RetrievalCapabilities
from cosmos_retriever.retrieval.compiler import CosmosQueryCompiler
from cosmos_retriever.retrieval.document_resolvers import build_document_resolver
from cosmos_retriever.retrieval.embedding import QueryEmbedder
from cosmos_retriever.retrieval.executor import CosmosExecutor
from cosmos_retriever.retrieval.models import (
    GrepRequest,
    NormalizedDocument,
    PartitionQueryPolicy,
    ReadDocumentRequest,
    RetrievedItem,
    SearchRequest,
)
from cosmos_retriever.retrieval.planner import RetrievalPlanner
from cosmos_retriever.retrieval.schema import CorpusSchema
from cosmos_retriever.retrieval.strategies import RetrievalContext

logger = structlog.get_logger("cosmos_retriever.retrieval.retriever")


class CorpusRetriever:
    def __init__(
        self,
        *,
        container,
        schema: CorpusSchema,
        capabilities: RetrievalCapabilities,
        query_embedder: QueryEmbedder | None = None,
        partition_policy: PartitionQueryPolicy | None = None,
    ) -> None:
        self.schema = schema
        self.capabilities = capabilities
        self.policy = partition_policy or PartitionQueryPolicy()
        self._embedder = query_embedder
        self._compiler = CosmosQueryCompiler(schema)
        self._executor = CosmosExecutor(container)
        self._planner = RetrievalPlanner(schema, capabilities, self.policy)
        self._ctx = RetrievalContext(
            schema=schema,
            compiler=self._compiler,
            executor=self._executor,
            capabilities=capabilities,
            policy=self.policy,
        )
        self._resolver = build_document_resolver(
            schema, self._compiler, self._executor, self.policy
        )

    def search(self, request: SearchRequest) -> list[RetrievedItem]:
        if request.vector_field is not None:
            self.schema.resolve_vector_config(request.vector_field)
        if request.text_fields:
            self.schema.resolve_text_fields(request.text_fields)
        strategy = self._planner.plan_search(request)
        if strategy.requires_embedding and request.query_vector is None:
            if self._embedder is None:
                from cosmos_retriever.retrieval.errors import EmbeddingProfileMismatch

                raise EmbeddingProfileMismatch(
                    "selected strategy requires a query embedding but no embedder is configured"
                )
            request = request.model_copy(
                update={"query_vector": self._embedder.embed(request.query)}
            )
        return strategy.execute(request, self._ctx)

    def grep_candidates(self, request: GrepRequest) -> list[RetrievedItem]:
        if request.text_field:
            self.schema.resolve_text_fields([request.text_field])
        strategy = self._planner.plan_grep(request)
        return strategy.candidates(request, self._ctx)

    def read_document(self, request: ReadDocumentRequest) -> NormalizedDocument:
        return self._resolver.resolve(request)
