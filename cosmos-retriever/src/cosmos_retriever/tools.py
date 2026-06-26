"""Tool implementations for the Harness-1 retrieval agent.

The corpus lives in Azure Cosmos DB for NoSQL and is queried with hybrid
RRF search (vector + full-text) plus an optional reranker. There are five
tools (matching the trained model's output schema):

* :class:`SearchCorpusTool` — hybrid vector + FTS search over the corpus.
* :class:`GrepCorpusTool` — BM25-narrowed regex search.
* :class:`ReadDocumentTool` — fetch all chunks of a document by its docid.
* :class:`PruneChunksTool` — record chunk-ids whose context should be removed.
* :class:`MultiToolUseTool` — wraps a parallel tool-call bundle (the trained
  model emits a single ``functions.multi_tool_use`` call to fan out).

Plus :class:`UserTextTool`, the sentinel tool for assistant text in the
trajectory, and :class:`SerializedTool`, a placeholder used by tests/round-trips.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, TypeAlias, cast

import openai
import structlog
import tenacity
from azure.cosmos import ContainerProxy, DatabaseProxy
from azure.cosmos.exceptions import CosmosHttpResponseError
from pydantic import BaseModel, Field

from cosmos_retriever.rerank import Reranker
from cosmos_retriever.utils import ProviderFormat

logger = structlog.get_logger("cosmos_retriever.tools")


# ============================================================================
# Cosmos helpers (concurrency throttle + retry)
# ============================================================================


def _read_positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("invalid_int_env", name=name, value=raw, default=default)
        return default
    if value < 1:
        logger.warning("invalid_positive_int_env", name=name, value=raw, default=default)
        return default
    return value


COSMOS_QUERY_MAX_CONCURRENCY = _read_positive_int_env("COSMOS_QUERY_MAX_CONCURRENCY", 8)
_COSMOS_QUERY_SEMAPHORE = threading.BoundedSemaphore(COSMOS_QUERY_MAX_CONCURRENCY)


def _is_retryable_cosmos_error(exc: BaseException) -> bool:
    if not isinstance(exc, CosmosHttpResponseError):
        return False
    status = getattr(exc, "status_code", None)
    return status in (408, 429, 449, 500, 502, 503, 504)


@tenacity.retry(
    stop=tenacity.stop_after_attempt(5),
    wait=tenacity.wait_exponential(multiplier=1, min=4, max=15),
    retry=tenacity.retry_if_exception(_is_retryable_cosmos_error),
    before_sleep=lambda retry_state: logger.warning(
        "retry_cosmos_query",
        attempt=retry_state.attempt_number,
        error=str(retry_state.outcome.exception()) if retry_state.outcome else None,
    ),
)
def _query_with_retry(
    container: ContainerProxy,
    query: str,
    parameters: list[dict[str, Any]],
    *,
    partition_key: str | None = None,
) -> list[dict[str, Any]]:
    """Execute a Cosmos NoSQL query with retry on transient errors."""

    start = time.perf_counter()
    with _COSMOS_QUERY_SEMAPHORE:
        kwargs: dict[str, Any] = {"query": query, "parameters": parameters}
        if partition_key is not None:
            kwargs["partition_key"] = partition_key
        else:
            kwargs["enable_cross_partition_query"] = True
        result = list(container.query_items(**kwargs))
    elapsed_ms = (time.perf_counter() - start) * 1000
    if elapsed_ms > 4500:
        logger.warning(
            "slow_cosmos_query",
            elapsed_ms=round(elapsed_ms, 1),
            cosmos_max_concurrency=COSMOS_QUERY_MAX_CONCURRENCY,
        )
    return result


# ----- Stopword + tokenisation helpers for FullTextScore --------------------

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

# Cosmos's en-US analyzer doesn't strip stopwords during FullTextScore scoring,
# and FullTextScore is hard-capped at 30 terms per call. Drop standard English
# stopwords client-side to (a) stay under 30 and (b) keep BM25 signal on the
# rare/content tokens.
_STOPWORDS = frozenset(
    ["a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by", "can", "did", "do", "does", "doing", "don", "down", "during", "each", "few", "for", "from", "further", "had", "has", "have", "having", "he", "her", "here", "hers", "herself", "him", "himself", "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just", "like", "me", "more", "most", "my", "myself", "no", "nor", "not", "now", "of", "off", "on", "once", "only", "or", "other", "our", "ours", "ourselves", "out", "over", "own", "please", "same", "she", "should", "so", "some", "such", "tell", "than", "that", "the", "their", "theirs", "them", "themselves", "then", "there", "these", "they", "this", "those", "through", "to", "too", "under", "until", "up", "very", "was", "we", "were", "what", "when", "where", "which", "while", "who", "whom", "why", "will", "with", "would", "you", "your", "yours", "yourself", "yourselves"]
)

_FTS_MAX_TERMS = 30  # Cosmos hard limit on FullTextScore arity.


def _tokenize_for_fts(query: str) -> list[str]:
    """Tokenise for Cosmos FullTextScore: lowercase, drop stopwords, dedupe, cap at 30."""

    out: list[str] = []
    seen: set[str] = set()
    for raw in _TOKEN_RE.findall(query):
        t = raw.lower()
        if t in _STOPWORDS or t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= _FTS_MAX_TERMS:
            break
    return out


def _fts_literal_args(terms: list[str]) -> str:
    """Render terms as comma-separated string literals for FullTextScore.

    The 2nd+ arguments of FullTextScore must be literals, not bound parameters.
    """

    def esc(t: str) -> str:
        return '"' + t.replace("\\", "\\\\").replace('"', '\\"') + '"'

    return ", ".join(esc(t) for t in terms)


# ============================================================================
# Tool schema (provider-agnostic) + provider format conversion
# ============================================================================


class ToolSchema(BaseModel):
    """Provider-agnostic JSON-Schema-like tool definition."""

    name: str
    description: str
    parameters: dict[str, Any]
    required: list[str] = Field(default_factory=list)

    def _to_openai_format(self) -> dict[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": self.parameters,
                "required": self.required,
            },
        }

    def _to_openai_harmony_format(self) -> dict[str, Any]:
        # Harmony uses the OpenAI-Chat-Completions function shape (function:{...}).
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": self.required,
                },
            },
        }

    def to_provider_format(self, provider: ProviderFormat) -> dict[str, Any]:
        if provider is ProviderFormat.OPENAI:
            return self._to_openai_format()
        if provider is ProviderFormat.OPENAI_HARMONY:
            return self._to_openai_harmony_format()
        raise ValueError(f"Unsupported provider format: {provider}")


# ============================================================================
# Tool schemas (data)
# ============================================================================

SEARCH_CORPUS_SCHEMA = ToolSchema(
    name="search_corpus",
    description=(
        "Searches the corpus for relevant documents based on the input query. "
        "Returns a section of the document that is relevant to the query."
    ),
    parameters={
        "query": {
            "type": "string",
            "description": "The search query to find relevant documents in the corpus.",
        }
    },
    required=["query"],
)

READ_DOCUMENT_SCHEMA = ToolSchema(
    name="read_document",
    description="Reads the content of a document based on its ID.",
    parameters={
        "doc_id": {
            "type": "string",
            "description": "The unique identifier of the document to read.",
        }
    },
    required=["doc_id"],
)

GREP_CORPUS_SCHEMA = ToolSchema(
    name="grep_corpus",
    description="Performs a regex search on the corpus to find documents matching the query.",
    parameters={
        "pattern": {
            "type": "string",
            "description": "The regex query to search for in the corpus.",
        }
    },
    required=["pattern"],
)

MULTI_TOOL_USE_SCHEMA = ToolSchema(
    name="multi_tool_use",
    description="Allows the agent to use multiple tools in parallel to gather information.",
    parameters={
        "tool_calls": {
            "type": "array",
            "description": "List of tool calls to execute in parallel.",
            "items": {
                "type": "object",
                "properties": {
                    "tool_name": {"type": "string"},
                    "parameters": {"type": "object"},
                },
                "required": ["tool_name", "parameters"],
            },
        }
    },
    required=["tool_calls"],
)

PRUNE_CHUNKS_SCHEMA = ToolSchema(
    name="prune_chunks",
    description=(
        "Prunes the chunks by id that are not relevant to the main question from the "
        "history of the conversation."
    ),
    parameters={"chunk_ids": {"type": "array", "items": {"type": "string"}}},
    required=["chunk_ids"],
)


# ============================================================================
# Base classes
# ============================================================================


class ToolCallMetadata(BaseModel):
    """Metadata returned alongside a tool call's text output."""


