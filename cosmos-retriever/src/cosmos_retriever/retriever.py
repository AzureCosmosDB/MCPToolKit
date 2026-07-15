
from __future__ import annotations

import time
from dataclasses import dataclass, field

import structlog
import tiktoken

from cosmos_retriever.config import CorpusConfig, RetrieverSettings, get_settings
from cosmos_retriever.rerank import BasetenReranker, Reranker, VLLMReranker
from cosmos_retriever.tools import ToolSet

logger = structlog.get_logger("cosmos_retriever.retriever")


@dataclass
class RetrievedDocument:

    id: str
    text: str = ""
    justification: str | None = None
    rank: int | None = None


@dataclass
class RetrievalResult:

    query: str
    documents: list[RetrievedDocument]
    num_turns: int
    final_text: str = ""
    pool_doc_ids: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    usage: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, str | int | float] = field(default_factory=dict)
    trajectory: dict[str, object] = field(default_factory=dict)


class CosmosRetriever:

    def __init__(
        self,
        settings: RetrieverSettings | None = None,
        *,
        corpus_name: str | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.corpus: CorpusConfig = self.settings.resolve_corpus(corpus_name)

        self._tiktoken = tiktoken.get_encoding("o200k_harmony")
        self._reranker = reranker or self._build_default_reranker()

        cosmos_db = self.settings.build_cosmos_database(self.corpus)
        openai_client = self.settings.build_openai_client(self.corpus)
        self._use_chat = self.settings.use_chat_backend
        self._use_responses = self.settings.use_responses_backend
        self._use_anthropic = self.settings.use_anthropic_backend

        self.toolset: ToolSet = ToolSet.build(
            cosmos_database=cosmos_db,
            cosmos_container_name=self.corpus.container,
            openai_client=openai_client,
            openai_embedding_model=self.corpus.embed_model,
            embed_query_instruction=self.corpus.embed_query_instruction,
            reranker=self._reranker,
            token_counter=self._text_token_counter,
            search_display_limit=self.settings.cosmos_retriever_search_display_limit,
        )

        self._chat_client = (
            self.settings.build_chat_client()
            if self.settings.use_generic_llm_backend
            else None
        )
        self._chat_model: str | None = self.settings.chat_model

        logger.info(
            "cosmos_retriever_initialized",
            inference_backend=self.settings.inference_backend,
            chat_base_url=self.settings.chat_base_url,
            chat_model=self._chat_model,
            cosmos_account=self.corpus.account_uri,
            cosmos_db=self.corpus.database,
            cosmos_container=self.corpus.container,
            embed_base_url=self.corpus.embed_base_url,
            embed_model=self.corpus.embed_model,
            embed_query_instruction=self.corpus.embed_query_instruction,
            reranker=type(self._reranker).__name__ if self._reranker is not None else None,
        )

    def search(
        self,
        query: str,
        *,
        max_documents: int = 20,
        max_turns: int | None = None,
        threshold_budget: int | None = None,
        token_budget: int | None = None,
    ) -> RetrievalResult:

        if not query or not query.strip():
            raise ValueError("query must be a non-empty string")

        return self._search_sync(
            query,
            max_documents,
            max_turns or self.settings.cosmos_retriever_max_turns,
            threshold_budget or self.settings.cosmos_retriever_threshold_budget,
            token_budget or self.settings.cosmos_retriever_token_budget,
        )

    def _search_sync(
        self,
        query: str,
        max_documents: int,
        max_turns: int,
        threshold_budget: int,
        token_budget: int,
    ) -> RetrievalResult:

        if self._use_chat:
            return self._search_chat(query, max_documents)
        if self._use_anthropic:
            return self._search_anthropic(query, max_documents)
        return self._search_responses(query, max_documents)

    def _search_chat(self, query: str, max_documents: int) -> RetrievalResult:

        from cosmos_retriever.inference.agent_loop import (
            run_chat_search,
        )

        if self._chat_client is None or self._chat_model is None:
            raise RuntimeError("chat backend selected but chat client/model not initialised")

        start = time.perf_counter()
        chat_result = run_chat_search(
            toolset=self.toolset,
            client=self._chat_client,
            model=self._chat_model,
            query=query,
            max_documents=max_documents,
            max_turns=self.settings.chat_max_turns,
            temperature=self.settings.chat_temperature,
            max_tokens=self.settings.chat_max_tokens,
        )
        elapsed = time.perf_counter() - start

        documents = [
            RetrievedDocument(id=d.id, text=d.text, justification=d.justification, rank=d.rank)
            for d in chat_result.documents
        ]
        result = RetrievalResult(
            query=query,
            documents=documents,
            num_turns=chat_result.num_turns,
            final_text=chat_result.final_text,
            elapsed_s=round(elapsed, 3),
            usage=chat_result.usage,
            metadata=chat_result.metadata,
        )
        logger.info(
            "search_complete",
            query=query[:200],
            backend="openai_chat",
            num_documents=len(result.documents),
            num_turns=result.num_turns,
            elapsed_s=result.elapsed_s,
        )
        return result

    def _search_responses(self, query: str, max_documents: int) -> RetrievalResult:

        from cosmos_retriever.inference.agent_loop import (
            run_responses_search,
        )

        if self._chat_client is None or self._chat_model is None:
            raise RuntimeError("responses backend selected but chat client/model not initialised")

        start = time.perf_counter()
        chat_result = run_responses_search(
            toolset=self.toolset,
            client=self._chat_client,
            model=self._chat_model,
            query=query,
            max_documents=max_documents,
            max_turns=self.settings.chat_max_turns,
            max_tokens=self.settings.chat_max_tokens,
            reasoning_effort=self.settings.chat_reasoning_effort,
        )
        elapsed = time.perf_counter() - start

        documents = [
            RetrievedDocument(id=d.id, text=d.text, justification=d.justification, rank=d.rank)
            for d in chat_result.documents
        ]
        result = RetrievalResult(
            query=query,
            documents=documents,
            num_turns=chat_result.num_turns,
            final_text=chat_result.final_text,
            elapsed_s=round(elapsed, 3),
            pool_doc_ids=chat_result.pool_doc_ids,
            usage=chat_result.usage,
            trajectory=chat_result.trajectory,
            metadata=chat_result.metadata,
        )
        logger.info(
            "search_complete",
            query=query[:200],
            backend="openai_responses",
            num_documents=len(result.documents),
            num_turns=result.num_turns,
            elapsed_s=result.elapsed_s,
        )
        return result

    def _search_anthropic(self, query: str, max_documents: int) -> RetrievalResult:
        from cosmos_retriever.inference.agent_loop import (
            run_anthropic_search,
        )

        if (
            not self.settings.chat_base_url
            or self.settings.chat_api_key is None
            or self._chat_model is None
        ):
            raise RuntimeError(
                "anthropic backend selected but CHAT_BASE_URL / CHAT_API_KEY / CHAT_MODEL not set"
            )

        start = time.perf_counter()
        chat_result = run_anthropic_search(
            toolset=self.toolset,
            base_url=self.settings.chat_base_url,
            api_key=self.settings.chat_api_key.get_secret_value(),
            model=self._chat_model,
            query=query,
            max_documents=max_documents,
            max_turns=self.settings.chat_max_turns,
            max_tokens=self.settings.chat_max_tokens,
            anthropic_version=self.settings.anthropic_version,
            auth_header=self.settings.anthropic_auth_header,
        )
        elapsed = time.perf_counter() - start

        documents = [
            RetrievedDocument(id=d.id, text=d.text, justification=d.justification, rank=d.rank)
            for d in chat_result.documents
        ]
        result = RetrievalResult(
            query=query,
            documents=documents,
            num_turns=chat_result.num_turns,
            final_text=chat_result.final_text,
            elapsed_s=round(elapsed, 3),
            pool_doc_ids=chat_result.pool_doc_ids,
            usage=chat_result.usage,
            trajectory=chat_result.trajectory,
            metadata=chat_result.metadata,
        )
        logger.info(
            "search_complete",
            query=query[:200],
            backend="anthropic_messages",
            num_documents=len(result.documents),
            num_turns=result.num_turns,
            elapsed_s=result.elapsed_s,
        )
        return result

    def _build_default_reranker(self) -> Reranker | None:
        if self.settings.baseten_api_key and self.settings.baseten_model_url:
            return BasetenReranker(
                client=self.settings.get_baseten_client(),
                token_counter=self._text_token_counter,
            )
        if self.settings.vllm_reranker_url:
            return VLLMReranker(
                base_url=self.settings.vllm_reranker_url,
                token_counter=self._text_token_counter,
            )
        return None

    def _text_token_counter(self, text: str) -> int:
        return len(self._tiktoken.encode(text))


__all__ = ["CosmosRetriever", "RetrievalResult", "RetrievedDocument"]
