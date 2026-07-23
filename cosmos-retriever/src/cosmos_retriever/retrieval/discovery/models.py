from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Provenance = Literal["authoritative", "inferred", "fallback", "unknown"]


class VectorIndexInfo(BaseModel):
    path: str
    dimensions: int | None = None
    distance_function: str | None = None
    data_type: str | None = None
    index_type: str | None = None
    indexed: bool = False


class ContainerMetadata(BaseModel):
    database: str
    container: str
    etag: str | None = None
    fetched_at: float
    partition_key_paths: list[str] = Field(default_factory=list)
    included_paths: list[str] = Field(default_factory=list)
    excluded_paths: list[str] = Field(default_factory=list)
    full_text_paths: list[str] = Field(default_factory=list)
    full_text_policy_paths: list[str] = Field(default_factory=list)
    vector_fields: list[VectorIndexInfo] = Field(default_factory=list)


class CapabilityFlag(BaseModel):
    value: bool
    provenance: Provenance = "authoritative"


class CapabilityProfile(BaseModel):
    database: str
    container: str
    fetched_at: float
    partition_key_paths: list[str] = Field(default_factory=list)
    full_text_paths: list[str] = Field(default_factory=list)
    vector_fields: list[VectorIndexInfo] = Field(default_factory=list)
    can_full_text: CapabilityFlag
    can_vector: CapabilityFlag
    can_native_hybrid: CapabilityFlag
    can_item_lookup: CapabilityFlag
    recommended_strategies: list[str] = Field(default_factory=list)
    confidence: float = 1.0

    def summary(self) -> dict[str, Any]:
        return {
            "database": self.database,
            "container": self.container,
            "full_text": self.can_full_text.value,
            "vector": self.can_vector.value,
            "hybrid": self.can_native_hybrid.value,
            "item_lookup": self.can_item_lookup.value,
            "full_text_paths": list(self.full_text_paths),
            "vector_paths": [v.path for v in self.vector_fields],
            "partition_key_paths": list(self.partition_key_paths),
            "recommended_strategies": list(self.recommended_strategies),
            "confidence": self.confidence,
        }
