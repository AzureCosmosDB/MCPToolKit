"""Document resolvers: reconstruct a complete logical document.

Replaces the pre-refactor ``ReadDocumentTool`` assumptions (docid == partition
key, ``__`` chunk-id parsing, fixed ``TOP 300``) with configurable resolution
modes selected by the planner.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from cosmos_retriever.retrieval.compiler import CosmosQueryCompiler
from cosmos_retriever.retrieval.errors import (
    CrossPartitionQueryDisabled,
    DocumentResolutionUnsupported,
)
from cosmos_retriever.retrieval.executor import CosmosExecutor
from cosmos_retriever.retrieval.models import (
    EqualsFilter,
    NormalizedDocument,
    PartitionQueryPolicy,
    ReadDocumentRequest,
)
from cosmos_retriever.retrieval.schema import CorpusSchema

DEFAULT_MAX_CHUNKS = 300


class DocumentResolver(ABC):
    def __init__(
        self,
        schema: CorpusSchema,
        compiler: CosmosQueryCompiler,
        executor: CosmosExecutor,
        policy: PartitionQueryPolicy,
    ) -> None:
        self.schema = schema
        self.compiler = compiler
        self.executor = executor
        self.policy = policy

    @abstractmethod
    def resolve(self, request: ReadDocumentRequest) -> NormalizedDocument: ...

    def _derive_document_id(self, request: ReadDocumentRequest) -> str:
        raw = request.document_id or request.item_id or ""
        codec = self.schema.identity_codec
        return codec.to_document_id(raw) if codec is not None else raw

    @staticmethod
    def _sorted_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(rows, key=lambda r: r.get("chunk_order") or 0)


class ItemIsDocumentResolver(DocumentResolver):
    

    def resolve(self, request: ReadDocumentRequest) -> NormalizedDocument:
        item_id = request.item_id or request.document_id or ""
        compiled = self.compiler.compile_structured(

            limit=1,
            filters=[EqualsFilter(logical_field="item_id", value=item_id)],
            ignored_item_ids=[],

            partition_key=request.partition_key,
            cross_partition=request.partition_key is None,
        )
        rows = self.executor.run(compiled)
        return NormalizedDocument(
            document_id=item_id,

            chunk_texts=[r.get("text", "") or "" for r in rows],
            chunk_ids=[str(r.get("item_id")) for r in rows],
        )


class ChunkedDocumentResolver(DocumentResolver):

    def resolve(self, request: ReadDocumentRequest) -> NormalizedDocument:
        doc_id = self._derive_document_id(request)

        max_chunks = request.max_chunks or DEFAULT_MAX_CHUNKS

        partition_key = request.partition_key or doc_id
        compiled = self.compiler.compile_document_read(

            document_id=doc_id,
            max_chunks=max_chunks,

            partition_key=partition_key,
            cross_partition=False,
        )
        rows = self._sorted_rows(self.executor.run(compiled))
        return NormalizedDocument(

            document_id=doc_id,
            chunk_texts=[r.get("text", "") or "" for r in rows],

            chunk_ids=[str(r.get("item_id")) for r in rows],
        )


class CrossPartitionChunkedDocumentResolver(DocumentResolver):
    def resolve(self, request: ReadDocumentRequest) -> NormalizedDocument:
        if not self.policy.allow_cross_partition_document_read:

            raise CrossPartitionQueryDisabled(
                "read_document requires cross-partition reconstruction, which is disabled"
            )
        doc_id = self._derive_document_id(request)

        max_chunks = request.max_chunks or DEFAULT_MAX_CHUNKS

        compiled = self.compiler.compile_document_read(
            document_id=doc_id,

            max_chunks=max_chunks,
            partition_key=request.partition_key,

            cross_partition=request.partition_key is None,
        )
        rows = self._sorted_rows(self.executor.run(compiled))
        
        return NormalizedDocument(
            document_id=doc_id,

            chunk_texts=[r.get("text", "") or "" for r in rows],
            chunk_ids=[str(r.get("item_id")) for r in rows],

            warnings=["cross-partition document reconstruction"],
        )


def build_document_resolver(
    schema: CorpusSchema,

    compiler: CosmosQueryCompiler,
    executor: CosmosExecutor,


    policy: PartitionQueryPolicy,
) -> DocumentResolver:
    """Select the appropriate resolver for the configured schema."""

    if schema.is_item_document_mode:
        return ItemIsDocumentResolver(schema, compiler, executor, policy)
    if schema.document_id_path is None:  # defensive; covered above

        raise DocumentResolutionUnsupported("no document reconstruction is possible")
    if schema.partition_key_is_document_id:
        return ChunkedDocumentResolver(schema, compiler, executor, policy)


    return CrossPartitionChunkedDocumentResolver(schema, compiler, executor, policy)