class Tool(ABC, BaseModel):
    """Base class for executable tools."""

    tool_schema: ToolSchema

    @abstractmethod
    def __call__(
        self,
        params: dict[Any, Any],
        overrides: dict[Any, Any] | None = None,
    ) -> tuple[str, ToolCallMetadata | None]:
        """Execute the tool against ``params`` (possibly overridden by the caller)."""

    def get_format(self, provider: ProviderFormat) -> dict[str, Any]:
        return self.tool_schema.to_provider_format(provider)

    def __repr__(self) -> str:
        return f"Tool(name={self.tool_schema.name!r})"


class SerializedTool(Tool):
    """Lightweight placeholder used when deserialising trajectories from JSON."""

    def __call__(
        self,
        params: dict[Any, Any],
        overrides: dict[Any, Any] | None = None,
    ) -> tuple[str, ToolCallMetadata | None]:
        raise NotImplementedError("SerializedTool is a placeholder and cannot be executed.")


# ============================================================================
# Concrete tools
# ============================================================================

DOC_TRUNCATION = 51_200_000  # effectively unbounded; keeps the formatting branch sane


class SearchCorpusToolCallMetadata(ToolCallMetadata):
    """IDs returned by a search call (post-rerank, with optional pre-rerank list)."""

    returned_chunk_ids: list[str]
    pre_rerank_chunk_ids: list[str] | None = None


