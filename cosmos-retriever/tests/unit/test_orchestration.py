from __future__ import annotations

from types import SimpleNamespace

from cosmos_retriever.retrieval.models import RetrievedItem, SearchRequest
from cosmos_retriever.retrieval.orchestration import (
    ContainerTarget,
    MultiContainerRetriever,
    fuse_rrf,
    select_search_targets,
)


def _items(prefix: str, n: int) -> list[RetrievedItem]:
    return [RetrievedItem(item_id=f"{prefix}{i}", text=f"{prefix}{i}") for i in range(1, n + 1)]


class _FakeRetriever:
    def __init__(self, items: list[RetrievedItem]) -> None:
        self._items = items
        self.last_request: SearchRequest | None = None

    def search(self, request: SearchRequest) -> list[RetrievedItem]:
        self.last_request = request
        return self._items


def _req() -> SearchRequest:
    return SearchRequest(query="q", limit=50)


def test_fuse_rrf_interleaves_and_tags_metadata() -> None:
    ta = ContainerTarget("db", "A")
    tb = ContainerTarget("db", "B")
    fused = fuse_rrf([(ta, _items("a", 3)), (tb, _items("b", 3))], limit=3)
    assert [it.item_id for it in fused] == ["a1", "b1", "a2"]
    assert fused[0].metadata["container"] == "A"
    assert fused[1].metadata["container"] == "B"
    assert "rrf" in fused[0].raw_scores
    assert fused[0].rank == 0 and fused[1].rank == 1


def test_multi_search_fans_out_and_fuses() -> None:
    ta = ContainerTarget("db", "A")
    tb = ContainerTarget("db", "B")
    resolvers = {ta: _FakeRetriever(_items("a", 2)), tb: _FakeRetriever(_items("b", 2))}
    mcr = MultiContainerRetriever(lambda t: resolvers[t])
    result = mcr.search([ta, tb], _req(), final_limit=3)
    assert result.errors == {}
    assert set(result.searched) == {ta, tb}
    assert result.per_container_counts == {"db/A": 2, "db/B": 2}
    assert [it.item_id for it in result.items] == ["a1", "b1", "a2"]


def test_partial_failure_is_isolated() -> None:
    ta = ContainerTarget("db", "A")
    tb = ContainerTarget("db", "B")

    class _Boom:
        def search(self, request: SearchRequest) -> list[RetrievedItem]:
            raise RuntimeError("container offline")

    resolvers = {ta: _FakeRetriever(_items("a", 2)), tb: _Boom()}
    mcr = MultiContainerRetriever(lambda t: resolvers[t])
    result = mcr.search([ta, tb], _req())
    assert result.searched == [ta]
    assert "db/B" in result.errors and "container offline" in result.errors["db/B"]
    assert [it.item_id for it in result.items] == ["a1", "a2"]


def test_per_container_limit_is_applied() -> None:
    ta = ContainerTarget("db", "A")
    fake = _FakeRetriever(_items("a", 2))
    mcr = MultiContainerRetriever(lambda t: fake)
    mcr.search([ta], _req(), per_container_limit=7)
    assert fake.last_request is not None and fake.last_request.limit == 7


def test_empty_targets() -> None:
    mcr = MultiContainerRetriever(lambda t: _FakeRetriever([]))
    result = mcr.search([], _req())
    assert result.items == [] and result.searched == []


def test_duplicate_targets_deduped() -> None:
    ta = ContainerTarget("db", "A")
    fake = _FakeRetriever(_items("a", 2))
    calls = {"n": 0}

    def resolver(t: ContainerTarget) -> _FakeRetriever:
        calls["n"] += 1
        return fake

    mcr = MultiContainerRetriever(resolver)
    mcr.search([ta, ta, ta], _req())
    assert calls["n"] == 1


def test_select_search_targets_filters_incapable() -> None:
    def cap(fts: bool, vec: bool) -> SimpleNamespace:
        return SimpleNamespace(
            can_full_text=SimpleNamespace(value=fts),
            can_vector=SimpleNamespace(value=vec),
        )

    profiles = {"A": cap(True, True), "B": cap(False, False), "C": cap(False, True)}

    catalog = SimpleNamespace(
        containers=lambda db: ["A", "B", "C"],
        profile=lambda db, name: profiles[name],
    )
    targets = select_search_targets(catalog, "db")
    assert [t.container for t in targets] == ["A", "C"]


def test_cross_collection_retriever_fuses_probes_and_greps() -> None:
    from cosmos_retriever.retrieval.models import (
        GrepRequest,
        NormalizedDocument,
        ReadDocumentRequest,
    )
    from cosmos_retriever.retrieval.orchestration import CrossCollectionRetriever

    ta = ContainerTarget("db", "A")
    tb = ContainerTarget("db", "B")

    class _FR:
        def __init__(self, items: list[RetrievedItem], doc_text: str) -> None:
            self._items = items
            self._doc_text = doc_text
            self.schema = object()

        def search(self, request: SearchRequest) -> list[RetrievedItem]:
            return self._items

        def grep_candidates(self, request: GrepRequest) -> list[RetrievedItem]:
            return self._items

        def read_document(self, request: ReadDocumentRequest) -> NormalizedDocument:
            return NormalizedDocument(
                document_id="d", chunk_texts=[self._doc_text], chunk_ids=["c"]
            )

    ra = _FR(_items("a", 2), doc_text="")       # yields an empty document
    rb = _FR(_items("b", 2), doc_text="hello")  # yields real text

    x = CrossCollectionRetriever([ta, tb], {ta: ra, tb: rb})

    # search fuses across collections with RRF interleaving
    fused = x.search(SearchRequest(query="q", limit=3))
    assert [it.item_id for it in fused] == ["a1", "b1", "a2"]

    # read_document probes past the empty collection to the one with content
    doc = x.read_document(ReadDocumentRequest(document_id="d"))
    assert doc.assembled == "hello"

    # grep fans out across every collection
    g = x.grep_candidates(GrepRequest(pattern="x", candidate_limit=10))
    assert len(g) == 4


def _run_all() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except BaseException as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
