from __future__ import annotations

from typing import Any

import pytest

from cosmos_retriever.retrieval.compiler import CosmosQueryCompiler
from cosmos_retriever.retrieval.errors import QueryCompilationError
from cosmos_retriever.retrieval.models import EqualsFilter, InFilter, RangeFilter
from cosmos_retriever.retrieval.paths import CosmosPath
from cosmos_retriever.retrieval.schema import CorpusSchema, VectorFieldConfig

_VEC = CosmosPath.parse("/embedding")
_TEXT = CosmosPath.parse("/text")
_BODY = CosmosPath.parse("/body")


def _schema(*, with_docid: bool = True) -> CorpusSchema:
    return CorpusSchema(
        item_id_path="/id",
        document_id_path="/docid" if with_docid else None,
        chunk_id_path="/id",
        chunk_order_path="/chunk_idx",
        title_path="/title",
        source_path="/source_type",
        text_paths=["/text"],
        vector_fields=[VectorFieldConfig(path="/embedding", dimensions=2560)],
        metadata_paths={"year": "/year"},
    )


def _compiler(*, with_docid: bool = True) -> CosmosQueryCompiler:
    return CosmosQueryCompiler(_schema(with_docid=with_docid))


def _param(q: Any, name: str) -> dict[str, Any]:
    for p in q.parameters:
        if p["name"] == name:
            return p
    raise AssertionError(f"no bound parameter {name!r} in {[p['name'] for p in q.parameters]}")


def _param_values(q: Any) -> list[Any]:
    return [p["value"] for p in q.parameters]


# --- projection -----------------------------------------------------------


def test_projection_emits_logical_columns_and_alias_map() -> None:
    select, aliases = _compiler().projection("@k0")
    assert select.startswith("SELECT TOP @k0 ")
    for col in (
        'c["id"] AS item_id',
        'c["docid"] AS document_id',
        'c["id"] AS chunk_id',
        'c["chunk_idx"] AS chunk_order',
        'c["title"] AS title',
        'c["source_type"] AS source',
        'c["text"] AS txt_0',
        'c["year"] AS md_year',
    ):
        assert col in select
    # text/metadata aliases resolve back to their logical names
    assert aliases["txt_0"] == "text"
    assert aliases["md_year"] == "year"


# --- structured filters ---------------------------------------------------


def test_structured_equals_filter_is_parameterized() -> None:
    q = _compiler().compile_structured(
        limit=10,
        filters=[EqualsFilter(logical_field="year", value=2020)],
        ignored_item_ids=[],
        partition_key=None,
        cross_partition=True,
    )
    assert q.strategy == "structured"
    assert 'c["year"] = @p1' in q.sql
    assert _param(q, "@p1")["value"] == 2020
    assert _param(q, "@k0")["value"] == 10


def test_range_filter_emits_both_bounds() -> None:
    q = _compiler().compile_structured(
        limit=5,
        filters=[RangeFilter(logical_field="year", minimum=2000, maximum=2020)],
        ignored_item_ids=[],
        partition_key=None,
        cross_partition=True,
    )
    assert '(c["year"] >= @p1 AND c["year"] <= @p2)' in q.sql
    assert _param(q, "@p1")["value"] == 2000
    assert _param(q, "@p2")["value"] == 2020


def test_range_filter_with_only_minimum() -> None:
    q = _compiler().compile_structured(
        limit=5,
        filters=[RangeFilter(logical_field="year", minimum=2000)],
        ignored_item_ids=[],
        partition_key=None,
        cross_partition=True,
    )
    assert '(c["year"] >= @p1)' in q.sql
    assert "<=" not in q.sql


def test_in_filter_uses_array_contains() -> None:
    q = _compiler().compile_structured(
        limit=5,
        filters=[InFilter(logical_field="source", values=["news", "blog"])],
        ignored_item_ids=[],
        partition_key=None,
        cross_partition=True,
    )
    assert 'ARRAY_CONTAINS(@p1, c["source_type"])' in q.sql
    assert _param(q, "@p1")["value"] == ["news", "blog"]


def test_ignored_item_ids_add_not_array_contains() -> None:
    q = _compiler().compile_structured(
        limit=5,
        filters=[],
        ignored_item_ids=["a", "b"],
        partition_key=None,
        cross_partition=True,
    )
    assert 'NOT ARRAY_CONTAINS(@p1, c["id"])' in q.sql
    assert _param(q, "@p1")["value"] == ["a", "b"]


def test_no_filters_emits_no_where_clause() -> None:
    q = _compiler().compile_structured(
        limit=5,
        filters=[],
        ignored_item_ids=[],
        partition_key=None,
        cross_partition=True,
    )
    assert "WHERE" not in q.sql


# --- vector / full-text / hybrid -----------------------------------------


