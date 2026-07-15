
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, TypeAlias

import openai
import structlog
from azure.cosmos import DatabaseProxy
from pydantic import BaseModel, Field

from cosmos_retriever.rerank import Reranker
from cosmos_retriever.retrieval import (
    CorpusRetriever,
    GrepRequest,
    QueryEmbedder,
    ReadDocumentRequest,
    SearchRequest,
    build_default_retriever,
)
from cosmos_retriever.retrieval.errors import UnknownField, UnsupportedRetrievalCapability
from cosmos_retriever.retrieval.executor import COSMOS_QUERY_MAX_CONCURRENCY
from cosmos_retriever.retrieval.formatting import DOC_TRUNCATION, format_result_blocks
from cosmos_retriever.retrieval.schema import CorpusSchema
from cosmos_retriever.utils import ProviderFormat

logger = structlog.get_logger("cosmos_retriever.tools")




class ToolSchema(BaseModel):

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




class ToolCallMetadata(BaseModel):
    pass


class Tool(ABC, BaseModel):

    tool_schema: ToolSchema

    @abstractmethod
    def __call__(
        self,
        params: dict[Any, Any],
        overrides: dict[Any, Any] | None = None,
    ) -> tuple[str, ToolCallMetadata | None]:
        pass

    def get_format(self, provider: ProviderFormat) -> dict[str, Any]:
        return self.tool_schema.to_provider_format(provider)

    def __repr__(self) -> str:
        return f"Tool(name={self.tool_schema.name!r})"


class SerializedTool(Tool):

    def __call__(
        self,
        params: dict[Any, Any],
        overrides: dict[Any, Any] | None = None,
    ) -> tuple[str, ToolCallMetadata | None]:
        raise NotImplementedError("SerializedTool is a placeholder and cannot be executed.")




def _search_schema_for(schema: CorpusSchema) -> ToolSchema:

    text_names = list(schema.text_field_map())
    vector_names = list(schema.vector_field_map())
    params: dict[str, Any] = {
        "query": {
            "type": "string",
            "description": "The search query to find relevant documents in the corpus.",
        }
    }
    if len(text_names) > 1:
        params["fields"] = {
            "type": "array",
            "items": {"type": "string", "enum": text_names},
            "description": (
                "Optional. Text field(s) to keyword-match against "
                f"(available: {text_names}). Defaults to the primary text field."
            ),
        }
    if len(vector_names) > 1:
        params["vector_field"] = {
            "type": "string",
            "enum": vector_names,
            "description": (
                "Optional. Vector field for semantic similarity "
                f"(available: {vector_names}). Defaults to the first vector field."
            ),
        }
    if text_names and vector_names:
        params["mode"] = {
            "type": "string",
            "enum": ["auto", "hybrid", "vector", "text"],
            "description": (
                "Optional retrieval method: 'hybrid' (semantic + keyword), "
                "'vector' (semantic only), 'text' (keyword only), or 'auto' (default)."
            ),
        }
    desc = (
        "Searches the corpus for relevant documents based on the input query. "
        "Returns a section of the document that is relevant to the query.\n\n"
        "Queryable schema:\n" + schema.agent_field_summary()
    )
    return ToolSchema(
        name="search_corpus", description=desc, parameters=params, required=["query"]
    )


def _grep_schema_for(schema: CorpusSchema) -> ToolSchema:

    text_names = list(schema.text_field_map())
    params: dict[str, Any] = {
        "pattern": {
            "type": "string",
            "description": "The regex query to search for in the corpus.",
        }
    }
    if len(text_names) > 1:
        params["field"] = {
            "type": "string",
            "enum": text_names,
            "description": (
                "Optional. Text field to search "
                f"(available: {text_names}). Defaults to the primary text field."
            ),
        }
    desc = (
        "Performs a regex search on the corpus to find documents matching the query.\n\n"
        "Queryable text fields: " + ", ".join(f"'{n}'" for n in text_names)
    )
    return ToolSchema(
        name="grep_corpus", description=desc, parameters=params, required=["pattern"]
    )


class SearchCorpusToolCallMetadata(ToolCallMetadata):

    returned_chunk_ids: list[str]
    pre_rerank_chunk_ids: list[str] | None = None


class SearchCorpusTool(Tool):

    tool_schema: ToolSchema
    _retriever: CorpusRetriever
    _reranker: Reranker | None
    _search_limit: int
    _display_limit: int

    def __init__(
        self,
        retriever: CorpusRetriever,
        reranker: Reranker | None = None,
        search_limit: int = 50,
        display_limit: int = 10,
    ) -> None:
        super().__init__(tool_schema=_search_schema_for(retriever.schema))
        self._retriever = retriever
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

        fields = params.get("fields")
        if isinstance(fields, str):
            fields = [fields]
        vector_field = params.get("vector_field")
        mode = params.get("mode") or "auto"
        if mode not in ("auto", "hybrid", "vector", "text"):
            mode = "auto"
        log.info(
            "search_corpus",
            query=query,
            ignore_ids=len(ignore_ids),
            fields=fields,
            vector_field=vector_field,
            mode=mode,
        )

        request = SearchRequest(
            query=query,
            limit=self._search_limit,
            ignored_item_ids=ignore_ids,
            text_fields=fields,
            vector_field=vector_field,
            mode=mode,
        )
        try:
            items = self._retriever.search(request)
        except (UnknownField, UnsupportedRetrievalCapability) as exc:
            log.warning("search_field_error", error=str(exc))
            return (
                f"Search field/mode error: {exc}",
                SearchCorpusToolCallMetadata(returned_chunk_ids=[]),
            )
        ids = [it.item_id for it in items]
        documents = [it.text for it in items]

        max_tokens_override = (
            overrides.get("max_tokens") if overrides and "max_tokens" in overrides else None
        )

        token_counts: list[int | None] = [None] * len(ids)
        if self._reranker is not None and ids:
            rerank_results = self._reranker(query, documents, max_tokens=max_tokens_override)
            ids = [ids[r.original_index] for r in rerank_results]
            documents = [r.document for r in rerank_results]
            token_counts = [r.tokens for r in rerank_results]
            log.info("reranked_results", num_results=len(ids))

        triples = list(zip(ids, documents, token_counts, strict=True))[: self._display_limit]
        text = format_result_blocks(triples)
        returned = [t[0] for t in triples]
        return text, SearchCorpusToolCallMetadata(returned_chunk_ids=returned)