class SearchCorpusTool(Tool):
    """Hybrid (vector + full-text RRF) corpus search backed by Cosmos DB."""

    tool_schema: ToolSchema
    _cosmos_database: DatabaseProxy
    _container: ContainerProxy
    _openai_client: openai.OpenAI
    _openai_ef_name: str
    _embed_query_instruction: str | None
    _reranker: Reranker | None
    _search_limit: int
    _display_limit: int

    def __init__(
        self,
        cosmos_database: DatabaseProxy,
        openai_client: openai.OpenAI,
        cosmos_container_name: str,
        openai_ef_name: str = "text-embedding-3-small",
        embed_query_instruction: str | None = None,
        reranker: Reranker | None = None,
        search_limit: int = 50,
        display_limit: int = 10,
    ) -> None:
        super().__init__(tool_schema=SEARCH_CORPUS_SCHEMA)
        self._cosmos_database = cosmos_database
        self._container = cosmos_database.get_container_client(cosmos_container_name)
        self._openai_client = openai_client
        self._openai_ef_name = openai_ef_name
        self._embed_query_instruction = embed_query_instruction
        self._reranker = reranker
        self._search_limit = search_limit
        self._display_limit = display_limit

    def __call__(
        self,
        params: dict[Any, Any],
        overrides: dict[Any, Any] | None = None,
    ) -> tuple[str, SearchCorpusToolCallMetadata | None]:
        log = logger.bind(tool=self.tool_schema.name)
        if not isinstance(params, dict) or "query" not in params:
            log.error("invalid_params", params_type=type(params).__name__)
            raise ValueError(f"Invalid params type: {type(params)}")

        query = params["query"]
        ignore_ids: list[str] = []
        if overrides is not None and "ignore_ids" in overrides:
            ignore_ids = overrides["ignore_ids"]
        log.info("search_corpus", query=query, ignore_ids=len(ignore_ids))

        terms = _tokenize_for_fts(query)
        if not terms:
            terms = [query.strip() or "_"]
        dense_vec = self._embed_query(query)

        sql_parts = ["SELECT TOP @k c.id, c.text, c.docid, c.chunk_idx FROM c"]
        parameters: list[dict[str, Any]] = [
            {"name": "@k", "value": self._search_limit},
            {"name": "@qVec", "value": dense_vec},
        ]
        if ignore_ids:
            sql_parts.append("WHERE NOT ARRAY_CONTAINS(@ignore, c.id)")
            parameters.append({"name": "@ignore", "value": ignore_ids})
        sql_parts.append(
            "ORDER BY RANK RRF("
            "VectorDistance(c.embedding, @qVec), "
            f"FullTextScore(c.text, {_fts_literal_args(terms)})"
            ")"
        )
        sql = "\n".join(sql_parts)

        rows = _query_with_retry(self._container, sql, parameters)
        ids = [r["id"] for r in rows]
        documents = [r.get("text", "") for r in rows]

        max_tokens_override = (
            overrides.get("max_tokens") if overrides and "max_tokens" in overrides else None
        )

        token_counts: list[int | None] = [None] * len(ids)
        if self._reranker is not None and ids:
            rerank_results = self._reranker(
                query, cast(list[str], documents), max_tokens=max_tokens_override
            )
            ids = [ids[r.original_index] for r in rerank_results]
            documents = [r.document for r in rerank_results]
            token_counts = [r.tokens for r in rerank_results]
            log.info("reranked_results", num_results=len(ids))

        formatted = [
            "\n# DOCUMENT ID: {}{} \n{}".format(
                id_,
                f" ({tokens} tokens)" if tokens is not None else "",
                doc[:DOC_TRUNCATION],
            )
            for id_, doc, tokens in zip(ids, cast(list[str], documents), token_counts, strict=True)
        ][: self._display_limit]

        text = "\n".join(formatted) if ids else "No results found"
        return text, SearchCorpusToolCallMetadata(returned_chunk_ids=ids[: len(formatted)])

    def _embed_query(self, text: str) -> list[float]:
        if self._embed_query_instruction:
            text = f"Instruct: {self._embed_query_instruction}\nQuery: {text}"
        resp = self._openai_client.embeddings.create(
            model=self._openai_ef_name, input=[text], encoding_format="float"
        )
        return resp.data[0].embedding


