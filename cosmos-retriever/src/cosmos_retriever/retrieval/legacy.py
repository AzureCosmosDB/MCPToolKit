
from __future__ import annotations

from cosmos_retriever.retrieval.capabilities import (
    RetrievalCapabilities,
    SupportLevel,
    VectorCapability,
)
from cosmos_retriever.retrieval.embedding import QueryEmbedder
from cosmos_retriever.retrieval.models import PartitionQueryPolicy
from cosmos_retriever.retrieval.retriever import CorpusRetriever
from cosmos_retriever.retrieval.schema import (
    CorpusSchema,
    LegacyDunderCodec,
    VectorFieldConfig,
)

_LEGACY_DIMENSIONS = 1536


def build_legacy_schema(
    embedding_model: str = "text-embedding-3-small",
    dimensions: int = _LEGACY_DIMENSIONS,
) -> CorpusSchema:
    schema = CorpusSchema(
        item_id_path="/id",
        text_paths=["/text"],
        primary_text_path="/text",
        vector_fields=[
            VectorFieldConfig(
                path="/embedding",
                embedding_model=embedding_model,
                dimensions=dimensions,
                distance_function="cosine",
            )
        ],
        document_id_path="/docid",
        chunk_id_path="/id",
        chunk_order_path="/chunk_idx",
        partition_key_paths=["/docid"],
    )
    schema.identity_codec = LegacyDunderCodec()
    return schema


def legacy_capabilities_for(schema: CorpusSchema) -> RetrievalCapabilities:

    field = schema.vector_fields[0]
    return RetrievalCapabilities(
        vector_fields=[
            VectorCapability(
                path=field.path,
                dimensions=field.dimensions,
                distance_function=field.distance_function,
                support=SupportLevel.INDEXED,
            )
        ],
        full_text_paths=[schema.primary_text_path],
        partition_key_paths=list(schema.partition_key_paths),
        native_hybrid_supported=True,
        full_text_supported=True,
        vector_supported=True,
        efficient_document_lookup_supported=True,
    )


def build_legacy_retriever(
    *,
    container,
    embedder: QueryEmbedder | None,
    embedding_model: str = "text-embedding-3-small",
    partition_policy: PartitionQueryPolicy | None = None,
) -> CorpusRetriever:
    schema = build_legacy_schema(embedding_model=embedding_model)
    return CorpusRetriever(
        container=container,
        schema=schema,
        capabilities=legacy_capabilities_for(schema),
        query_embedder=embedder,
        partition_policy=partition_policy or PartitionQueryPolicy(),
    )
