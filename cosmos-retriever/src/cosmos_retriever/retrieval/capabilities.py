from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from cosmos_retriever.retrieval.paths import CosmosPath
from cosmos_retriever.retrieval.schema import PathField


class SupportLevel(StrEnum):
    INDEXED = "indexed"
    SCAN = "scan"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class VectorCapability(BaseModel):
    path: PathField
    dimensions: int
    distance_function: str = "cosine"
    index_type: str | None = None
    support: SupportLevel = SupportLevel.UNKNOWN


class RetrievalCapabilities(BaseModel):
    vector_fields: list[VectorCapability] = []
    full_text_paths: list[PathField] = []
    range_indexed_paths: list[PathField] = []
    partition_key_paths: list[PathField] = []
    native_hybrid_supported: bool = False
    full_text_supported: bool = False
    vector_supported: bool = False
    efficient_document_lookup_supported: bool = False

    def vector_capability_for(self, path: CosmosPath) -> VectorCapability | None:
        for v in self.vector_fields:
            if str(v.path) == str(path):
                return v
        return None

    def has_full_text_path(self, path: CosmosPath) -> bool:
        return any(str(p) == str(path) for p in self.full_text_paths)