class GrepCorpusToolCallMetadata(ToolCallMetadata):
    """IDs returned by a grep call."""

    returned_chunk_ids: list[str]


class GrepCorpusTool(Tool):
    """Regex search over the corpus.

    Cosmos's ``RegexMatch`` requires an O(N) scan that blows past serverless
    per-request budgets. We use ``FullTextScore`` (index-backed BM25) on the
    pattern's tokens, then post-filter the top hits with the real regex
    client-side.
    """

    tool_schema: ToolSchema
    _cosmos_database: DatabaseProxy
    _container: ContainerProxy
    _token_counter: Callable[[str], int] | None

    def __init__(
        self,
        cosmos_database: DatabaseProxy,
        cosmos_container_name: str,
        token_counter: Callable[[str], int] | None = None,
    ) -> None:
        super().__init__(tool_schema=GREP_CORPUS_SCHEMA)
        self._cosmos_database = cosmos_database
        self._container = cosmos_database.get_container_client(cosmos_container_name)
        self._token_counter = token_counter

    def __call__(
        self,
        params: dict[Any, Any],
        overrides: dict[Any, Any] | None = None,
    ) -> tuple[str, ToolCallMetadata | None]:
        log = logger.bind(tool=self.tool_schema.name)
        if not isinstance(params, dict) or "pattern" not in params:
            log.error("invalid_params", params_type=type(params).__name__)
            raise ValueError(f"Invalid params type: {type(params)}")

        pattern = params["pattern"]
        log.info("grep_corpus", pattern=pattern)

        terms = _tokenize_for_fts(pattern)
        if not terms:
            return "No results found", GrepCorpusToolCallMetadata(returned_chunk_ids=[])

        sql = (
            "SELECT TOP 50 c.id, c.text, c.docid FROM c "
            "ORDER BY RANK FullTextScore(c.text, " + _fts_literal_args(terms) + ")"
        )
        candidate_rows = _query_with_retry(self._container, sql, [])

        try:
            regex = re.compile(pattern, re.IGNORECASE)
            rows = [r for r in candidate_rows if regex.search(r.get("text", ""))][:5]
        except re.error:
            rows = candidate_rows[:5]

        ids = [r["id"] for r in rows]
        documents = [r.get("text", "") for r in rows]
        token_counts: list[int | None] = (
            [self._token_counter(doc) for doc in documents]
            if self._token_counter is not None
            else [None] * len(documents)
        )

        formatted = [
            "\n# DOCUMENT ID: {}{} \n{}".format(
                id_,
                f" ({tokens} tokens)" if tokens is not None else "",
                doc[:DOC_TRUNCATION],
            )
            for id_, doc, tokens in zip(ids, documents, token_counts, strict=True)
        ]
        text = "\n".join(formatted) if ids else "No results found"
        return text, GrepCorpusToolCallMetadata(returned_chunk_ids=ids)


