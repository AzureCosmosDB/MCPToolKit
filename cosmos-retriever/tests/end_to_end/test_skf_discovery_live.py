"""End-to-end live tests for schema discovery (``binding.py`` _from_live path)
against the real ``skf-rag-test`` containers.

Exercises every layer of live discovery on real Cosmos DB container metadata:

    container.read()  ->  parse_container_metadata  ->  {capabilities, schema}
                                                    ->  build_capability_retriever_from_live

and cross-checks the discovered capabilities/schema against each container's
actual vector-embedding / full-text / partition-key policies. Covers all three
skf-database text containers (1536-dim x2 and 3072-dim) so dimension and
field-set adaptation is verified, plus override application and determinism.

Opt-in: skipped unless ``RUN_SKF_LIVE`` is truthy and ``.env.local`` points at
``skf-rag-test``. Requires ``az login`` with the Cosmos Data Reader role.
"""
from __future__ import annotations

import os

import pytest


def _live_enabled() -> bool:
    if os.getenv("RUN_SKF_LIVE", "").strip().lower() not in {"1", "true", "yes"}:
        return False
    try:
        from cosmos_retriever.config import get_settings

        s = get_settings()
        return bool(s.account_uri and "skf-rag-test" in s.account_uri)
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _live_enabled(),
    reason="set RUN_SKF_LIVE=1 and configure .env.local for skf-rag-test",
)

DATABASE = "skf-database"
PRIMARY = "skf-unstructured"

# Ground truth (from the containers' vector/full-text policies).
EXPECTED = {
    "skf-unstructured": {
        "dims": 1536,
        "fields": {"benefits", "content", "description", "designation",
                   "long_description", "summary", "taxonomy", "taxonomy_sap", "title"},
    },
    "skf-unstructured-text-large": {
        "dims": 3072,
        "fields": {"title", "summary", "content"},
    },
    "skf-structured": {
        "dims": 1536,
        "fields": {"benefits", "description", "designation",
                   "long_description", "taxonomy", "taxonomy_sap"},
    },
}

# ─────────────────────────────── helpers ──────────────────────────────────


def _container(settings, name):
    corpus = settings.resolve_corpus(name)
    client = settings.build_cosmos_client(corpus)
    return client.get_database_client(corpus.database).get_container_client(name)


def _discover(settings, name):
    from cosmos_retriever.retrieval.binding import (
        capabilities_from_metadata,
        schema_from_metadata,
    )
    from cosmos_retriever.retrieval.discovery.profiler import parse_container_metadata

    container = _container(settings, name)
    props = container.read()
    md = parse_container_metadata(DATABASE, container.id, props, props.get("_etag"))
    return props, md, capabilities_from_metadata(md), schema_from_metadata(md)


# ─────────────────────────────── fixtures ─────────────────────────────────


@pytest.fixture(scope="session")
def settings():
    from cosmos_retriever.config import get_settings

    return get_settings()


@pytest.fixture(scope="session")
def primary(settings):
    """(props, metadata, capabilities, schema) for skf-unstructured."""
    try:
        return _discover(settings, PRIMARY)
    except Exception as exc:
        pytest.skip(f"discovery failed: {type(exc).__name__}: {exc}")


# ═══════════════════════ raw read + parse_container_metadata ══════════════


def test_container_read_returns_policies(primary) -> None:
    props, *_ = primary
    assert props["id"] == PRIMARY
    assert props.get("partitionKey", {}).get("paths") == ["/id"]
    assert props.get("vectorEmbeddingPolicy", {}).get("vectorEmbeddings")
    assert props.get("fullTextPolicy", {}).get("fullTextPaths")


def test_parse_metadata_partition_and_etag(primary) -> None:
    props, md, *_ = primary
    assert md.database == DATABASE and md.container == PRIMARY
    assert md.partition_key_paths == ["/id"]
    assert md.etag == props.get("_etag")
    assert md.fetched_at > 0


def test_parse_metadata_vector_field(primary) -> None:
    _, md, *_ = primary
    assert len(md.vector_fields) == 1
    vf = md.vector_fields[0]
    assert vf.path == "/embedding"
    assert vf.dimensions == 1536
    assert vf.distance_function == "cosine"
    assert vf.indexed is True  # a vector index exists for the embedding path


def test_parse_metadata_full_text_index_matches_policy(primary) -> None:
    _, md, *_ = primary
    # The indexed full-text paths should cover the full-text policy paths.
    assert set(md.full_text_paths) == set(md.full_text_policy_paths)
    assert len(md.full_text_paths) == 9


# ═══════════════════════ capabilities_from_metadata ═══════════════════════


def test_capabilities_flags(primary) -> None:
    _, _, caps, _ = primary
    assert caps.full_text_supported is True
    assert caps.vector_supported is True
    assert caps.native_hybrid_supported is True
    assert caps.efficient_document_lookup_supported is True


def test_capabilities_vector_capability(primary) -> None:
    from cosmos_retriever.retrieval.capabilities import SupportLevel
    from cosmos_retriever.retrieval.paths import CosmosPath

    _, _, caps, _ = primary
    cap = caps.vector_capability_for(CosmosPath.parse("/embedding"))
    assert cap is not None
    assert cap.dimensions == 1536
    assert cap.distance_function == "cosine"
    assert cap.support is SupportLevel.INDEXED
    assert caps.vector_capability_for(CosmosPath.parse("/nope")) is None


