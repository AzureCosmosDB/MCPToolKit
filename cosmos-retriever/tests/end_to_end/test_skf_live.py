"""End-to-end live tests against the real ``skf-rag-test`` Cosmos DB corpus.

These exercise the full stack — Azure Cosmos DB hybrid (vector + full-text RRF)
retrieval, Azure OpenAI ``text-embedding-3-small`` (1536-dim) query embeddings,
the local Qwen3-Reranker, and the gpt-5.4 ``/responses`` agent — against the
``skf-database/skf-unstructured`` container (~9k SKF product/industry docs).

Cost/latency control: the expensive agentic ``CosmosRetriever.search`` runs
ONCE (session fixture) and is asserted many ways; the retrieval layer is covered
cheaply and exhaustively via a directly-built ``CorpusRetriever`` and the built
toolset tools (no LLM).

Opt-in only: the whole module is skipped unless ``RUN_SKF_LIVE`` is truthy and
``.env.local`` points ``ACCOUNT_URI`` at ``skf-rag-test``. It relies on the real
``.env.local`` (the tests/conftest env-isolation deliberately excludes this
folder). Requires ``az login`` with the Cosmos Data Reader role.
"""
from __future__ import annotations

import os
from dataclasses import asdict

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
CONTAINER = "skf-unstructured"
EXPECTED_DIMS = 1536
# This corpus exposes 9 full-text fields, so retrieval requires explicit selection.
TEXT_FIELDS = ["title", "summary", "content"]

# ─────────────────────────────── fixtures ─────────────────────────────────


@pytest.fixture(scope="session")
def settings():
    from cosmos_retriever.config import get_settings

    return get_settings()


@pytest.fixture(scope="session")
def engine(settings):
    """The full CosmosRetriever (toolset + reranker + agent), built once."""
    from cosmos_retriever.retriever import CosmosRetriever

    try:
        return CosmosRetriever(settings=settings, corpus_name=CONTAINER)
    except Exception as exc:  # network/RBAC/embedding misconfig
        pytest.skip(f"could not build CosmosRetriever: {type(exc).__name__}: {exc}")


@pytest.fixture(scope="session")
def corpus_retriever(settings):
    """Low-level CorpusRetriever for direct search/grep/read (no LLM)."""
    from cosmos_retriever.retrieval import (
        QueryEmbedder,
        build_capability_retriever_from_live,
    )

    corpus = settings.resolve_corpus(CONTAINER)
    client = settings.build_cosmos_client(corpus)
    container = client.get_database_client(corpus.database).get_container_client(corpus.container)
    embedder = QueryEmbedder(
        client=settings.build_openai_client(corpus),
        model=corpus.embed_model,
        query_instruction=corpus.embed_query_instruction,
        dimensions=corpus.embed_dimensions,
    )
    return build_capability_retriever_from_live(
        container=container,
        database=corpus.database,
        embedder=embedder,
        override=corpus.schema_override,
    )


@pytest.fixture(scope="session")
def embedder(settings):
    from cosmos_retriever.retrieval import QueryEmbedder

    corpus = settings.resolve_corpus(CONTAINER)
    return QueryEmbedder(
        client=settings.build_openai_client(corpus),
        model=corpus.embed_model,
        query_instruction=corpus.embed_query_instruction,
        dimensions=corpus.embed_dimensions,
    )


@pytest.fixture(scope="session")
def agent_result(engine):
    """One real agentic search, reused across assertions."""
    return engine.search(
        "Which SKF bearings are recommended for high-temperature aerospace "
        "engine and gearbox applications?",
        max_documents=5,
    )


@pytest.fixture(scope="session")
def top_doc_id(corpus_retriever):
    from cosmos_retriever.retrieval.models import SearchRequest

    items = corpus_retriever.search(
        SearchRequest(query="aerospace bearing", limit=5, text_fields=TEXT_FIELDS)
    )
    if not items:
        pytest.skip("no documents returned for seed query")
    return items[0].item_id


