"""Tests for the FastAPI HTTP service in :mod:`cosmos_retriever.server`.

These never touch real Cosmos / vLLM: the heavy :class:`CosmosRetriever` is
replaced with a stub so we only exercise the request/response plumbing,
concurrency-pool keying, and error-envelope behaviour.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import cosmos_retriever.server as server_module
from cosmos_retriever.config import get_settings
from cosmos_retriever.retriever import RetrievalResult, RetrievedDocument


class _StubRetriever:
    """Stand-in for CosmosRetriever that records its construction args."""

    instances: list[_StubRetriever] = []

    def __init__(self, settings=None, *, corpus_name=None, reranker=None) -> None:
        self.settings = settings
        self.corpus_name = corpus_name
        self.calls: list[tuple[str, int]] = []
        _StubRetriever.instances.append(self)

    def search(self, query: str, *, max_documents: int = 20) -> RetrievalResult:
        self.calls.append((query, max_documents))
        return RetrievalResult(
            query=query,
            documents=[RetrievedDocument(id="doc-1", text="hello", rank=0)],
            num_turns=3,
            elapsed_s=1.5,
        )


class _BoomRetriever(_StubRetriever):
    def search(self, query: str, *, max_documents: int = 20) -> RetrievalResult:
        raise RuntimeError("vllm unreachable")


def _client(monkeypatch, retriever_cls=_StubRetriever) -> TestClient:
    _StubRetriever.instances = []
    monkeypatch.setattr(server_module, "CosmosRetriever", retriever_cls)
    get_settings.cache_clear()
    app = server_module.create_app(get_settings())
    return TestClient(app)


def test_health_ok(monkeypatch) -> None:
    with _client(monkeypatch) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


def test_search_returns_result_json(monkeypatch) -> None:
    with _client(monkeypatch) as client:
        resp = client.post("/search", json={"query": "who discovered radium?", "maxDocuments": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["query"] == "who discovered radium?"
    assert body["num_turns"] == 3
    assert body["documents"][0]["id"] == "doc-1"
    # max_documents forwarded through the alias.
    assert _StubRetriever.instances[0].calls == [("who discovered radium?", 5)]


def test_search_defaults_max_documents(monkeypatch) -> None:
    with _client(monkeypatch) as client:
        resp = client.post("/search", json={"query": "q"})
    assert resp.status_code == 200
    assert _StubRetriever.instances[0].calls == [("q", 20)]


def test_search_rejects_empty_query(monkeypatch) -> None:
    with _client(monkeypatch) as client:
        resp = client.post("/search", json={"query": ""})
    assert resp.status_code == 422  # pydantic min_length


def test_search_pool_keys_by_corpus(monkeypatch) -> None:
    with _client(monkeypatch) as client:
        client.post("/search", json={"query": "a", "container": "corpus-x"})
        client.post("/search", json={"query": "b", "container": "corpus-x"})
        client.post("/search", json={"query": "c", "container": "corpus-y"})
    # Same container reuses one retriever; a different one builds a second.
    corpora = sorted(r.corpus_name for r in _StubRetriever.instances)
    assert corpora == ["corpus-x", "corpus-y"]


def test_search_error_returns_json_envelope(monkeypatch) -> None:
    with _client(monkeypatch, retriever_cls=_BoomRetriever) as client:
        resp = client.post("/search", json={"query": "boom"})
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"] == "vllm unreachable"
    assert body["type"] == "RuntimeError"
