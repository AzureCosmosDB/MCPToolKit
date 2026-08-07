"""Exhaustive tests for `cosmos_retriever.retrieval.document_resolvers`.

Resolvers turn a ReadDocumentRequest into a NormalizedDocument by compiling a
read, executing it, and assembling chunk text. Tests fake the compiler /
executor / schema and patch ``row_text_fields`` / ``assemble_text`` so every
resolver's id derivation, partition/cross-partition decision, chunk ordering,
and warnings are asserted without Cosmos. build_document_resolver's dispatch
matrix is covered too.
"""
from __future__ import annotations

import pytest

from cosmos_retriever.retrieval import document_resolvers as dr
from cosmos_retriever.retrieval.document_resolvers import (
    DEFAULT_MAX_CHUNKS,
    ChunkedDocumentResolver,
    CrossPartitionChunkedDocumentResolver,
    DocumentResolver,
    ItemIsDocumentResolver,
    build_document_resolver,
)
from cosmos_retriever.retrieval.errors import (
    CrossPartitionQueryDisabled,
    DocumentResolutionUnsupported,
)
from cosmos_retriever.retrieval.models import ReadDocumentRequest

# ────────────────────────────── fakes ─────────────────────────────────────


class FakeCodec:
    def to_document_id(self, raw: str) -> str:
        return f"doc::{raw}"


class FakeSchema:
    def __init__(self, codec=None, item_mode=False, document_id_path="/doc",
                 pk_is_doc_id=False):
        self.identity_codec = codec
        self.is_item_document_mode = item_mode
        self.document_id_path = document_id_path
        self.partition_key_is_document_id = pk_is_doc_id


class FakeCompiled:
    def __init__(self):
        self.projected_aliases = "ALIASES"
        self.warnings: list[str] = []


class FakeCompiler:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.compiled: list[FakeCompiled] = []

    def _mk(self, method, kwargs):
        c = FakeCompiled()
        self.calls.append((method, kwargs))
        self.compiled.append(c)
        return c

    def compile_structured(self, **kw):
        return self._mk("structured", kw)

    def compile_document_read(self, **kw):
        return self._mk("document_read", kw)


class FakeExecutor:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else []
        self.ran: list = []

    def run(self, compiled):
        self.ran.append(compiled)
        return self.rows


class FakePolicy:
    def __init__(self, allow_cross_partition_document_read=True):
        self.allow_cross_partition_document_read = allow_cross_partition_document_read


@pytest.fixture(autouse=True)
def _patch_normalization(monkeypatch):
    # row_text_fields returns the row; assemble_text picks its "text".
    monkeypatch.setattr(dr, "row_text_fields", lambda r, aliases: r)
    monkeypatch.setattr(dr, "assemble_text", lambda fields: fields["text"])


def _row(item_id, text, chunk_order=None):
    return {"item_id": item_id, "text": text, "chunk_order": chunk_order}


# ═══════════════════════ base helpers ═════════════════════════════════════


def test_document_resolver_is_abstract() -> None:
    with pytest.raises(TypeError):
        DocumentResolver(FakeSchema(), FakeCompiler(), FakeExecutor(), FakePolicy())  # type: ignore[abstract]


def test_derive_document_id_prefers_document_id() -> None:
    r = ItemIsDocumentResolver(FakeSchema(), FakeCompiler(), FakeExecutor(), FakePolicy())
    assert r._derive_document_id(ReadDocumentRequest(document_id="D", item_id="I")) == "D"


def test_derive_document_id_falls_back_to_item_id() -> None:
    r = ItemIsDocumentResolver(FakeSchema(), FakeCompiler(), FakeExecutor(), FakePolicy())
    assert r._derive_document_id(ReadDocumentRequest(item_id="I")) == "I"


def test_derive_document_id_empty_when_both_missing() -> None:
    r = ItemIsDocumentResolver(FakeSchema(), FakeCompiler(), FakeExecutor(), FakePolicy())
    assert r._derive_document_id(ReadDocumentRequest()) == ""


def test_derive_document_id_applies_codec() -> None:
    r = ItemIsDocumentResolver(FakeSchema(codec=FakeCodec()), FakeCompiler(), FakeExecutor(), FakePolicy())
    assert r._derive_document_id(ReadDocumentRequest(document_id="D")) == "doc::D"


def test_sorted_rows_orders_by_chunk_order_none_as_zero() -> None:
    rows = [_row("c", "c", 2), _row("a", "a", None), _row("b", "b", 1)]
    ordered = DocumentResolver._sorted_rows(rows)
    assert [r["item_id"] for r in ordered] == ["a", "b", "c"]


# ═══════════════════════ ItemIsDocumentResolver ═══════════════════════════


def test_item_is_document_resolve_wiring() -> None:
    compiler, executor = FakeCompiler(), FakeExecutor(rows=[_row("i1", "t1"), _row("i2", "t2")])
    r = ItemIsDocumentResolver(FakeSchema(item_mode=True), compiler, executor, FakePolicy())
    doc = r.resolve(ReadDocumentRequest(item_id="ITEM"))

    method, kw = compiler.calls[0]
    assert method == "structured"
    assert kw["limit"] == 1
    assert kw["ignored_item_ids"] == []
    assert kw["cross_partition"] is True  # no partition key
    only_filter = kw["filters"][0]
    assert only_filter.logical_field == "item_id" and only_filter.value == "ITEM"
    assert doc.document_id == "ITEM"
    assert doc.chunk_texts == ["t1", "t2"]
    assert doc.chunk_ids == ["i1", "i2"]