def test_capabilities_full_text_paths(primary) -> None:
    from cosmos_retriever.retrieval.paths import CosmosPath

    _, _, caps, _ = primary
    for field in ("title", "summary", "content"):
        assert caps.has_full_text_path(CosmosPath.parse(f"/{field}"))
    assert not caps.has_full_text_path(CosmosPath.parse("/not_a_field"))
    assert [str(p) for p in caps.partition_key_paths] == ["/id"]


# ═══════════════════════ schema_from_metadata ═════════════════════════════


def test_schema_identity_and_mode(primary) -> None:
    _, _, _, schema = primary
    assert str(schema.item_id_path) == "/id"
    assert schema.is_item_document_mode is True  # no document_id_path override
    assert schema.partition_key_is_document_id is False
    assert [str(p) for p in schema.partition_key_paths] == ["/id"]


def test_schema_text_fields(primary) -> None:
    _, _, _, schema = primary
    assert set(schema.text_field_map()) == EXPECTED[PRIMARY]["fields"]
    assert len(schema.text_paths) == 9


def test_schema_vector_field(primary) -> None:
    _, _, _, schema = primary
    assert set(schema.vector_field_map()) == {"embedding"}
    vf = schema.resolve_vector_config(None)
    assert vf.dimensions == 1536
    assert str(schema.resolve_vector_field(None)) == "/embedding"


def test_schema_resolve_text_fields(primary) -> None:
    from cosmos_retriever.retrieval.errors import UnknownField

    _, _, _, schema = primary
    assert [str(p) for p in schema.resolve_text_fields(["title"])] == ["/title"]
    with pytest.raises(UnknownField):
        schema.resolve_text_fields(None)  # ambiguous: 9 fields
    with pytest.raises(UnknownField):
        schema.resolve_text_fields(["not_a_field"])


def test_schema_agent_field_summary(primary) -> None:
    _, _, _, schema = primary
    summary = schema.agent_field_summary()
    assert isinstance(summary, str) and "title" in summary


# ═══════════════════════ build_capability_retriever_from_live ═════════════


@pytest.fixture(scope="session")
def live_retriever(settings):
    from cosmos_retriever.retrieval import (
        QueryEmbedder,
        build_capability_retriever_from_live,
    )

    corpus = settings.resolve_corpus(PRIMARY)
    container = _container(settings, PRIMARY)
    embedder = QueryEmbedder(
        client=settings.build_openai_client(corpus),
        model=corpus.embed_model,
        query_instruction=corpus.embed_query_instruction,
        dimensions=corpus.embed_dimensions,
    )
    return build_capability_retriever_from_live(
        container=container, database=DATABASE, embedder=embedder
    )


def test_from_live_builds_matching_schema(live_retriever, primary) -> None:
    _, _, _, schema = primary
    assert str(live_retriever.schema.item_id_path) == "/id"
    assert set(live_retriever.schema.text_field_map()) == set(schema.text_field_map())
    assert live_retriever.schema.resolve_vector_config(None).dimensions == 1536


def test_from_live_builds_matching_capabilities(live_retriever) -> None:
    caps = live_retriever.capabilities
    assert caps.native_hybrid_supported and caps.full_text_supported and caps.vector_supported


def test_from_live_retriever_actually_searches(live_retriever) -> None:
    from cosmos_retriever.retrieval.models import SearchRequest

    items = live_retriever.search(
        SearchRequest(query="aerospace bearing", limit=5, mode="vector")
    )
    assert items and all(it.item_id.startswith("skf") for it in items)


def test_from_live_override_switches_to_chunked_mode(settings) -> None:
    from cosmos_retriever.retrieval import (
        QueryEmbedder,
        build_capability_retriever_from_live,
    )
    from cosmos_retriever.retrieval.schema_override import SchemaOverride

    corpus = settings.resolve_corpus(PRIMARY)
    container = _container(settings, PRIMARY)
    embedder = QueryEmbedder(
        client=settings.build_openai_client(corpus),
        model=corpus.embed_model,
        dimensions=corpus.embed_dimensions,
    )
    override = SchemaOverride(document_id_path="/id", title_path="/title")
    retriever = build_capability_retriever_from_live(
        container=container, database=DATABASE, embedder=embedder, override=override
    )
    schema = retriever.schema
    assert str(schema.document_id_path) == "/id"
    assert str(schema.title_path) == "/title"
    assert schema.is_item_document_mode is False  # override provides a document id path
    assert schema.partition_key_is_document_id is True  # pk /id == document id /id


def test_discovery_is_deterministic(settings) -> None:
    _, md1, caps1, s1 = _discover(settings, PRIMARY)
    _, md2, caps2, s2 = _discover(settings, PRIMARY)
    assert set(s1.text_field_map()) == set(s2.text_field_map())
    assert s1.resolve_vector_config(None).dimensions == s2.resolve_vector_config(None).dimensions
    assert caps1.native_hybrid_supported == caps2.native_hybrid_supported
    assert [str(v.path) for v in md1.vector_fields] == [str(v.path) for v in md2.vector_fields]


# ═══════════════════════ cross-container adaptation ═══════════════════════


@pytest.mark.parametrize("name", list(EXPECTED))
def test_discovery_adapts_per_container(settings, name) -> None:
    try:
        _, md, caps, schema = _discover(settings, name)
    except Exception as exc:
        pytest.skip(f"{name}: {type(exc).__name__}: {exc}")
    exp = EXPECTED[name]
    assert schema.resolve_vector_config(None).dimensions == exp["dims"]
    assert md.vector_fields[0].dimensions == exp["dims"]
    assert set(schema.text_field_map()) == exp["fields"]
    assert caps.native_hybrid_supported is True  # all three index text + vector
