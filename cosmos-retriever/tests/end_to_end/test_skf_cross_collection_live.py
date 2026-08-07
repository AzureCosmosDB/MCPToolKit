"""End-to-end live tests for cross-collection RRF fusion over the real
``skf-rag-test`` / ``skf-database`` collections.

Database-wide search fans each request out across every searchable collection
and fuses the per-collection ranked lists with Reciprocal Rank Fusion. These
tests exercise that path over real data at every layer:

    select_search_targets  ->  MultiContainerRetriever  ->  fuse_rrf
                           ->  CrossCollectionRetriever (search / grep / read)
                           ->  CosmosRetriever(corpus_name="*")

``skf-database`` is a realistic stress case: its collections have mixed
embedding dimensions (1536 x2, 3072 x1) and different text-field sets, so the
fan-out's per-collection error tolerance (a failing collection is skipped, the
rest still fuse) is exercised with genuine dimension/field mismatches — not
mocks.

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
C_UNSTRUCT = "skf-unstructured"          # 1536-dim, 9 text fields
C_STRUCT = "skf-structured"              # 1536-dim, 6 text fields (incl. description)
C_LARGE = "skf-unstructured-text-large"  # 3072-dim -> vector-incompatible with 1536 embedder
COMMON_TEXT_FIELD = "description"        # present in both 1536 collections


class _Conn:
    def __init__(self, client):
        self._client = client

    def client(self):
        return self._client


def _target(container: str):
    from cosmos_retriever.retrieval.orchestration import ContainerTarget

    return ContainerTarget(database=DATABASE, container=container)


# ─────────────────────────────── fixtures ─────────────────────────────────


@pytest.fixture(scope="session")
def settings():
    from cosmos_retriever.config import get_settings

    return get_settings()


@pytest.fixture(scope="session")
def cosmos_client(settings):
    corpus = settings.resolve_corpus(C_UNSTRUCT)
    return settings.build_cosmos_client(corpus)


@pytest.fixture(scope="session")
def embedder(settings):
    from cosmos_retriever.retrieval import QueryEmbedder

    corpus = settings.resolve_corpus(C_UNSTRUCT)  # 1536-dim
    return QueryEmbedder(
        client=settings.build_openai_client(corpus),
        model=corpus.embed_model,
        query_instruction=corpus.embed_query_instruction,
        dimensions=corpus.embed_dimensions,
    )


@pytest.fixture(scope="session")
def retrievers(settings, cosmos_client, embedder):
    """Per-collection CorpusRetrievers keyed by ContainerTarget (built once)."""
    from cosmos_retriever.retrieval import build_capability_retriever_from_live

    db = cosmos_client.get_database_client(DATABASE)
    out = {}
    for name in (C_UNSTRUCT, C_STRUCT, C_LARGE):
        try:
            out[_target(name)] = build_capability_retriever_from_live(
                container=db.get_container_client(name),
                database=DATABASE,
                embedder=embedder,
            )
        except Exception as exc:
            pytest.skip(f"could not build retriever for {name}: {exc}")
    return out


@pytest.fixture(scope="session")
def catalog(cosmos_client):
    from cosmos_retriever.retrieval.discovery import ResourceCatalog

    return ResourceCatalog(_Conn(cosmos_client))


@pytest.fixture(scope="session")
def cross(retrievers):
    """CrossCollectionRetriever over the two dimension-compatible collections."""
    from cosmos_retriever.retrieval.orchestration import CrossCollectionRetriever

    targets = [_target(C_UNSTRUCT), _target(C_STRUCT)]
    subset = {t: retrievers[t] for t in targets}
    return CrossCollectionRetriever(targets, subset)


def _vsearch(retriever, query="bearing steel", limit=5):
    from cosmos_retriever.retrieval.models import SearchRequest

    return retriever.search(SearchRequest(query=query, limit=limit, mode="vector"))


# ═══════════════════════ select_search_targets ════════════════════════════


def test_select_targets_finds_searchable_collections(catalog) -> None:
    from cosmos_retriever.retrieval.orchestration import select_search_targets

    targets = select_search_targets(catalog, DATABASE)
    names = {t.container for t in targets}
    assert {C_UNSTRUCT, C_STRUCT, C_LARGE} <= names
    assert all(t.database == DATABASE for t in targets)
    for t in targets:
        p = catalog.profile(DATABASE, t.container)
        assert p.can_full_text.value or p.can_vector.value


def test_select_targets_capability_filter(catalog) -> None:
    from cosmos_retriever.retrieval.orchestration import select_search_targets

    filtered = select_search_targets(catalog, DATABASE, require_capability=True)
    unfiltered = select_search_targets(catalog, DATABASE, require_capability=False)
    assert len(unfiltered) >= len(filtered)  # unfiltered may include non-indexed containers


def test_select_targets_explicit_subset(catalog) -> None:
    from cosmos_retriever.retrieval.orchestration import select_search_targets

    targets = select_search_targets(catalog, DATABASE, containers=[C_UNSTRUCT])
    assert [t.container for t in targets] == [C_UNSTRUCT]


# ═══════════════════════ fuse_rrf over real items ═════════════════════════


def test_fuse_rrf_math_and_tagging(retrievers) -> None:
    from cosmos_retriever.retrieval.orchestration import RRF_K, fuse_rrf

    t_u, t_s = _target(C_UNSTRUCT), _target(C_STRUCT)
    a = _vsearch(retrievers[t_u], limit=5)
    b = _vsearch(retrievers[t_s], limit=5)
    assert a and b

    fused = fuse_rrf([(t_u, a), (t_s, b)])
    # Different collections -> qualified keys never collide -> all items survive.
    assert len(fused) == len(a) + len(b)
    assert [it.rank for it in fused] == list(range(len(fused)))
    scores = [it.raw_scores["rrf"] for it in fused]
    assert scores == sorted(scores, reverse=True)
    assert fused[0].raw_scores["rrf"] == pytest.approx(1.0 / (RRF_K + 0))  # pos 0 -> 1/60
    tags = {(it.metadata["database"], it.metadata["container"]) for it in fused}
    assert tags == {(DATABASE, C_UNSTRUCT), (DATABASE, C_STRUCT)}


def test_fuse_rrf_respects_limit(retrievers) -> None:
    from cosmos_retriever.retrieval.orchestration import fuse_rrf

    t_u, t_s = _target(C_UNSTRUCT), _target(C_STRUCT)
    fused = fuse_rrf(
        [(t_u, _vsearch(retrievers[t_u], limit=5)), (t_s, _vsearch(retrievers[t_s], limit=5))],
        limit=3,
    )
    assert len(fused) == 3


# ═══════════════════════ MultiContainerRetriever ══════════════════════════


def _mcr(retrievers):
    from cosmos_retriever.retrieval.orchestration import MultiContainerRetriever

    return MultiContainerRetriever(lambda t: retrievers[t], max_workers=4)


def test_multi_search_fuses_across_collections(retrievers) -> None:
    from cosmos_retriever.retrieval.models import SearchRequest

    targets = [_target(C_UNSTRUCT), _target(C_STRUCT)]
    res = _mcr(retrievers).search(
        targets, SearchRequest(query="bearing steel", limit=5, mode="vector")
    )
    assert res.items
    assert set(res.searched) == set(targets)
    assert set(res.per_container_counts) == {f"{DATABASE}/{C_UNSTRUCT}", f"{DATABASE}/{C_STRUCT}"}
    assert res.errors == {}
    assert res.elapsed_s > 0.0


def test_multi_search_deduplicates_targets(retrievers) -> None:
    from cosmos_retriever.retrieval.models import SearchRequest

    t_u = _target(C_UNSTRUCT)
    res = _mcr(retrievers).search([t_u, t_u], SearchRequest(query="bearing", limit=5, mode="vector"))
    assert res.searched == [t_u]


def test_multi_search_per_container_limit(retrievers) -> None:
    from cosmos_retriever.retrieval.models import SearchRequest

    targets = [_target(C_UNSTRUCT), _target(C_STRUCT)]
    res = _mcr(retrievers).search(
        targets, SearchRequest(query="bearing", limit=10, mode="vector"),
        per_container_limit=2, final_limit=10,
    )
    assert all(count <= 2 for count in res.per_container_counts.values())


def test_multi_search_captures_per_container_errors(retrievers) -> None:
    from cosmos_retriever.retrieval.models import SearchRequest

    # "content" exists in skf-unstructured but not skf-structured, so the latter
    # raises UnknownField; it must be recorded in errors WITHOUT aborting the
    # fusion of the collection that succeeded.
    targets = [_target(C_UNSTRUCT), _target(C_STRUCT)]
    res = _mcr(retrievers).search(
        targets, SearchRequest(query="bearing", limit=5, mode="text", text_fields=["content"])
    )
    assert f"{DATABASE}/{C_STRUCT}" in res.errors  # field mismatch captured
    assert _target(C_UNSTRUCT) in res.searched
    assert res.items  # good collection still returned fused results


# ═══════════════════════ CrossCollectionRetriever ═════════════════════════


def test_cross_schema_is_representative(cross, retrievers) -> None:
    assert cross.schema is retrievers[_target(C_UNSTRUCT)].schema


def test_cross_search_fuses_multiple_collections(cross) -> None:
    from cosmos_retriever.retrieval.models import SearchRequest

    items = cross.search(SearchRequest(query="bearing steel", limit=10, mode="vector"))
    assert items
    assert [it.rank for it in items] == list(range(len(items)))
    assert all("rrf" in it.raw_scores for it in items)
    containers = {it.metadata.get("container") for it in items}
    assert containers <= {C_UNSTRUCT, C_STRUCT}
    assert len(containers) >= 2  # genuinely fused across both collections


def test_cross_search_respects_limit(cross) -> None:
    from cosmos_retriever.retrieval.models import SearchRequest

    items = cross.search(SearchRequest(query="bearing", limit=4, mode="vector"))
    assert len(items) <= 4


def test_cross_search_error_tolerant_on_field_mismatch(cross) -> None:
    from cosmos_retriever.retrieval.models import SearchRequest

    # "content" exists in skf-unstructured but not skf-structured -> the latter
    # errors out, but the search still returns the former's hits.
    items = cross.search(
        SearchRequest(query="aerospace bearing", limit=5, mode="text", text_fields=["content"])
    )
    assert items
    assert {it.metadata.get("container") for it in items} == {C_UNSTRUCT}


def test_cross_grep_fans_out_and_caps(cross) -> None:
    from cosmos_retriever.retrieval.models import GrepRequest

    hits = cross.grep_candidates(
        GrepRequest(pattern="bearing", text_field=COMMON_TEXT_FIELD, candidate_limit=10)
    )
    assert isinstance(hits, list)
    assert len(hits) <= 10
    for it in hits:
        assert it.item_id.startswith("skf")


def test_cross_read_document_round_trip(cross) -> None:
    from cosmos_retriever.retrieval.models import ReadDocumentRequest, SearchRequest

    items = cross.search(SearchRequest(query="aerospace bearing", limit=3, mode="vector"))
    doc_id = items[0].item_id
    doc = cross.read_document(ReadDocumentRequest(document_id=doc_id))
    assert doc.assembled.strip()


def test_cross_read_unknown_document_is_empty(cross) -> None:
    from cosmos_retriever.retrieval.models import ReadDocumentRequest

    doc = cross.read_document(ReadDocumentRequest(document_id="skf-nonexistent-zzz"))
    assert doc.assembled == ""


# ═══════════════════════ CosmosRetriever(corpus_name="*") ═════════════════


def test_database_wide_engine_builds_cross_collection(settings) -> None:
    from cosmos_retriever.retriever import CosmosRetriever

    engine = CosmosRetriever(settings=settings, corpus_name="*")
    assert engine.database_wide is True
    inner = engine.toolset.get_tool("search_corpus")._retriever
    from cosmos_retriever.retrieval.orchestration import CrossCollectionRetriever

    assert isinstance(inner, CrossCollectionRetriever)
    assert len(inner._targets) >= 3  # all searchable skf-database collections
