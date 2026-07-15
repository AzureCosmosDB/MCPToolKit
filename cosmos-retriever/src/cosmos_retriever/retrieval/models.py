"""Logical request/result models for the retrieval layer.

These carry *no* Cosmos SQL, physical field names, partition-key paths, or
capability knowledge. Agent-facing tools build the request models; the retriever
returns the normalized result models.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class EqualsFilter(BaseModel):

    kind: Literal["equals"] = "equals"


    logical_field: str
    value: Any


class RangeFilter(BaseModel):
    kind: Literal["range"] = "range"
    logical_field: str
    minimum: Any | None = None

    maximum: Any | None = None


class InFilter(BaseModel):
    kind: Literal["in"] = "in"


    logical_field: str
    values: list[Any]


FilterExpression = Annotated[
    EqualsFilter | RangeFilter | InFilter, Field(discriminator="kind")
]
class SearchRequest(BaseModel):
    query: str


    query_vector: list[float] | None = None
    limit: int = 50
    ignored_item_ids: list[str] = Field(default_factory=list)



    filters: list[FilterExpression] = Field(default_factory=list)
    partition_key: Any | None = None
    


    text_fields: list[str] | None = None
    vector_field: str | None = None
    mode: Literal["auto", "hybrid", "vector", "text"] = "auto"


class GrepRequest(BaseModel):
    pattern: str

    candidate_limit: int = 50

    result_limit: int = 5
    filters: list[FilterExpression] = Field(default_factory=list)
    partition_key: Any | None = None
    text_field: str | None = None


class ReadDocumentRequest(BaseModel):
    document_id: str | None = None
    item_id: str | None = None

    partition_key: Any | None = None


    max_chunks: int | None = None
    query: str | None = None


class RetrievedItem(BaseModel):
    item_id: str
    document_id: str | None = None
    chunk_id: str | None = None

    chunk_order: int | None = None
    text: str = ""
    


    text_fields: dict[str, str] = Field(default_factory=dict)
    title: str | None = None

    source: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)



    partition_key: Any | None = None
    retrieval_strategy: str = ""
    retrieval_channels: list[str] = Field(default_factory=list)

    raw_scores: dict[str, float] = Field(default_factory=dict)
    rank: int = 0


class NormalizedDocument(BaseModel):
    document_id: str | None = None
    chunk_texts: list[str] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)

    warnings: list[str] = Field(default_factory=list)

    @property
    def assembled(self) -> str:
        return "".join(self.chunk_texts)


class CompiledCosmosQuery(BaseModel):
    sql: str
    parameters: list[dict[str, Any]] = Field(default_factory=list)
    partition_key: Any | None = None
    enable_cross_partition_query: bool = False


    strategy: str = ""
    projected_aliases: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)



class PartitionQueryPolicy(BaseModel):
    allow_cross_partition_search: bool = True
    allow_cross_partition_document_read: bool = False

    require_partition_filter_when_available: bool = False

    maximum_partitions: int | None = None


    allow_bounded_scan: bool = False
