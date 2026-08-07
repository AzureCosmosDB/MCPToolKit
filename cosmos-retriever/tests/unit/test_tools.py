"""Exhaustive tests for the agent tools module (`cosmos_retriever.tools`).

Covers, with fakes and no network / Cosmos / OpenAI access:

  1. ToolSchema             — provider wire formats + dispatch + required default
  2. Static schema consts   — search / read / grep / multi / prune shapes
  3. Tool / SerializedTool  — get_format, __repr__, abstractness, placeholder raise
  4. Dynamic schema builders— _search_schema_for / _grep_schema_for field matrices
  5. SearchCorpusTool       — validation, coercion, errors, rerank reorder, limits
  6. GrepCorpusTool         — validation, field errors, empty, regex fallback, tokens
  7. ReadDocumentTool       — ctor invariant, id aliases, item-doc / rerank / truncate
  8. PruneChunksTool        — validation + fixed output
  9. _sanitize_query_value  — vector collapse, recursion, long-string truncation
 10. _SELECT_RE             — accepts SELECT variants, rejects writes
 11. RunQueryTool           — validation, guards, happy path, cap, truncate, error
 12. MultiToolUseTool       — dispatch, unknown-tool raise, json encoding
 13. UserTextTool           — always raises
 14. ToolSet / build        — add/remove/get/formats/repr + build wiring

Fakes: FakeSchema, FakeRetriever, FakeReranker, FakeCosmosClient. Real Pydantic
models (RetrievedItem, NormalizedDocument, RerankResult) are used directly.
`tools.logger` is replaced with a recording stub; `tools.time.perf_counter` is
patched where deterministic timing is asserted.
"""
from __future__ import annotations

import json

import pytest

from cosmos_retriever import tools
from cosmos_retriever.rerank import RerankResult
from cosmos_retriever.retrieval.errors import (
    UnknownField,
    UnsupportedRetrievalCapability,
)
from cosmos_retriever.retrieval.models import NormalizedDocument, RetrievedItem
from cosmos_retriever.tools import (
    _SELECT_RE,
    GREP_CORPUS_SCHEMA,
    MULTI_TOOL_USE_SCHEMA,
    PRUNE_CHUNKS_SCHEMA,
    READ_DOCUMENT_SCHEMA,
    RUN_QUERY_SCHEMA,
    SEARCH_CORPUS_SCHEMA,
    GrepCorpusTool,
    MultiToolUseTool,
    PruneChunksTool,
    ReadDocumentTool,
    RunQueryTool,
    SearchCorpusTool,
    SearchCorpusToolCallMetadata,
    SerializedTool,
    Tool,
    ToolSchema,
    ToolSet,
    UserTextTool,
    _grep_schema_for,
    _sanitize_query_value,
    _search_schema_for,
)
from cosmos_retriever.utils import ProviderFormat

# ────────────────────────────── shared fakes ──────────────────────────────


