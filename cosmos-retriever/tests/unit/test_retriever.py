"""Exhaustive tests for `CorpusRetriever` (`cosmos_retriever.retrieval.retriever`).

`CorpusRetriever` is a thin orchestrator: it wires collaborators in ``__init__``
and, per call, resolves schema fields, asks the planner for a strategy, optionally
embeds the query, and delegates execution. These tests isolate it by patching the
five collaborator constructors in the module with recorders returning fakes /
sentinels, so every branch of ``__init__`` / ``search`` / ``grep_candidates`` /
``read_document`` is exercised without Cosmos, embeddings, or real strategies.

Fakes: FakeSchema, FakePlanner, FakeSearchStrategy, FakeGrepStrategy,
FakeEmbedder, FakeResolver. Real Pydantic models (SearchRequest, GrepRequest,
ReadDocumentRequest, RetrievedItem, NormalizedDocument, PartitionQueryPolicy)
are used directly.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from cosmos_retriever.retrieval import retriever as retr_mod
from cosmos_retriever.retrieval.errors import EmbeddingProfileMismatch
from cosmos_retriever.retrieval.models import (
    GrepRequest,
    NormalizedDocument,
    PartitionQueryPolicy,
    ReadDocumentRequest,
    RetrievedItem,
    SearchRequest,
)
from cosmos_retriever.retrieval.retriever import CorpusRetriever

# ────────────────────────────── fakes ─────────────────────────────────────


class _CallRecorder:
    """Records positional/keyword args and returns a fixed value."""

    def __init__(self, return_value: object) -> None:
        self.return_value = return_value
        self.calls: list[tuple[tuple, dict]] = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.return_value


class FakeSchema:
    def __init__(self) -> None:
        self.vector_calls: list = []
        self.text_calls: list = []

    def resolve_vector_config(self, name):
        self.vector_calls.append(name)
        return object()

    def resolve_text_fields(self, names):
        self.text_calls.append(names)
        return []


class FakeSearchStrategy:
    def __init__(self, requires_embedding: bool, result: list[RetrievedItem]) -> None:
        self.requires_embedding = requires_embedding
        self._result = result
        self.execute_calls: list[tuple] = []

    def execute(self, req, ctx):
        self.execute_calls.append((req, ctx))
        return self._result


class FakeGrepStrategy:
    def __init__(self, result: list[RetrievedItem]) -> None:
        self._result = result
        self.candidate_calls: list[tuple] = []

    def candidates(self, req, ctx):
        self.candidate_calls.append((req, ctx))
        return self._result


class FakePlanner:
    def __init__(self, search_strategy=None, grep_strategy=None) -> None:
        self._search = search_strategy
        self._grep = grep_strategy
        self.search_reqs: list = []
        self.grep_reqs: list = []

    def plan_search(self, req):
        self.search_reqs.append(req)
        return self._search

    def plan_grep(self, req):
        self.grep_reqs.append(req)
        return self._grep


class FakeEmbedder:
    def __init__(self, vector: list[float]) -> None:
        self.vector = vector
        self.calls: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return self.vector


class FakeResolver:
    def __init__(self, document: NormalizedDocument) -> None:
        self.document = document
        self.calls: list = []

    def resolve(self, req):
        self.calls.append(req)
        return self.document


def _item(item_id: str, text: str = "") -> RetrievedItem:
    return RetrievedItem(item_id=item_id, text=text)


def _build(
    monkeypatch,
    *,
    search_strategy: FakeSearchStrategy | None = None,
    grep_strategy: FakeGrepStrategy | None = None,
    embedder: FakeEmbedder | None = None,
    policy: PartitionQueryPolicy | None = None,
    document: NormalizedDocument | None = None,
) -> SimpleNamespace:
    """Patch collaborator constructors and build an isolated CorpusRetriever."""
    schema = FakeSchema()
    planner = FakePlanner(search_strategy, grep_strategy)
    resolver = FakeResolver(document or NormalizedDocument(chunk_texts=[]))

    compiler_sentinel = object()
    executor_sentinel = object()
    ctx_sentinel = object()

    comp_rec = _CallRecorder(compiler_sentinel)
    exec_rec = _CallRecorder(executor_sentinel)
    planner_rec = _CallRecorder(planner)
    ctx_rec = _CallRecorder(ctx_sentinel)
    resolver_rec = _CallRecorder(resolver)

    monkeypatch.setattr(retr_mod, "CosmosQueryCompiler", comp_rec)
    monkeypatch.setattr(retr_mod, "CosmosExecutor", exec_rec)
    monkeypatch.setattr(retr_mod, "RetrievalPlanner", planner_rec)
    monkeypatch.setattr(retr_mod, "RetrievalContext", ctx_rec)
    monkeypatch.setattr(retr_mod, "build_document_resolver", resolver_rec)

    container = object()
    capabilities = object()
    retriever = CorpusRetriever(
        container=container,
        schema=schema,  # type: ignore[arg-type]
        capabilities=capabilities,  # type: ignore[arg-type]
        query_embedder=embedder,  # type: ignore[arg-type]
        partition_policy=policy,
    )
    return SimpleNamespace(
        retriever=retriever,
        schema=schema,
        planner=planner,
        resolver=resolver,
        embedder=embedder,
        container=container,
        capabilities=capabilities,
        compiler_sentinel=compiler_sentinel,
        executor_sentinel=executor_sentinel,
        ctx_sentinel=ctx_sentinel,
        comp_rec=comp_rec,
        exec_rec=exec_rec,
        planner_rec=planner_rec,
        ctx_rec=ctx_rec,
        resolver_rec=resolver_rec,
    )


# ═══════════════════════════ __init__ wiring ══════════════════════════════


def test_init_defaults_policy_to_partition_query_policy(monkeypatch) -> None:
    b = _build(monkeypatch)
    assert isinstance(b.retriever.policy, PartitionQueryPolicy)


def test_init_uses_provided_policy(monkeypatch) -> None:
    policy = PartitionQueryPolicy()
    b = _build(monkeypatch, policy=policy)
    assert b.retriever.policy is policy


def test_init_stores_schema_capabilities_embedder(monkeypatch) -> None:
    embedder = FakeEmbedder([0.1])
    b = _build(monkeypatch, embedder=embedder)
    assert b.retriever.schema is b.schema
    assert b.retriever.capabilities is b.capabilities
    assert b.retriever._embedder is embedder


def test_init_embedder_defaults_to_none(monkeypatch) -> None:
    b = _build(monkeypatch)
    assert b.retriever._embedder is None


def test_init_constructs_compiler_and_executor_with_expected_args(monkeypatch) -> None:
    b = _build(monkeypatch)
    assert b.comp_rec.calls == [((b.schema,), {})]
    assert b.exec_rec.calls == [((b.container,), {})]
    assert b.retriever._compiler is b.compiler_sentinel
    assert b.retriever._executor is b.executor_sentinel


def test_init_constructs_planner_positionally(monkeypatch) -> None:
    b = _build(monkeypatch)
    (args, kwargs) = b.planner_rec.calls[0]
    assert args == (b.schema, b.capabilities, b.retriever.policy)
    assert kwargs == {}
    assert b.retriever._planner is b.planner


def test_init_constructs_context_with_keywords(monkeypatch) -> None:
    b = _build(monkeypatch)
    (_args, kwargs) = b.ctx_rec.calls[0]
    assert kwargs == {
        "schema": b.schema,
        "compiler": b.compiler_sentinel,
        "executor": b.executor_sentinel,
        "capabilities": b.capabilities,
        "policy": b.retriever.policy,
    }
    assert b.retriever._ctx is b.ctx_sentinel


def test_init_builds_resolver_positionally(monkeypatch) -> None:
    b = _build(monkeypatch)
    (args, kwargs) = b.resolver_rec.calls[0]
    assert args == (
        b.schema,
        b.compiler_sentinel,
        b.executor_sentinel,
        b.retriever.policy,
    )
    assert kwargs == {}
    assert b.retriever._resolver is b.resolver


# ═══════════════════════════════ search ═══════════════════════════════════


def test_search_resolves_vector_field_when_present(monkeypatch) -> None:
    strat = FakeSearchStrategy(requires_embedding=False, result=[])
    b = _build(monkeypatch, search_strategy=strat)
    b.retriever.search(SearchRequest(query="q", vector_field="vec"))
    assert b.schema.vector_calls == ["vec"]


def test_search_skips_vector_resolution_when_absent(monkeypatch) -> None:
    strat = FakeSearchStrategy(requires_embedding=False, result=[])
    b = _build(monkeypatch, search_strategy=strat)
    b.retriever.search(SearchRequest(query="q"))
    assert b.schema.vector_calls == []


def test_search_resolves_text_fields_when_present(monkeypatch) -> None:
    strat = FakeSearchStrategy(requires_embedding=False, result=[])
    b = _build(monkeypatch, search_strategy=strat)
    b.retriever.search(SearchRequest(query="q", text_fields=["a", "b"]))
    assert b.schema.text_calls == [["a", "b"]]


def test_search_skips_text_resolution_when_none_or_empty(monkeypatch) -> None:
    strat = FakeSearchStrategy(requires_embedding=False, result=[])
    b = _build(monkeypatch, search_strategy=strat)
    b.retriever.search(SearchRequest(query="q", text_fields=None))
    b.retriever.search(SearchRequest(query="q", text_fields=[]))
    assert b.schema.text_calls == []


def test_search_calls_planner_and_returns_execute_result(monkeypatch) -> None:
    items = [_item("a"), _item("b")]
    strat = FakeSearchStrategy(requires_embedding=False, result=items)
    b = _build(monkeypatch, search_strategy=strat)
    req = SearchRequest(query="q")
    out = b.retriever.search(req)
    assert out is items
    assert b.planner.search_reqs == [req]


def test_search_passes_ctx_identity_to_execute(monkeypatch) -> None:
    strat = FakeSearchStrategy(requires_embedding=False, result=[])
    b = _build(monkeypatch, search_strategy=strat)
    req = SearchRequest(query="q")
    b.retriever.search(req)
    (passed_req, passed_ctx) = strat.execute_calls[0]
    assert passed_req is req
    assert passed_ctx is b.retriever._ctx


def test_search_no_embedding_needed_ignores_missing_embedder(monkeypatch) -> None:
    strat = FakeSearchStrategy(requires_embedding=False, result=[])
    b = _build(monkeypatch, search_strategy=strat, embedder=None)
    req = SearchRequest(query="q")  # query_vector None, embedder None
    b.retriever.search(req)  # must not raise
    assert strat.execute_calls[0][0].query_vector is None


def test_search_embedding_needed_but_vector_present_skips_embedder(monkeypatch) -> None:
    strat = FakeSearchStrategy(requires_embedding=True, result=[])
    embedder = FakeEmbedder([9.9])
    b = _build(monkeypatch, search_strategy=strat, embedder=embedder)
    req = SearchRequest(query="q", query_vector=[1.0, 2.0])
    b.retriever.search(req)
    assert embedder.calls == []
    assert strat.execute_calls[0][0].query_vector == [1.0, 2.0]


def test_search_embeds_query_when_needed_and_updates_request(monkeypatch) -> None:
    strat = FakeSearchStrategy(requires_embedding=True, result=[])
    embedder = FakeEmbedder([0.1, 0.2, 0.3])
    b = _build(monkeypatch, search_strategy=strat, embedder=embedder)
    req = SearchRequest(query="hello")
    b.retriever.search(req)
    assert embedder.calls == ["hello"]
    executed_req = strat.execute_calls[0][0]
    assert executed_req.query_vector == [0.1, 0.2, 0.3]
    assert executed_req.query == "hello"
    assert req.query_vector is None  # original request not mutated


def test_search_embedding_needed_without_embedder_raises(monkeypatch) -> None:
    strat = FakeSearchStrategy(requires_embedding=True, result=[])
    b = _build(monkeypatch, search_strategy=strat, embedder=None)
    with pytest.raises(EmbeddingProfileMismatch):
        b.retriever.search(SearchRequest(query="q"))
    assert strat.execute_calls == []  # execution never reached


# ═══════════════════════════ grep_candidates ══════════════════════════════


def test_grep_resolves_single_text_field_when_present(monkeypatch) -> None:
    strat = FakeGrepStrategy(result=[])
    b = _build(monkeypatch, grep_strategy=strat)
    b.retriever.grep_candidates(GrepRequest(pattern="p", text_field="body"))
    assert b.schema.text_calls == [["body"]]


def test_grep_skips_text_resolution_when_absent(monkeypatch) -> None:
    strat = FakeGrepStrategy(result=[])
    b = _build(monkeypatch, grep_strategy=strat)
    b.retriever.grep_candidates(GrepRequest(pattern="p"))
    assert b.schema.text_calls == []


def test_grep_calls_planner_and_returns_candidates(monkeypatch) -> None:
    items = [_item("x")]
    strat = FakeGrepStrategy(result=items)
    b = _build(monkeypatch, grep_strategy=strat)
    req = GrepRequest(pattern="p")
    out = b.retriever.grep_candidates(req)
    assert out is items
    assert b.planner.grep_reqs == [req]


def test_grep_passes_ctx_identity(monkeypatch) -> None:
    strat = FakeGrepStrategy(result=[])
    b = _build(monkeypatch, grep_strategy=strat)
    req = GrepRequest(pattern="p")
    b.retriever.grep_candidates(req)
    (passed_req, passed_ctx) = strat.candidate_calls[0]
    assert passed_req is req
    assert passed_ctx is b.retriever._ctx


# ═══════════════════════════ read_document ════════════════════════════════


def test_read_document_delegates_to_resolver(monkeypatch) -> None:
    doc = NormalizedDocument(chunk_texts=["hello"])
    b = _build(monkeypatch, document=doc)
    req = ReadDocumentRequest(document_id="d1")
    out = b.retriever.read_document(req)
    assert out is doc
    assert b.resolver.calls == [req]