class ReadDocumentTool(Tool):
    """Reads all chunks for a document (partitioned by docid)."""

    tool_schema: ToolSchema
    _cosmos_database: DatabaseProxy
    _container: ContainerProxy
    _reranker: Reranker | None
    _token_counter: Callable[[str], int] | None
    _max_tokens: int | None

    def __init__(
        self,
        cosmos_database: DatabaseProxy,
        cosmos_container_name: str,
        reranker: Reranker | None = None,
        token_counter: Callable[[str], int] | None = None,
        max_tokens: int | None = None,
    ) -> None:
        if max_tokens is not None and token_counter is None:
            raise ValueError("token_counter is required when max_tokens is specified")
        super().__init__(tool_schema=READ_DOCUMENT_SCHEMA)
        self._cosmos_database = cosmos_database
        self._container = cosmos_database.get_container_client(cosmos_container_name)
        self._reranker = reranker
        self._token_counter = token_counter
        self._max_tokens = max_tokens

    def __call__(
        self,
        params: dict[Any, Any],
        overrides: dict[Any, Any] | None = None,
    ) -> tuple[str, ToolCallMetadata | None]:
        log = logger.bind(tool=self.tool_schema.name)
        if not isinstance(params, dict) or ("doc_id" not in params and "id" not in params):
            log.error("invalid_params", params_type=type(params).__name__)
            raise ValueError(f"Invalid params type: {type(params)}")

        doc_id = params.get("doc_id") or params.get("id")
        log.info("read_document", doc_id=doc_id)
        # Ingest format is "<docid>__<chunk_idx>"; tolerate either form.
        if isinstance(doc_id, str) and "__" in doc_id:
            doc_id = doc_id.split("__", 1)[0]

        sql = (
            "SELECT TOP 300 c.id, c.text, c.chunk_idx, c.docid FROM c "
            "WHERE c.docid = @doc_id"
        )
        parameters = [{"name": "@doc_id", "value": doc_id}]
        rows = _query_with_retry(self._container, sql, parameters, partition_key=doc_id)
        rows.sort(key=lambda r: r.get("chunk_idx", 0))
        documents = [r.get("text", "") for r in rows]
        assembled = "".join(cast(list[str], documents))

        query = overrides.get("query") if overrides else None
        max_tokens = (
            overrides.get("max_tokens") if overrides and "max_tokens" in overrides else None
        ) or self._max_tokens

        if self._reranker is not None and query is not None and max_tokens is not None:
            rerank_results = self._reranker(query, cast(list[str], documents), max_tokens=max_tokens)
            kept_indices = {r.original_index for r in rerank_results}
            kept_docs = [documents[i] for i in range(len(documents)) if i in kept_indices]
            assembled = "".join(kept_docs)
            log.info("reranked_and_filtered", original=len(documents), kept=len(kept_docs))
        elif self._token_counter is not None and max_tokens is not None:
            total_tokens = self._token_counter(assembled)
            if total_tokens > max_tokens:
                truncated: list[str] = []
                running = 0
                for doc in documents:
                    n = self._token_counter(doc)
                    if running + n > max_tokens:
                        break
                    truncated.append(doc)
                    running += n
                assembled = "".join(truncated)
                log.info("truncated_by_tokens", original=len(documents), kept=len(truncated))

        if self._token_counter is not None:
            token_count = self._token_counter(assembled)
            return f"# Document ({token_count} tokens)\n{assembled}", None
        return assembled, None


class PruneChunksTool(Tool):
    """No-op tool used to record which chunks should be elided in subsequent turns."""

    tool_schema: ToolSchema

    def __init__(self) -> None:
        super().__init__(tool_schema=PRUNE_CHUNKS_SCHEMA)

    def __call__(
        self,
        params: dict[Any, Any],
        overrides: dict[Any, Any] | None = None,
    ) -> tuple[str, ToolCallMetadata | None]:
        log = logger.bind(tool=self.tool_schema.name)
        if not isinstance(params, dict) or "chunk_ids" not in params:
            log.error("invalid_params", params_type=type(params).__name__)
            raise ValueError(f"Invalid params type: {type(params)}")
        log.info("prune_chunks", chunk_ids=len(params["chunk_ids"]))
        return "Pruned", None