def _search(corpus_retriever, **kw):
    from cosmos_retriever.retrieval.models import SearchRequest

    return corpus_retriever.search(SearchRequest(**kw))


# ═══════════════════════ config / corpus wiring ═══════════════════════════


def test_settings_point_at_skf(settings) -> None:
    assert "skf-rag-test" in settings.account_uri
    corpus = settings.resolve_corpus(CONTAINER)
    assert corpus.embed_model == "text-embedding-3-small"
    assert corpus.embed_dimensions == EXPECTED_DIMS


def test_engine_corpus_and_toolset(engine) -> None:
    assert engine.database_wide is False
    assert engine.corpus.database == DATABASE
    assert engine.corpus.container == CONTAINER
    names = set(engine.toolset.tools)
    assert {"search_corpus", "grep_corpus", "read_document", "prune_chunks"} <= names
    assert "execute_query" in names  # raw query enabled by default


def test_embedder_dimension_matches_corpus(embedder) -> None:
    vec = embedder.embed("high temperature aerospace bearing")
    assert isinstance(vec, list) and len(vec) == EXPECTED_DIMS
    assert all(isinstance(x, float) for x in vec[:8])


# ═══════════════════════ low-level retrieval layer ════════════════════════


def test_hybrid_search_returns_ranked_docs(corpus_retriever) -> None:
    items = _search(
        corpus_retriever, query="aerospace engine gearbox bearing", limit=10, text_fields=TEXT_FIELDS
    )
    assert 1 <= len(items) <= 10
    assert all(it.item_id.startswith("skf") for it in items)
    assert all(it.text for it in items)
    assert [it.rank for it in items] == list(range(len(items)))
    assert items[0].retrieval_strategy in {"native_hybrid", "client_fusion"}


def test_hybrid_search_is_relevant(corpus_retriever) -> None:
    items = _search(
        corpus_retriever, query="high temperature aerospace bearing", limit=5, text_fields=TEXT_FIELDS
    )
    blob = " ".join(it.text for it in items).lower()
    assert "bearing" in blob


def test_vector_search_uses_embedding(corpus_retriever) -> None:
    items = _search(corpus_retriever, query="corrosion resistant steel bearing", limit=5, mode="vector")
    assert items
    assert items[0].retrieval_strategy == "vector"


def test_full_text_search(corpus_retriever) -> None:
    items = _search(
        corpus_retriever, query="aerospace bearing", limit=5, mode="text", text_fields=TEXT_FIELDS
    )
    assert items
    assert items[0].retrieval_strategy == "full_text"


def test_search_respects_limit(corpus_retriever) -> None:
    items = _search(corpus_retriever, query="bearing", limit=3, text_fields=TEXT_FIELDS)
    assert len(items) <= 3


def test_search_ignored_item_ids_excludes(corpus_retriever, top_doc_id) -> None:
    items = _search(
        corpus_retriever,
        query="aerospace bearing",
        limit=10,
        ignored_item_ids=[top_doc_id],
        text_fields=TEXT_FIELDS,
    )
    assert top_doc_id not in {it.item_id for it in items}


def test_search_specific_text_field(corpus_retriever) -> None:
    items = _search(corpus_retriever, query="bearing", limit=5, mode="text", text_fields=["title"])
    assert isinstance(items, list)  # field-scoped search must not error


def test_search_without_fields_requires_selection(corpus_retriever) -> None:
    from cosmos_retriever.retrieval.errors import UnknownField
    from cosmos_retriever.retrieval.models import SearchRequest

    # With 9 full-text fields, a text/hybrid search must name the field(s).
    with pytest.raises(UnknownField):
        corpus_retriever.search(SearchRequest(query="bearing", mode="text"))