class _RecordLogger:
    """structlog-like stub that records (event, kwargs) and binds to itself."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def bind(self, **kwargs):
        return self

    def _log(self, level, event, **kwargs):
        self.events.append((level, event, kwargs))

    def info(self, event, **kwargs):
        self._log("info", event, **kwargs)

    def warning(self, event, **kwargs):
        self._log("warning", event, **kwargs)

    def error(self, event, **kwargs):
        self._log("error", event, **kwargs)


class FakeSchema:
    """Stands in for CorpusSchema; only the surface tools.py touches."""

    def __init__(
        self,
        text_fields: list[str] | None = None,
        vector_fields: list[str] | None = None,
        item_document_mode: bool = False,
        summary: str = "SCHEMA-SUMMARY",
    ) -> None:
        self._text = text_fields if text_fields is not None else ["body"]
        self._vector = vector_fields if vector_fields is not None else []
        self.is_item_document_mode = item_document_mode
        self._summary = summary

    def text_field_map(self) -> dict[str, object]:
        return {name: object() for name in self._text}

    def vector_field_map(self) -> dict[str, object]:
        return {name: object() for name in self._vector}

    def agent_field_summary(self) -> str:
        return self._summary


class FakeRetriever:
    """Stands in for CorpusRetriever; records requests, returns canned data."""

    def __init__(
        self,
        schema: FakeSchema | None = None,
        items: list[RetrievedItem] | None = None,
        candidates: list[RetrievedItem] | None = None,
        document: NormalizedDocument | None = None,
        search_exc: Exception | None = None,
        grep_exc: Exception | None = None,
    ) -> None:
        self.schema = schema or FakeSchema()
        self._items = items or []
        self._candidates = candidates if candidates is not None else []
        self._document = document or NormalizedDocument(chunk_texts=[])
        self._search_exc = search_exc
        self._grep_exc = grep_exc
        self.search_requests: list = []
        self.grep_requests: list = []
        self.read_requests: list = []

    def search(self, request):
        self.search_requests.append(request)
        if self._search_exc is not None:
            raise self._search_exc
        return self._items

    def grep_candidates(self, request):
        self.grep_requests.append(request)
        if self._grep_exc is not None:
            raise self._grep_exc
        return self._candidates

    def read_document(self, request):
        self.read_requests.append(request)
        return self._document


class FakeReranker:
    """Callable stand-in for Reranker; emits RerankResults in a fixed order."""

    def __init__(self, order: list[int], tokens: list[int | None] | None = None) -> None:
        self.order = order
        self.tokens = tokens
        self.calls: list[tuple] = []

    def __call__(self, query, documents, max_tokens=None):
        self.calls.append((query, list(documents), max_tokens))
        out: list[RerankResult] = []
        for i, idx in enumerate(self.order):
            tok = self.tokens[i] if self.tokens is not None else None
            out.append(
                RerankResult(
                    document=documents[idx],
                    score=1.0 - 0.1 * i,
                    original_index=idx,
                    tokens=tok,
                )
            )
        return out


class FakeContainer:
    def __init__(self, rows=None, exc: Exception | None = None) -> None:
        self.rows = rows or []
        self.exc = exc
        self.received: tuple | None = None

    def query_items(self, query, enable_cross_partition_query, max_item_count):
        self.received = (query, enable_cross_partition_query, max_item_count)
        if self.exc is not None:
            raise self.exc
        yield from self.rows


class FakeDatabase:
    def __init__(self, container: FakeContainer) -> None:
        self._container = container
        self.requested_container: str | None = None

    def get_container_client(self, name):
        self.requested_container = name
        return self._container


class FakeCosmosClient:
    def __init__(self, container: FakeContainer) -> None:
        self._database = FakeDatabase(container)
        self.requested_database: str | None = None

    def get_database_client(self, name):
        self.requested_database = name
        return self._database


def _item(item_id: str, text: str) -> RetrievedItem:
    return RetrievedItem(item_id=item_id, text=text)


@pytest.fixture(autouse=True)
def _silence_logger(monkeypatch):
    """Replace module logger with a recorder for every test."""
    rec = _RecordLogger()
    monkeypatch.setattr(tools, "logger", rec)
    return rec


# ═══════════════════════ 1. ToolSchema wire formats ═══════════════════════


def _schema() -> ToolSchema:
    return ToolSchema(
        name="t",
        description="d",
        parameters={"q": {"type": "string"}},
        required=["q"],
    )


def test_toolschema_required_defaults_to_empty_list() -> None:
    s = ToolSchema(name="t", description="d", parameters={})
    assert s.required == []


def test_openai_format_is_flat_function() -> None:
    out = _schema()._to_openai_format()
    assert out == {
        "type": "function",
        "name": "t",
        "description": "d",
        "parameters": {
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        },
    }


def test_openai_harmony_format_nests_under_function() -> None:
    out = _schema()._to_openai_harmony_format()
    assert out["type"] == "function"
    assert out["function"]["name"] == "t"
    assert out["function"]["parameters"]["required"] == ["q"]


def test_anthropic_format_uses_input_schema() -> None:
    out = _schema()._to_anthropic_format()
    assert set(out) == {"name", "description", "input_schema"}
    assert "parameters" not in out
    assert out["input_schema"]["properties"] == {"q": {"type": "string"}}


def test_to_provider_format_dispatch() -> None:
    s = _schema()
    assert s.to_provider_format(ProviderFormat.OPENAI) == s._to_openai_format()
    assert s.to_provider_format(ProviderFormat.OPENAI_HARMONY) == s._to_openai_harmony_format()
    assert s.to_provider_format(ProviderFormat.ANTHROPIC) == s._to_anthropic_format()


def test_to_provider_format_unsupported_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported provider format"):
        _schema().to_provider_format(object())  # type: ignore[arg-type]


# ═══════════════════════ 2. static schema constants ═══════════════════════


def test_static_schema_names_and_required() -> None:
    assert SEARCH_CORPUS_SCHEMA.name == "search_corpus"
    assert SEARCH_CORPUS_SCHEMA.required == ["query"]
    assert READ_DOCUMENT_SCHEMA.name == "read_document"
    assert READ_DOCUMENT_SCHEMA.required == ["doc_id"]
    assert GREP_CORPUS_SCHEMA.name == "grep_corpus"
    assert GREP_CORPUS_SCHEMA.required == ["pattern"]
    assert PRUNE_CHUNKS_SCHEMA.name == "prune_chunks"
    assert PRUNE_CHUNKS_SCHEMA.required == ["chunk_ids"]
    assert RUN_QUERY_SCHEMA.name == "execute_query"
    assert RUN_QUERY_SCHEMA.required == ["query"]


def test_multi_tool_use_schema_item_shape() -> None:
    items = MULTI_TOOL_USE_SCHEMA.parameters["tool_calls"]["items"]
    assert items["required"] == ["tool_name", "parameters"]
    assert set(items["properties"]) == {"tool_name", "parameters"}


# ═══════════════════════ 3. Tool / SerializedTool ═════════════════════════


def test_tool_is_abstract() -> None:
    with pytest.raises(TypeError):
        Tool(tool_schema=_schema())  # type: ignore[abstract]


def test_tool_get_format_and_repr() -> None:
    tool = PruneChunksTool()
    assert tool.__repr__() == "Tool(name='prune_chunks')"
    fmt = tool.get_format(ProviderFormat.OPENAI)
    assert fmt["name"] == "prune_chunks"


def test_serialized_tool_cannot_execute() -> None:
    tool = SerializedTool(tool_schema=_schema())
    with pytest.raises(NotImplementedError):
        tool({"q": "x"})


# ═══════════════════ 4. dynamic schema builders ═══════════════════════════


def test_search_schema_single_text_no_vector() -> None:
    s = _search_schema_for(FakeSchema(text_fields=["body"], vector_fields=[]))
    assert s.required == ["query"]
    assert set(s.parameters) == {"query"}
    assert "SCHEMA-SUMMARY" in s.description


def test_search_schema_multi_text_adds_fields_and_requires_it() -> None:
    s = _search_schema_for(FakeSchema(text_fields=["a", "b"], vector_fields=[]))
    assert "fields" in s.parameters
    assert s.required == ["query", "fields"]
    assert "mode" not in s.parameters  # no vector -> no mode


def test_search_schema_multi_vector_adds_vector_field_and_mode() -> None:
    s = _search_schema_for(FakeSchema(text_fields=["a"], vector_fields=["v1", "v2"]))
    assert "vector_field" in s.parameters
    assert "mode" in s.parameters  # text and vector both present
    assert "fields" not in s.parameters  # single text
    assert s.required == ["query"]


def test_search_schema_multi_text_and_vector_full_params() -> None:
    s = _search_schema_for(FakeSchema(text_fields=["a", "b"], vector_fields=["v1", "v2"]))
    assert {"query", "fields", "vector_field", "mode"} <= set(s.parameters)
    assert s.required == ["query", "fields"]


def test_search_schema_single_vector_no_vector_field_param() -> None:
    s = _search_schema_for(FakeSchema(text_fields=["a"], vector_fields=["only"]))
    assert "vector_field" not in s.parameters  # needs >1 vector
    assert "mode" in s.parameters  # still text+vector present


def test_grep_schema_single_text() -> None:
    s = _grep_schema_for(FakeSchema(text_fields=["body"]))
    assert s.required == ["pattern"]
    assert "field" not in s.parameters


def test_grep_schema_multi_text_requires_field() -> None:
    s = _grep_schema_for(FakeSchema(text_fields=["a", "b"]))
    assert "field" in s.parameters
    assert s.required == ["pattern", "field"]


# ═══════════════════════ 5. SearchCorpusTool ══════════════════════════════


def _search_tool(retriever, reranker=None, search_limit=50, display_limit=10):
    return SearchCorpusTool(
        retriever=retriever,
        reranker=reranker,
        search_limit=search_limit,
        display_limit=display_limit,
    )


def test_search_invalid_params_raises() -> None:
    tool = _search_tool(FakeRetriever())
    with pytest.raises(ValueError, match="Invalid params type"):
        tool({"not_query": 1})
    with pytest.raises(ValueError):
        tool(["query"])  # type: ignore[arg-type]


def test_search_passes_request_fields_and_coerces() -> None:
    retr = FakeRetriever(items=[_item("a", "ta")])
    tool = _search_tool(retr, search_limit=7)
    tool(
        {"query": "Q", "fields": "title", "vector_field": "vec", "mode": "hybrid"},
        overrides={"ignore_ids": ["x", "y"]},
    )
    req = retr.search_requests[0]
    assert req.query == "Q"
    assert req.limit == 7
    assert req.text_fields == ["title"]  # str coerced to list
    assert req.vector_field == "vec"
    assert req.mode == "hybrid"
    assert req.ignored_item_ids == ["x", "y"]


def test_search_invalid_mode_falls_back_to_auto() -> None:
    retr = FakeRetriever(items=[])
    tool = _search_tool(retr)
    tool({"query": "Q", "mode": "nonsense"})
    assert retr.search_requests[0].mode == "auto"


def test_search_field_error_returns_message_not_raise() -> None:
    retr = FakeRetriever(search_exc=UnknownField("bad field"))
    tool = _search_tool(retr)
    text, meta = tool({"query": "Q"})
    assert "Search field/mode error: bad field" in text
    assert isinstance(meta, SearchCorpusToolCallMetadata)
    assert meta.returned_chunk_ids == []


def test_search_capability_error_returns_message() -> None:
    retr = FakeRetriever(search_exc=UnsupportedRetrievalCapability("nope"))
    text, meta = _search_tool(retr)({"query": "Q"})
    assert "Search field/mode error: nope" in text
    assert meta.returned_chunk_ids == []


def test_search_no_reranker_passthrough_and_metadata() -> None:
    retr = FakeRetriever(items=[_item("a", "ta"), _item("b", "tb")])
    text, meta = _search_tool(retr)({"query": "Q"})
    assert meta.returned_chunk_ids == ["a", "b"]
    assert meta.rerank_s == 0.0
    assert "ta" in text and "tb" in text


def test_search_empty_results() -> None:
    retr = FakeRetriever(items=[])
    reranker = FakeReranker(order=[0])
    text, meta = _search_tool(retr, reranker=reranker)({"query": "Q"})
    assert meta.returned_chunk_ids == []
    assert reranker.calls == []  # reranker skipped when no ids
    assert text == "No results found"


def test_search_with_reranker_reorders_by_original_index() -> None:
    retr = FakeRetriever(items=[_item("a", "ta"), _item("b", "tb"), _item("c", "tc")])
    reranker = FakeReranker(order=[2, 0, 1], tokens=[5, 6, 7])
    text, meta = _search_tool(retr, reranker=reranker)({"query": "Q"})
    assert meta.returned_chunk_ids == ["c", "a", "b"]
    assert reranker.calls[0][0] == "Q"
    assert "(5 tokens)" in text  # token counts propagated into formatting


def test_search_passes_max_tokens_override_to_reranker() -> None:
    retr = FakeRetriever(items=[_item("a", "ta")])
    reranker = FakeReranker(order=[0])
    _search_tool(retr, reranker=reranker)({"query": "Q"}, overrides={"max_tokens": 123})
    assert reranker.calls[0][2] == 123


def test_search_display_limit_truncates() -> None:
    retr = FakeRetriever(items=[_item(str(i), f"t{i}") for i in range(5)])
    _, meta = _search_tool(retr, display_limit=2)({"query": "Q"})
    assert meta.returned_chunk_ids == ["0", "1"]


def test_search_timing_rounded_to_three_decimals(monkeypatch) -> None:
    seq = iter([0.0, 0.512812, 1.0, 2.517001])
    monkeypatch.setattr(tools.time, "perf_counter", lambda: next(seq))
    retr = FakeRetriever(items=[_item("a", "ta")])
    reranker = FakeReranker(order=[0])
    _, meta = _search_tool(retr, reranker=reranker)({"query": "Q"})
    assert meta.retrieval_s == 0.513
    assert meta.rerank_s == 1.517


# ═══════════════════════ 6. GrepCorpusTool ════════════════════════════════


def test_grep_invalid_params_raises() -> None:
    with pytest.raises(ValueError, match="Invalid params type"):
        GrepCorpusTool(FakeRetriever())({"nope": 1})


def test_grep_field_error_returns_message() -> None:
    retr = FakeRetriever(grep_exc=UnknownField("bad"))
    text, meta = GrepCorpusTool(retr)({"pattern": "x"})
    assert "Grep field error: bad" in text
    assert meta.returned_chunk_ids == []


def test_grep_no_candidates_returns_no_results() -> None:
    retr = FakeRetriever(candidates=[])
    text, meta = GrepCorpusTool(retr)({"pattern": "x"})
    assert text == "No results found"
    assert meta.returned_chunk_ids == []


def test_grep_filters_by_case_insensitive_regex() -> None:
    retr = FakeRetriever(
        candidates=[_item("a", "has FOO here"), _item("b", "no match"), _item("c", "foobar")]
    )
    _, meta = GrepCorpusTool(retr)({"pattern": "foo"})
    assert meta.returned_chunk_ids == ["a", "c"]


def test_grep_invalid_regex_falls_back_to_candidates() -> None:
    cands = [_item(str(i), f"t{i}") for i in range(7)]
    retr = FakeRetriever(candidates=cands)
    _, meta = GrepCorpusTool(retr)({"pattern": "["})  # invalid regex
    assert meta.returned_chunk_ids == ["0", "1", "2", "3", "4"]  # first 5


def test_grep_token_counter_annotates() -> None:
    retr = FakeRetriever(candidates=[_item("a", "abc")])
    text, _ = GrepCorpusTool(retr, token_counter=len)({"pattern": "abc"})
    assert "(3 tokens)" in text


def test_grep_field_forwarded_to_request() -> None:
    retr = FakeRetriever(candidates=[_item("a", "abc")])
    GrepCorpusTool(retr)({"pattern": "abc", "field": "body"})
    assert retr.grep_requests[0].text_field == "body"


# ═══════════════════════ 7. ReadDocumentTool ══════════════════════════════


def test_read_ctor_max_tokens_requires_counter() -> None:
    with pytest.raises(ValueError, match="token_counter is required"):
        ReadDocumentTool(FakeRetriever(), max_tokens=10)


def test_read_invalid_params_raises() -> None:
    with pytest.raises(ValueError, match="Invalid params type"):
        ReadDocumentTool(FakeRetriever())({"nope": 1})


def test_read_accepts_doc_id_and_id_aliases() -> None:
    retr = FakeRetriever(document=NormalizedDocument(chunk_texts=["body"]))
    ReadDocumentTool(retr)({"doc_id": "d1"})
    ReadDocumentTool(retr)({"id": "d2"})
    assert retr.read_requests[0].document_id == "d1"
    assert retr.read_requests[1].document_id == "d2"


def test_read_item_document_mode_verbatim_no_counter() -> None:
    retr = FakeRetriever(
        schema=FakeSchema(item_document_mode=True),
        document=NormalizedDocument(chunk_texts=["whole doc"]),
    )
    text, meta = ReadDocumentTool(retr)({"doc_id": "d"})
    assert text == "whole doc"
    assert meta is None


def test_read_item_document_mode_with_counter_header() -> None:
    retr = FakeRetriever(
        schema=FakeSchema(item_document_mode=True),
        document=NormalizedDocument(chunk_texts=["abcde"]),
    )
    text, _ = ReadDocumentTool(retr, token_counter=len)({"doc_id": "d"})
    assert text == "# Document (5 tokens)\nabcde"


def test_read_chunk_mode_rerank_filters_kept_chunks() -> None:
    retr = FakeRetriever(document=NormalizedDocument(chunk_texts=["A", "B", "C"]))
    reranker = FakeReranker(order=[0, 2])  # keep indices 0 and 2
    tool = ReadDocumentTool(retr, reranker=reranker, token_counter=len, max_tokens=100)
    text, _ = tool({"doc_id": "d"}, overrides={"query": "Q", "max_tokens": 100})
    assert text.endswith("AC")  # original order preserved, B dropped


def test_read_chunk_mode_token_truncation_without_reranker() -> None:
    retr = FakeRetriever(document=NormalizedDocument(chunk_texts=["aa", "bb", "cc"]))
    tool = ReadDocumentTool(retr, token_counter=len, max_tokens=4)
    text, _ = tool({"doc_id": "d"})
    assert text == "# Document (4 tokens)\naabb"  # cc dropped by budget


def test_read_chunk_mode_plain_no_counter() -> None:
    retr = FakeRetriever(document=NormalizedDocument(chunk_texts=["x", "y"]))
    text, meta = ReadDocumentTool(retr)({"doc_id": "d"})
    assert text == "xy"
    assert meta is None


# ═══════════════════════ 8. PruneChunksTool ═══════════════════════════════


def test_prune_invalid_params_raises() -> None:
    with pytest.raises(ValueError, match="Invalid params type"):
        PruneChunksTool()({"nope": 1})


def test_prune_returns_fixed_output() -> None:
    text, meta = PruneChunksTool()({"chunk_ids": ["a", "b"]})
    assert text == "Pruned"
    assert meta is None


# ═══════════════════ 9. _sanitize_query_value ═════════════════════════════


def test_sanitize_collapses_numeric_vector() -> None:
    assert _sanitize_query_value(list(range(40))) == "<vector: 40 values>"


def test_sanitize_short_list_recursed_not_collapsed() -> None:
    assert _sanitize_query_value([1, 2, 3]) == [1, 2, 3]


def test_sanitize_non_numeric_long_list_recursed() -> None:
    val = ["s"] * 40
    assert _sanitize_query_value(val) == ["s"] * 40  # not all-numeric -> not collapsed


def test_sanitize_nested_dict_and_long_string() -> None:
    long = "z" * 5000
    out = _sanitize_query_value({"k": long, "n": {"vec": list(range(50))}})
    assert out["k"].endswith("\u2026") and len(out["k"]) == 4001
    assert out["n"]["vec"] == "<vector: 50 values>"


def test_sanitize_scalar_passthrough() -> None:
    assert _sanitize_query_value(7) == 7
    assert _sanitize_query_value("short") == "short"


# ═══════════════════════ 10. _SELECT_RE ═══════════════════════════════════


@pytest.mark.parametrize(
    "q",
    ["select * from c", "  SELECT c.id", "(select 1)", "((  select x", "\n\tSELECT a"],
)
def test_select_re_accepts(q: str) -> None:
    assert _SELECT_RE.match(q)


@pytest.mark.parametrize(
    "q",
    ["insert into c", "update c set x=1", "delete from c", "drop table c", "with t as ()"],
)
def test_select_re_rejects(q: str) -> None:
    assert _SELECT_RE.match(q) is None


# ═══════════════════════ 11. RunQueryTool ═════════════════════════════════


def _run_tool(container, **kw):
    return RunQueryTool(
        client=FakeCosmosClient(container),
        default_database=kw.pop("db", "corpusdb"),
        default_container=kw.pop("cont", "corpuscont"),
        **kw,
    )


def test_run_invalid_params_raises() -> None:
    with pytest.raises(ValueError, match="Invalid params type"):
        _run_tool(FakeContainer())({"nope": 1})


def test_run_empty_query_error() -> None:
    text, _ = _run_tool(FakeContainer())({"query": "   "})
    assert "must be a non-empty SELECT query" in text


def test_run_non_select_rejected() -> None:
    text, _ = _run_tool(FakeContainer())({"query": "DELETE FROM c"})
    assert "only read-only SELECT queries are allowed" in text


def test_run_missing_db_or_container_error() -> None:
    tool = RunQueryTool(client=FakeCosmosClient(FakeContainer()))
    text, _ = tool({"query": "SELECT * FROM c"})
    assert "specify both 'database' and 'container'" in text


def test_run_happy_path_header_and_body() -> None:
    container = FakeContainer(rows=[{"id": 1}, {"id": 2}])
    text, _ = _run_tool(container)({"query": "SELECT * FROM c"})
    header, body = text.split("\n", 1)
    assert header == "# execute_query: 2 row(s) from corpusdb/corpuscont"
    assert json.loads(body) == [{"id": 1}, {"id": 2}]


def test_run_caps_rows_and_marks_capped() -> None:
    container = FakeContainer(rows=[{"id": i} for i in range(25)])
    text, _ = _run_tool(container, max_rows=3)({"query": "SELECT * FROM c"})
    header = text.split("\n", 1)[0]
    assert "3 row(s)" in header and "capped at 3" in header


def test_run_truncates_large_body() -> None:
    container = FakeContainer(rows=[{"blob": "x" * 500}])
    text, _ = _run_tool(container, max_chars=50)({"query": "SELECT * FROM c"})
    header, body = text.split("\n", 1)
    assert "[output truncated]" in header
    assert body.endswith("\u2026")


def test_run_client_exception_returned_as_text() -> None:
    container = FakeContainer(exc=ValueError("boom"))
    text, _ = _run_tool(container)({"query": "SELECT * FROM c"})
    assert text == "execute_query error: ValueError: boom"


def test_run_explicit_db_container_override_defaults() -> None:
    container = FakeContainer(rows=[])
    tool = _run_tool(container)
    tool({"query": "SELECT * FROM c", "database": "d2", "container": "c2"})
    assert tool._client.requested_database == "d2"


# ═══════════════════════ 12. MultiToolUseTool ═════════════════════════════


class _EchoTool(Tool):
    def __call__(self, params, overrides=None):
        return f"echo:{params.get('v')}", None


def _echo_toolset() -> ToolSet:
    ts = ToolSet()
    ts.add_tool(_EchoTool(tool_schema=ToolSchema(name="echo", description="d", parameters={})))
    return ts


def test_multi_tool_dispatches_and_json_encodes() -> None:
    tool = MultiToolUseTool(_echo_toolset())
    text, meta = tool(
        {"tool_calls": [{"tool_name": "echo", "parameters": {"v": 1}},
                        {"tool_name": "echo", "parameters": {"v": 2}}]}
    )
    assert json.loads(text) == ["echo:1", "echo:2"]
    assert meta is None


def test_multi_tool_unknown_tool_raises() -> None:
    tool = MultiToolUseTool(_echo_toolset())
    with pytest.raises(ValueError, match="not found in toolset"):
        tool({"tool_calls": [{"tool_name": "missing", "parameters": {}}]})


# ═══════════════════════ 13. UserTextTool ═════════════════════════════════


def test_user_text_tool_always_raises() -> None:
    with pytest.raises(ValueError, match="should not be called directly"):
        UserTextTool()({})


# ═══════════════════════ 14. ToolSet / build ══════════════════════════════


def test_toolset_add_duplicate_raises() -> None:
    ts = ToolSet()
    ts.add_tool(PruneChunksTool())
    with pytest.raises(ValueError, match="already exists"):
        ts.add_tool(PruneChunksTool())


def test_toolset_remove_missing_is_noop_and_get() -> None:
    ts = ToolSet()
    tool = PruneChunksTool()
    ts.add_tool(tool)
    ts.remove_tool("does_not_exist")  # no raise
    assert ts.get_tool("prune_chunks") is tool
    ts.remove_tool("prune_chunks")
    assert ts.get_tool("prune_chunks") is None


def test_toolset_get_formats_one_per_tool() -> None:
    ts = ToolSet()
    ts.add_tool(PruneChunksTool())
    ts.add_tool(UserTextTool())
    fmts = ts.get_formats(ProviderFormat.OPENAI)
    assert {f["name"] for f in fmts} == {"prune_chunks", "user_text"}


def test_toolset_repr_sorted_with_name() -> None:
    ts = ToolSet(name="mine")
    ts.add_tool(UserTextTool())
    ts.add_tool(PruneChunksTool())
    assert repr(ts) == "ToolSet (mine)[2 tools: prune_chunks, user_text]"


def test_build_requires_retriever_or_deps() -> None:
    with pytest.raises(ValueError, match="requires either 'retriever'"):
        ToolSet.build()


def test_build_default_toolset_has_four_tools() -> None:
    ts = ToolSet.build(retriever=FakeRetriever())
    assert set(ts.tools) == {"search_corpus", "grep_corpus", "read_document", "prune_chunks"}


def test_build_enable_raw_query_adds_execute_query() -> None:
    ts = ToolSet.build(
        retriever=FakeRetriever(),
        enable_raw_query=True,
        cosmos_client=FakeCosmosClient(FakeContainer()),
    )
    assert "execute_query" in ts.tools
    assert len(ts.tools) == 5


def test_build_raw_query_not_added_without_client() -> None:
    ts = ToolSet.build(retriever=FakeRetriever(), enable_raw_query=True)
    assert "execute_query" not in ts.tools