_ToolSetT: TypeAlias = "ToolSet"


class MultiToolUseTool(Tool):
    """Wraps a parallel tool-call bundle for models without native parallel calls.

    The trained Harness-1 model emits a single ``functions.multi_tool_use``
    call with a list of inner ``{tool_name, parameters}`` entries; the inner
    tools are dispatched serially against the bound :class:`ToolSet`.
    """

    tool_schema: ToolSchema
    toolset: _ToolSetT

    def __init__(self, toolset: ToolSet) -> None:
        super().__init__(tool_schema=MULTI_TOOL_USE_SCHEMA, toolset=toolset)

    def __call__(
        self,
        params: dict[Any, Any],
        overrides: dict[Any, Any] | None = None,
    ) -> tuple[str, ToolCallMetadata | None]:
        results: list[str] = []
        for tool_call in params["tool_calls"]:
            tool = self.toolset.get_tool(tool_call["tool_name"])
            if tool is None:
                raise ValueError(f"Tool {tool_call['tool_name']} not found in toolset")
            output, _ = tool(tool_call["parameters"])
            results.append(output)
        return json.dumps(results), None


class UserTextTool(Tool):
    """Sentinel tool representing assistant text in a trajectory."""

    tool_schema: ToolSchema

    def __init__(self) -> None:
        super().__init__(
            tool_schema=ToolSchema(
                name="user_text",
                description="Produces text for the user.",
                parameters={},
                required=[],
            )
        )

    def __call__(
        self,
        params: dict[Any, Any],
        overrides: dict[Any, Any] | None = None,
    ) -> tuple[str, ToolCallMetadata | None]:
        raise ValueError("UserTextTool should not be called directly")


# ============================================================================
# Stub tools used by the ultra_core working-memory env
# ----------------------------------------------------------------------------
# These tools are *registered* on the toolset so the model sees their
# schemas, but their actual behaviour is dispatched by
# :class:`cosmos_retriever.env.UltraSearchEnv` (which has access to the
# cross-turn :class:`WorkingMemory`).
# ============================================================================


def _stub_tool(name_for_error: str):
    def _impl(self, params, overrides=None):
        raise NotImplementedError(
            f"{name_for_error} is dispatched by UltraSearchEnv, not the tool itself"
        )
    return _impl


class FanOutSearchTool(Tool):
    """Stub: dispatched by env. Runs N parallel ``search_corpus`` calls."""

    tool_schema: ToolSchema

    def __init__(self) -> None:
        from cosmos_retriever.ultra_core import FAN_OUT_SEARCH_SCHEMA
        super().__init__(tool_schema=FAN_OUT_SEARCH_SCHEMA)

    __call__ = _stub_tool("fan_out_search")


class CurateTool(Tool):
    """Stub: dispatched by env. Updates :class:`WorkingMemory.curated_ids`."""

    tool_schema: ToolSchema

    def __init__(self) -> None:
        from cosmos_retriever.ultra_core import CURATE_SCHEMA
        super().__init__(tool_schema=CURATE_SCHEMA)

    __call__ = _stub_tool("curate")


class EndSearchTool(Tool):
    """Sentinel tool — when called, the env terminates the episode."""

    tool_schema: ToolSchema

    def __init__(self) -> None:
        from cosmos_retriever.ultra_core import END_SEARCH_SCHEMA
        super().__init__(tool_schema=END_SEARCH_SCHEMA)

    def __call__(self, params, overrides=None):
        return "Search concluded.", None


class ReviewDocsTool(Tool):
    """Stub: dispatched by env. Returns full text of previously-found docs."""

    tool_schema: ToolSchema

    def __init__(self) -> None:
        from cosmos_retriever.ultra_core import REVIEW_DOCS_SCHEMA
        super().__init__(tool_schema=REVIEW_DOCS_SCHEMA)

    __call__ = _stub_tool("review_docs")


class VerifyTool(Tool):
    """Stub: dispatched by env (v8d). Verifies a claim against doc IDs."""

    tool_schema: ToolSchema

    def __init__(self) -> None:
        from cosmos_retriever.ultra_core import VERIFY_SCHEMA
        super().__init__(tool_schema=VERIFY_SCHEMA)

    __call__ = _stub_tool("verify")