class GrepCorpusToolCallMetadata(ToolCallMetadata):

    returned_chunk_ids: list[str]


class GrepCorpusTool(Tool):

    tool_schema: ToolSchema
    _retriever: CorpusRetriever
    _token_counter: Callable[[str], int] | None

    def __init__(
        self,
        retriever: CorpusRetriever,
        token_counter: Callable[[str], int] | None = None,
    ) -> None:
        super().__init__(tool_schema=_grep_schema_for(retriever.schema))
        self._retriever = retriever
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
        field = params.get("field")
        log.info("grep_corpus", pattern=pattern, field=field)

        try:
            candidates = self._retriever.grep_candidates(
                GrepRequest(
                    pattern=pattern, candidate_limit=50, result_limit=5, text_field=field
                )
            )
        except (UnknownField, UnsupportedRetrievalCapability) as exc:
            log.warning("grep_field_error", error=str(exc))
            return (
                f"Grep field error: {exc}",
                GrepCorpusToolCallMetadata(returned_chunk_ids=[]),
            )
        if not candidates:
            return "No results found", GrepCorpusToolCallMetadata(returned_chunk_ids=[])

        try:
            regex = re.compile(pattern, re.IGNORECASE)
            matched = [it for it in candidates if regex.search(it.text)][:5]
        except re.error:
            matched = candidates[:5]

        ids = [it.item_id for it in matched]
        documents = [it.text for it in matched]
        token_counts: list[int | None] = (
            [self._token_counter(doc) for doc in documents]
            if self._token_counter is not None
            else [None] * len(documents)
        )

        triples = list(zip(ids, documents, token_counts, strict=True))
        text = format_result_blocks(triples)
        return text, GrepCorpusToolCallMetadata(returned_chunk_ids=ids)


class ReadDocumentTool(Tool):

    tool_schema: ToolSchema
    _retriever: CorpusRetriever
    _reranker: Reranker | None
    _token_counter: Callable[[str], int] | None
    _max_tokens: int | None

    def __init__(
        self,
        retriever: CorpusRetriever,
        reranker: Reranker | None = None,
        token_counter: Callable[[str], int] | None = None,
        max_tokens: int | None = None,
    ) -> None:
        if max_tokens is not None and token_counter is None:
            raise ValueError("token_counter is required when max_tokens is specified")
        super().__init__(tool_schema=READ_DOCUMENT_SCHEMA)
        self._retriever = retriever
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

        query = overrides.get("query") if overrides else None
        max_tokens = (
            overrides.get("max_tokens") if overrides and "max_tokens" in overrides else None
        ) or self._max_tokens

        document = self._retriever.read_document(
            ReadDocumentRequest(document_id=doc_id, query=query)
        )
        documents = document.chunk_texts
        assembled = document.assembled

        if self._reranker is not None and query is not None and max_tokens is not None:
            rerank_results = self._reranker(query, documents, max_tokens=max_tokens)
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




class ToolSet(BaseModel):

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
        cosmos_database: DatabaseProxy | None = None,
        cosmos_container_name: str | None = None,
        openai_client: openai.OpenAI | None = None,
        openai_embedding_model: str = "text-embedding-3-small",
        embed_query_instruction: str | None = None,
        retriever: CorpusRetriever | None = None,
        reranker: Reranker | None = None,
        token_counter: Callable[[str], int] | None = None,
        max_tokens: int | None = None,
        search_limit: int = 50,
        search_display_limit: int = 10,
        name: str | None = None,
    ) -> ToolSet:

        if retriever is None:
            if cosmos_database is None or cosmos_container_name is None or openai_client is None:
                raise ValueError(
                    "ToolSet.build requires either 'retriever' or "
                    "'cosmos_database' + 'cosmos_container_name' + 'openai_client'"
                )
            container = cosmos_database.get_container_client(cosmos_container_name)
            embedder = QueryEmbedder(
                client=openai_client,
                model=openai_embedding_model,
                query_instruction=embed_query_instruction,
            )
            retriever = build_default_retriever(
                container=container,
                embedder=embedder,
                embedding_model=openai_embedding_model,
            )

        toolset = cls(name=name)
        toolset.add_tool(
            SearchCorpusTool(
                retriever=retriever,
                reranker=reranker,
                search_limit=search_limit,
                display_limit=search_display_limit,
            )
        )
        toolset.add_tool(
            GrepCorpusTool(
                retriever=retriever,
                token_counter=token_counter,
            )
        )
        toolset.add_tool(
            ReadDocumentTool(
                retriever=retriever,
                reranker=reranker,
                token_counter=token_counter,
                max_tokens=max_tokens,
            )
        )
        toolset.add_tool(PruneChunksTool())
        return toolset


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