def test_grep_finds_literal_term(corpus_retriever) -> None:
    from cosmos_retriever.retrieval.models import GrepRequest

    hits = corpus_retriever.grep_candidates(
        GrepRequest(pattern="bearing", text_field="title", candidate_limit=50, result_limit=5)
    )
    assert isinstance(hits, list)
    for it in hits:
        assert it.item_id.startswith("skf")


def test_grep_all_stopword_pattern_is_empty(corpus_retriever) -> None:
    from cosmos_retriever.retrieval.models import GrepRequest

    assert corpus_retriever.grep_candidates(GrepRequest(pattern="the and of")) == []


def test_read_document_round_trip(corpus_retriever, top_doc_id) -> None:
    from cosmos_retriever.retrieval.models import ReadDocumentRequest

    doc = corpus_retriever.read_document(ReadDocumentRequest(document_id=top_doc_id))
    assert doc.chunk_texts and doc.assembled.strip()


def test_read_unknown_document_is_empty(corpus_retriever) -> None:
    from cosmos_retriever.retrieval.models import ReadDocumentRequest

    doc = corpus_retriever.read_document(ReadDocumentRequest(document_id="skf-does-not-exist-xyz"))
    assert doc.chunk_texts == []


# ═══════════════════════ toolset integration (with reranker) ══════════════


def test_search_corpus_tool_invokes_reranker(engine) -> None:
    tool = engine.toolset.get_tool("search_corpus")
    text, meta = tool({"query": "high temperature aerospace bearing", "fields": TEXT_FIELDS})
    assert meta is not None and meta.returned_chunk_ids
    assert meta.retrieval_s >= 0.0
    assert meta.rerank_s > 0.0  # the live Qwen3-Reranker actually ran
    assert "DOCUMENT ID" in text


def test_read_document_tool(engine, top_doc_id) -> None:
    tool = engine.toolset.get_tool("read_document")
    text, _ = tool({"doc_id": top_doc_id})
    assert isinstance(text, str) and text.strip()


def test_execute_query_tool_select_and_write_guard(engine) -> None:
    tool = engine.toolset.get_tool("execute_query")
    ok, _ = tool({"query": "SELECT TOP 1 c.id FROM c", "database": DATABASE, "container": CONTAINER})
    assert "row(s)" in ok
    blocked, _ = tool({"query": "DELETE FROM c", "database": DATABASE, "container": CONTAINER})
    assert "only read-only SELECT queries are allowed" in blocked


# ═══════════════════════ full agentic end-to-end ══════════════════════════


def test_agent_result_shape(agent_result) -> None:
    from cosmos_retriever.retriever import RetrievalResult, RetrievedDocument

    assert isinstance(agent_result, RetrievalResult)
    assert agent_result.num_turns >= 1
    assert agent_result.elapsed_s > 0.0
    assert 1 <= len(agent_result.documents) <= 5
    assert all(isinstance(d, RetrievedDocument) for d in agent_result.documents)


def test_agent_documents_are_well_formed(agent_result) -> None:
    docs = agent_result.documents
    assert [d.rank for d in docs] == list(range(len(docs)))  # 0..n-1, ordered
    assert len({d.id for d in docs}) == len(docs)  # unique ids
    for d in docs:
        assert d.id and d.id.startswith("skf")
        assert d.text and d.text.strip()
        assert d.justification and d.justification.strip()


def test_agent_result_is_relevant(agent_result) -> None:
    blob = " ".join(d.text for d in agent_result.documents).lower()
    assert "bearing" in blob


def test_agent_result_serializes(agent_result) -> None:
    d = asdict(agent_result)
    assert d["query"] and isinstance(d["documents"], list)
    assert set(d) >= {"query", "documents", "num_turns", "elapsed_s"}


def test_agent_pool_covers_returned_docs(agent_result) -> None:
    # The candidate pool should be a superset of the finally-returned documents.
    returned = {d.id for d in agent_result.documents}
    if agent_result.pool_doc_ids:
        assert returned <= set(agent_result.pool_doc_ids)