# ============================================================================
# ToolSet
# ============================================================================


class ToolSet(BaseModel):
    """A composable collection of named :class:`Tool` instances."""

    tools: dict[str, Tool] = Field(default_factory=dict)
    name: str | None = None

    def add_tool(self, tool: Tool) -> None:
        if tool.tool_schema.name in self.tools:
            raise ValueError(f"Tool with name {tool.tool_schema.name} already exists")
        self.tools[tool.tool_schema.name] = tool

    def remove_tool(self, name: str) -> None:
        self.tools.pop(name, None)

    def get_tool(self, name: str) -> Tool | None:
        return self.tools.get(name)

    def get_formats(self, provider: ProviderFormat) -> list[dict[str, Any]]:
        return [tool.get_format(provider) for tool in self.tools.values()]

    def __repr__(self) -> str:
        names = ", ".join(sorted(self.tools.keys()))
        suffix = f" ({self.name})" if self.name else ""
        return f"ToolSet{suffix}[{len(self.tools)} tools: {names}]"

    @classmethod
    def build(
        cls,
        *,
        cosmos_database: DatabaseProxy,
        cosmos_container_name: str,
        openai_client: openai.OpenAI,
        openai_embedding_model: str = "text-embedding-3-small",
        embed_query_instruction: str | None = None,
        reranker: Reranker | None = None,
        token_counter: Callable[[str], int] | None = None,
        max_tokens: int | None = None,
        search_limit: int = 50,
        search_display_limit: int = 10,
        include_ultra_tools: bool = False,
        name: str | None = None,
    ) -> ToolSet:
        """Build a fully-wired retrieval :class:`ToolSet`.

        Returns a :class:`ToolSet` containing :class:`SearchCorpusTool`,
        :class:`GrepCorpusTool`, :class:`ReadDocumentTool`, and
        :class:`PruneChunksTool` — exactly the four tools the trained
        Harness-1 model expects to see on its developer message.

        When ``include_ultra_tools`` is true, also registers the stub
        ``fan_out_search``, ``curate``, ``review_docs``, and
        ``end_search`` tools used by
        :class:`cosmos_retriever.env.UltraSearchEnv`.
        """

        toolset = cls(name=name)
        toolset.add_tool(
            SearchCorpusTool(
                cosmos_database=cosmos_database,
                openai_client=openai_client,
                cosmos_container_name=cosmos_container_name,
                openai_ef_name=openai_embedding_model,
                embed_query_instruction=embed_query_instruction,
                reranker=reranker,
                search_limit=search_limit,
                display_limit=search_display_limit,
            )
        )
        toolset.add_tool(
            GrepCorpusTool(
                cosmos_database=cosmos_database,
                cosmos_container_name=cosmos_container_name,
                token_counter=token_counter,
            )
        )
        toolset.add_tool(
            ReadDocumentTool(
                cosmos_database=cosmos_database,
                cosmos_container_name=cosmos_container_name,
                reranker=reranker,
                token_counter=token_counter,
                max_tokens=max_tokens,
            )
        )
        toolset.add_tool(PruneChunksTool())
        if include_ultra_tools:
            toolset.add_tool(FanOutSearchTool())
            toolset.add_tool(CurateTool())
            toolset.add_tool(ReviewDocsTool())
            toolset.add_tool(EndSearchTool())
        return toolset


# Re-export the names trajectory.py imports
__all__ = [
    "COSMOS_QUERY_MAX_CONCURRENCY",
    "DOC_TRUNCATION",
    "GREP_CORPUS_SCHEMA",
    "GrepCorpusTool",
    "GrepCorpusToolCallMetadata",
    "MULTI_TOOL_USE_SCHEMA",
    "MultiToolUseTool",
    "PRUNE_CHUNKS_SCHEMA",
    "PruneChunksTool",
    "READ_DOCUMENT_SCHEMA",
    "ReadDocumentTool",
    "SEARCH_CORPUS_SCHEMA",
    "SearchCorpusTool",
    "SearchCorpusToolCallMetadata",
    "SerializedTool",
    "Tool",
    "ToolCallMetadata",
    "ToolSchema",
    "ToolSet",
    "UserTextTool",
]