def test_item_is_document_prefers_item_id_over_document_id() -> None:
    compiler = FakeCompiler()
    r = ItemIsDocumentResolver(FakeSchema(), compiler, FakeExecutor(), FakePolicy())
    r.resolve(ReadDocumentRequest(item_id="I", document_id="D"))
    assert compiler.calls[0][1]["filters"][0].value == "I"


def test_item_is_document_partition_key_sets_cross_false() -> None:
    compiler = FakeCompiler()
    r = ItemIsDocumentResolver(FakeSchema(), compiler, FakeExecutor(), FakePolicy())
    r.resolve(ReadDocumentRequest(item_id="I", partition_key="pk"))
    assert compiler.calls[0][1]["cross_partition"] is False
    assert compiler.calls[0][1]["partition_key"] == "pk"


# ═══════════════════════ ChunkedDocumentResolver ══════════════════════════


def test_chunked_resolve_wiring_and_sorting() -> None:
    compiler = FakeCompiler()
    executor = FakeExecutor(rows=[_row("c2", "second", 2), _row("c1", "first", 1)])
    r = ChunkedDocumentResolver(FakeSchema(), compiler, executor, FakePolicy())
    doc = r.resolve(ReadDocumentRequest(document_id="DOC"))

    method, kw = compiler.calls[0]
    assert method == "document_read"
    assert kw["document_id"] == "DOC"
    assert kw["max_chunks"] == DEFAULT_MAX_CHUNKS
    assert kw["partition_key"] == "DOC"  # falls back to doc id
    assert kw["cross_partition"] is False
    assert doc.chunk_texts == ["first", "second"]  # sorted by chunk_order
    assert doc.chunk_ids == ["c1", "c2"]
    assert doc.warnings == []


def test_chunked_custom_max_chunks_and_partition_key() -> None:
    compiler = FakeCompiler()
    r = ChunkedDocumentResolver(FakeSchema(), compiler, FakeExecutor(), FakePolicy())
    r.resolve(ReadDocumentRequest(document_id="DOC", max_chunks=5, partition_key="PK"))
    kw = compiler.calls[0][1]
    assert kw["max_chunks"] == 5
    assert kw["partition_key"] == "PK"


def test_chunked_applies_codec_to_document_id() -> None:
    compiler = FakeCompiler()
    r = ChunkedDocumentResolver(FakeSchema(codec=FakeCodec()), compiler, FakeExecutor(), FakePolicy())
    r.resolve(ReadDocumentRequest(document_id="raw"))
    assert compiler.calls[0][1]["document_id"] == "doc::raw"


# ═══════════════════ CrossPartitionChunkedDocumentResolver ════════════════


def test_cross_partition_disabled_raises() -> None:
    r = CrossPartitionChunkedDocumentResolver(
        FakeSchema(), FakeCompiler(), FakeExecutor(),
        FakePolicy(allow_cross_partition_document_read=False),
    )
    with pytest.raises(CrossPartitionQueryDisabled):
        r.resolve(ReadDocumentRequest(document_id="D"))


def test_cross_partition_resolve_wiring_and_warning() -> None:
    compiler = FakeCompiler()
    executor = FakeExecutor(rows=[_row("c2", "b", 2), _row("c1", "a", 1)])
    r = CrossPartitionChunkedDocumentResolver(FakeSchema(), compiler, executor, FakePolicy())
    doc = r.resolve(ReadDocumentRequest(document_id="DOC"))

    kw = compiler.calls[0][1]
    assert kw["document_id"] == "DOC"
    assert kw["partition_key"] is None
    assert kw["cross_partition"] is True  # no partition key
    assert doc.chunk_texts == ["a", "b"]  # sorted
    assert doc.warnings == ["cross-partition document reconstruction"]


def test_cross_partition_with_key_sets_cross_false() -> None:
    compiler = FakeCompiler()
    r = CrossPartitionChunkedDocumentResolver(FakeSchema(), compiler, FakeExecutor(), FakePolicy())
    r.resolve(ReadDocumentRequest(document_id="D", partition_key="PK"))
    kw = compiler.calls[0][1]
    assert kw["partition_key"] == "PK"
    assert kw["cross_partition"] is False


# ═══════════════════════ build_document_resolver ══════════════════════════


def test_build_returns_item_resolver_in_item_mode() -> None:
    resolver = build_document_resolver(
        FakeSchema(item_mode=True), FakeCompiler(), FakeExecutor(), FakePolicy()
    )
    assert isinstance(resolver, ItemIsDocumentResolver)


def test_build_raises_without_document_id_path() -> None:
    with pytest.raises(DocumentResolutionUnsupported):
        build_document_resolver(
            FakeSchema(item_mode=False, document_id_path=None),
            FakeCompiler(), FakeExecutor(), FakePolicy(),
        )


def test_build_returns_chunked_when_pk_is_document_id() -> None:
    resolver = build_document_resolver(
        FakeSchema(item_mode=False, document_id_path="/d", pk_is_doc_id=True),
        FakeCompiler(), FakeExecutor(), FakePolicy(),
    )
    assert isinstance(resolver, ChunkedDocumentResolver)


def test_build_returns_cross_partition_otherwise() -> None:
    resolver = build_document_resolver(
        FakeSchema(item_mode=False, document_id_path="/d", pk_is_doc_id=False),
        FakeCompiler(), FakeExecutor(), FakePolicy(),
    )
    assert isinstance(resolver, CrossPartitionChunkedDocumentResolver)
