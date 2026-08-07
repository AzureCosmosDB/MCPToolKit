"""Exhaustive tests for `cosmos_retriever.retrieval.embedding`.

QueryEmbedder wraps an OpenAI embeddings client. Tests use a fake client to
assert the exact create() call (model, input list, encoding_format, optional
dimensions), the instruction-prefixing of the query text, and that the first
embedding vector is returned.
"""
from __future__ import annotations

from types import SimpleNamespace

from cosmos_retriever.retrieval.embedding import QueryEmbedder


class FakeEmbeddings:
    def __init__(self, embedding):
        self.embedding = embedding
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(embedding=self.embedding)])


class FakeClient:
    def __init__(self, embedding):
        self.embeddings = FakeEmbeddings(embedding)


def _embedder(embedding=None, **kw) -> tuple[QueryEmbedder, FakeClient]:
    client = FakeClient(embedding if embedding is not None else [0.1, 0.2])
    return QueryEmbedder(client=client, model=kw.pop("model", "m"), **kw), client


def test_embed_basic_call_and_return() -> None:
    emb, client = _embedder(embedding=[0.1, 0.2, 0.3])
    out = emb.embed("hello")
    assert out == [0.1, 0.2, 0.3]
    assert client.embeddings.calls == [
        {"model": "m", "input": ["hello"], "encoding_format": "float"}
    ]


def test_embed_no_dimensions_kwarg_when_unset() -> None:
    emb, client = _embedder()
    emb.embed("q")
    assert "dimensions" not in client.embeddings.calls[0]


def test_embed_includes_dimensions_when_set() -> None:
    emb, client = _embedder(dimensions=256)
    emb.embed("q")
    assert client.embeddings.calls[0]["dimensions"] == 256


def test_embed_applies_instruction_prefix() -> None:
    emb, client = _embedder(query_instruction="Find docs")
    emb.embed("cats")
    assert client.embeddings.calls[0]["input"] == ["Instruct: Find docs\nQuery: cats"]


def test_embed_no_instruction_leaves_text_untouched() -> None:
    emb, client = _embedder(query_instruction=None)
    emb.embed("plain")
    assert client.embeddings.calls[0]["input"] == ["plain"]


def test_embed_empty_instruction_is_ignored() -> None:
    emb, client = _embedder(query_instruction="")
    emb.embed("plain")
    assert client.embeddings.calls[0]["input"] == ["plain"]  # falsy instruction skipped


def test_embed_uses_configured_model() -> None:
    emb, client = _embedder(model="text-embedding-3-large")
    emb.embed("q")
    assert client.embeddings.calls[0]["model"] == "text-embedding-3-large"


def test_embed_returns_first_vector_only() -> None:
    client = FakeClient(None)
    client.embeddings = SimpleNamespace(
        calls=[],
        create=lambda **kw: SimpleNamespace(
            data=[SimpleNamespace(embedding=[1.0]), SimpleNamespace(embedding=[9.0])]
        ),
    )
    emb = QueryEmbedder(client=client, model="m")
    assert emb.embed("q") == [1.0]


def test_embed_instruction_and_dimensions_together() -> None:
    emb, client = _embedder(query_instruction="Ins", dimensions=64)
    emb.embed("q")
    call = client.embeddings.calls[0]
    assert call["input"] == ["Instruct: Ins\nQuery: q"]
    assert call["dimensions"] == 64