def test_vector_orders_by_vector_distance() -> None:
    q = _compiler().compile_vector(
        query_vector=[0.1, 0.2, 0.3],
        limit=8,
        ignored_item_ids=[],
        filters=[],
        partition_key=None,
        cross_partition=True,
        vector_path=_VEC,
    )
    assert q.strategy == "vector"
    assert 'ORDER BY VectorDistance(c["embedding"], @qVec1)' in q.sql
    assert _param(q, "@qVec1")["value"] == [0.1, 0.2, 0.3]


def test_full_text_single_path_uses_rank_fulltextscore() -> None:
    q = _compiler().compile_full_text(
        query="the quick brown fox",
        limit=5,
        ignored_item_ids=[],
        filters=[],
        partition_key=None,
        cross_partition=True,
        text_paths=[_TEXT],
    )
    assert q.strategy == "full_text"
    # stopword "the" dropped; remaining terms rendered as quoted literals
    assert 'ORDER BY RANK FullTextScore(c["text"], "quick", "brown", "fox")' in q.sql


def test_full_text_multiple_paths_uses_rank_rrf() -> None:
    q = _compiler().compile_full_text(
        query="quick brown",
        limit=5,
        ignored_item_ids=[],
        filters=[],
        partition_key=None,
        cross_partition=True,
        text_paths=[_TEXT, _BODY],
    )
    assert "ORDER BY RANK RRF(" in q.sql
    assert 'FullTextScore(c["text"], "quick", "brown")' in q.sql
    assert 'FullTextScore(c["body"], "quick", "brown")' in q.sql


def test_hybrid_fuses_vector_and_full_text_in_rrf() -> None:
    q = _compiler().compile_hybrid(
        query="quick brown",
        query_vector=[0.1, 0.2],
        limit=7,
        ignored_item_ids=[],
        filters=[],
        partition_key=None,
        cross_partition=True,
        vector_path=_VEC,
        text_paths=[_TEXT],
    )
    assert q.strategy == "native_hybrid"
    assert (
        'ORDER BY RANK RRF(VectorDistance(c["embedding"], @qVec1), '
        'FullTextScore(c["text"], "quick", "brown"))'
    ) in q.sql
    assert _param(q, "@qVec1")["value"] == [0.1, 0.2]


# --- document read --------------------------------------------------------


def test_document_read_filters_by_document_id() -> None:
    q = _compiler().compile_document_read(
        document_id="doc-1",
        max_chunks=50,
        partition_key=None,
        cross_partition=True,
    )
    assert q.strategy == "document_read"
    assert 'WHERE c["docid"] = @doc1' in q.sql
    assert _param(q, "@doc1")["value"] == "doc-1"


def test_document_read_without_document_id_path_raises() -> None:
    with pytest.raises(QueryCompilationError):
        _compiler(with_docid=False).compile_document_read(
            document_id="doc-1",
            max_chunks=50,
            partition_key=None,
            cross_partition=True,
        )


# --- errors & injection safety -------------------------------------------


def test_unknown_logical_field_raises() -> None:
    with pytest.raises(QueryCompilationError):
        _compiler().compile_structured(
            limit=5,
            filters=[EqualsFilter(logical_field="does_not_exist", value=1)],
            ignored_item_ids=[],
            partition_key=None,
            cross_partition=True,
        )


def test_filter_values_are_bound_never_inlined() -> None:
    """User-controlled values must go through @params, not the SQL string."""
    malicious = "2020'; DROP TABLE Foo--"
    q = _compiler().compile_structured(
        limit=5,
        filters=[EqualsFilter(logical_field="year", value=malicious)],
        ignored_item_ids=[],
        partition_key=None,
        cross_partition=True,
    )
    assert "DROP TABLE" not in q.sql
    assert 'c["year"] = @p1' in q.sql
    assert malicious in _param_values(q)


@pytest.mark.parametrize(
    "kind, expected_strategy",
    [
        ("hybrid", "native_hybrid"),
        ("vector", "vector"),
        ("full_text", "full_text"),
        ("structured", "structured"),
    ],
)
def test_each_query_type_reports_its_strategy(kind: str, expected_strategy: str) -> None:
    c = _compiler()
    common = dict(
        limit=5,
        ignored_item_ids=[],
        filters=[],
        partition_key=None,
        cross_partition=True,
    )
    if kind == "hybrid":
        q = c.compile_hybrid(query="q", query_vector=[0.1], vector_path=_VEC, text_paths=[_TEXT], **common)
    elif kind == "vector":
        q = c.compile_vector(query_vector=[0.1], vector_path=_VEC, **common)
    elif kind == "full_text":
        q = c.compile_full_text(query="q", text_paths=[_TEXT], **common)
    else:
        q = c.compile_structured(**common)
    assert q.strategy == expected_strategy
    assert q.sql.startswith("SELECT TOP @k0 ")
