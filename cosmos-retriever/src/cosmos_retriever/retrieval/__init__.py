"""Schema-decoupled retrieval layer for the Cosmos retriever.

Public entry points:

* :class:`CorpusRetriever` — façade the agent tools depend on.
* :class:`CorpusSchema` / :class:`VectorFieldConfig` — logical→physical mapping.
* :class:`RetrievalCapabilities` — what the container can efficiently do.
* :func:`build_legacy_retriever` — the named legacy benchmark profile.
"""

from __future__ import annotations

from cosmos_retriever.retrieval.capabilities import (
    RetrievalCapabilities,
    SupportLevel,
    VectorCapability,
)
from cosmos_retriever.retrieval.embedding import QueryEmbedder
from cosmos_retriever.retrieval.legacy import (
    build_legacy_retriever,
    build_legacy_schema,
    legacy_capabilities_for,
)
from cosmos_retriever.retrieval.models import (
    EqualsFilter,
    GrepRequest,
    InFilter,
    NormalizedDocument,
    PartitionQueryPolicy,
    RangeFilter,
    ReadDocumentRequest,
    RetrievedItem,
    SearchRequest,
)
from cosmos_retriever.retrieval.paths import CosmosPath
from cosmos_retriever.retrieval.retriever import CorpusRetriever
from cosmos_retriever.retrieval.schema import (
    ChunkIdentityCodec,
    CorpusSchema,
    LegacyDunderCodec,
    VectorFieldConfig,
)

__all__ = [
    "ChunkIdentityCodec",
    "CorpusRetriever",
    "CorpusSchema",
    "CosmosPath",
    "EqualsFilter",
    "GrepRequest",
    "InFilter",
    "LegacyDunderCodec",
    "NormalizedDocument",
    "PartitionQueryPolicy",
    "QueryEmbedder",
    "RangeFilter",
    "ReadDocumentRequest",
    "RetrievalCapabilities",
    "RetrievedItem",
    "SearchRequest",
    "SupportLevel",
    "VectorCapability",
    "VectorFieldConfig",
    "build_legacy_retriever",
    "build_legacy_schema",
    "legacy_capabilities_for",
]
