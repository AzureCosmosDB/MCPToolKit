from __future__ import annotations

from cosmos_retriever.retrieval.capabilities import (
    RetrievalCapabilities,
    SupportLevel,
    VectorCapability,
)
from cosmos_retriever.retrieval.discovery.models import ContainerMetadata
from cosmos_retriever.retrieval.discovery.profiler import parse_container_metadata
from cosmos_retriever.retrieval.embedding import QueryEmbedder
from cosmos_retriever.retrieval.models import PartitionQueryPolicy
from cosmos_retriever.retrieval.retriever import CorpusRetriever
from cosmos_retriever.retrieval.schema import (
    CorpusSchema,
    DunderChunkCodec,
    VectorFieldConfig,
)
from cosmos_retriever.retrieval.schema_override import SchemaOverride

__all__ = [
    "SchemaOverride",
    "capabilities_from_metadata",
    "schema_from_metadata",
    "build_capability_retriever",
    "build_capability_retriever_from_live",
]


def capabilities_from_metadata(metadata: ContainerMetadata) -> RetrievalCapabilities:
    indexed = [v for v in metadata.vector_fields if v.indexed and (v.dimensions or 0) > 0]
    has_fts = bool(metadata.full_text_paths)
    has_vec = bool(indexed)
    return RetrievalCapabilities(
        vector_fields=[
            VectorCapability(
                path=v.path,
                dimensions=v.dimensions or 0,
                distance_function=v.distance_function or "cosine",
                support=SupportLevel.INDEXED,
            )
            for v in indexed
        ],
        full_text_paths=list(metadata.full_text_paths),
        partition_key_paths=list(metadata.partition_key_paths),
        native_hybrid_supported=has_vec and has_fts,
        full_text_supported=has_fts,
        vector_supported=has_vec,
        efficient_document_lookup_supported=True,
    )


def schema_from_metadata(
    metadata: ContainerMetadata,
    override: SchemaOverride | None = None,
) -> CorpusSchema:
    o = override or SchemaOverride()
    text_paths = list(metadata.full_text_paths)
    vector_fields = [
        VectorFieldConfig(
            path=v.path,
            dimensions=v.dimensions or 0,
            distance_function=v.distance_function or "cosine",
        )
        for v in metadata.vector_fields
        if v.indexed and (v.dimensions or 0) > 0
    ]

    schema = CorpusSchema(
        item_id_path=o.item_id_path or "/id",
        text_paths=text_paths,
        vector_fields=vector_fields,
        document_id_path=o.document_id_path,
        chunk_id_path=o.chunk_id_path,
        chunk_order_path=o.chunk_order_path,
        title_path=o.title_path,
        source_path=o.source_path,
        partition_key_paths=list(metadata.partition_key_paths),
    )
    if o.use_dunder_codec:
        schema.identity_codec = DunderChunkCodec()
    return schema


def build_capability_retriever(
    *,
    container,
    metadata: ContainerMetadata,
    embedder: QueryEmbedder | None = None,
    override: SchemaOverride | None = None,
    partition_policy: PartitionQueryPolicy | None = None,
) -> CorpusRetriever:
    return CorpusRetriever(
        container=container,
        schema=schema_from_metadata(metadata, override),
        capabilities=capabilities_from_metadata(metadata),
        query_embedder=embedder,
        partition_policy=partition_policy or PartitionQueryPolicy(),
    )


def build_capability_retriever_from_live(
    *,
    container,
    database: str,
    embedder: QueryEmbedder | None = None,
    override: SchemaOverride | None = None,
    partition_policy: PartitionQueryPolicy | None = None,
) -> CorpusRetriever:
    props = container.read()
    metadata = parse_container_metadata(
        database, container.id, props, props.get("_etag")
    )
    return build_capability_retriever(
        container=container,
        metadata=metadata,
        embedder=embedder,
        override=override,
        partition_policy=partition_policy,
    )
