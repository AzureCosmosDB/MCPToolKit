"""High-level facade: ``CosmosRetriever().search(query)`` returns docs.

Wraps the agent state machine, tool-set wiring, and Harmony token counter into
a single synchronous object that the CLI (and any in-process caller) drives
directly. The agent loop is synchronous end-to-end (Cosmos SDK + httpx +
tiktoken are all sync); there is no async surface here on purpose so that
subprocess-based callers (the MCP Toolkit ``agentic_search`` tool) get clean,
predictable behaviour.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field

import structlog
import tiktoken
from openai_harmony import (
    HarmonyEncoding,
    HarmonyEncodingName,
    RenderConversationConfig,
    load_harmony_encoding,
)

from cosmos_retriever.config import CorpusConfig, RetrieverSettings, get_settings
from cosmos_retriever.rerank import BasetenReranker, Reranker, VLLMReranker
from cosmos_retriever.tools import (
    SearchCorpusTool,
    SearchCorpusToolCallMetadata,
    ToolSet,
)
from cosmos_retriever.trajectory import (
    Action,
    Observation,
    Trajectory,
)

logger = structlog.get_logger("cosmos_retriever.retriever")


_DOCUMENT_BLOCK_PATTERN = re.compile(
    r"<Document\s+id=[\"']?(?P<id>[^\"'\s>]+)[\"']?\s*>\s*"
    r"(?:<Justification>\s*(?P<justification>.*?)\s*</Justification>\s*)?"
    r"</Document>",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class RetrievedDocument:
    """A single curated document returned by the agent."""

    id: str
    text: str = ""  # populated by `_hydrate_document_text` when available
    justification: str | None = None
    rank: int | None = None


@dataclass
class RetrievalResult:
    """Output of :py:meth:`CosmosRetriever.search`."""

    query: str
    documents: list[RetrievedDocument]
    num_turns: int
    final_text: str = ""
    pool_doc_ids: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    metadata: dict[str, str | int | float] = field(default_factory=dict)
    # Per-query trajectory: the agent's step-by-step actions (search queries
    # issued, per-turn tool calls, programmatic turn summaries, and the final
    # importance tags assigned during curation). Populated by the harmony_vllm
    # backend; empty for backends that don't expose turn-level state.
    trajectory: dict[str, object] = field(default_factory=dict)


class CosmosRetriever:
    """Drive the trained Harness-1 agent against a Cosmos DB corpus.

    Construct once per process; reuse for many ``search`` calls. The internal
    Cosmos and OpenAI clients are kept open for the lifetime of the instance.

    Args:
        settings: Loaded :class:`RetrieverSettings`. Falls back to
            :func:`get_settings` (i.e. env vars + ``.env``).
        corpus_name: Optional container name to look up in the
            :py:attr:`RetrieverSettings.corpus_registry`. When omitted,
            the default-corpus env vars (``ACCOUNT_URI`` / ``COSMOS_DATABASE`` /
            ``COSMOS_CORPUS_CONTAINER`` / ``AZURE_OPENAI_*``) are used.
        reranker: Optional pre-built reranker. When omitted, one is built
            from settings (Baseten if configured, then local vLLM, else None).
    """

    def __init__(
        self,
        settings: RetrieverSettings | None = None,
        *,
        corpus_name: str | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.corpus: CorpusConfig = self.settings.resolve_corpus(corpus_name)

        self._enc: HarmonyEncoding = load_harmony_encoding(HarmonyEncodingName.HARMONY_GPT_OSS)
        self._tiktoken = tiktoken.get_encoding("o200k_harmony")
        self._reranker = reranker or self._build_default_reranker()

        cosmos_db = self.settings.build_cosmos_database(self.corpus)
        openai_client = self.settings.build_openai_client(self.corpus)
        self._use_chat = self.settings.use_chat_backend
        self._use_responses = self.settings.use_responses_backend
        self._use_generic = self.settings.use_generic_llm_backend

        self.toolset: ToolSet = ToolSet.build(
            cosmos_database=cosmos_db,
            cosmos_container_name=self.corpus.container,
            openai_client=openai_client,
            openai_embedding_model=self.corpus.embed_model,
            embed_query_instruction=self.corpus.embed_query_instruction,
            reranker=self._reranker,
            token_counter=self._text_token_counter,
            search_display_limit=self.settings.cosmos_retriever_search_display_limit,
            # The ultra stub tools are dispatched by the Harmony env; a generic
            # chat/responses model must not see (and try to call) them.
            include_ultra_tools=not self._use_generic,
        )

        # Inference backend: either the fine-tuned Harness-1 over Harmony tokens,
        # or any OpenAI-compatible chat/responses model via function-calling.
        self.inference_model = None
        self._chat_client = None
        self._chat_model: str | None = None
        if self._use_generic:
            self._chat_client = self.settings.build_chat_client()
            self._chat_model = self.settings.chat_model
        else:
            from cosmos_retriever.inference.vllm import (  # noqa: PLC0415 — heavy, harmony-only
                VLLMHarmonyInferenceModel,
            )

            self.inference_model = VLLMHarmonyInferenceModel(
                base_url=self.settings.vllm_base_url,
                model_name=self.settings.vllm_model_name,
                timeout_s=self.settings.vllm_timeout_s,
            )

        logger.info(
            "cosmos_retriever_initialized",
            inference_backend=self.settings.inference_backend,
            vllm_base_url=None if self._use_generic else self.settings.vllm_base_url,
            vllm_model_name=None if self._use_generic else self.settings.vllm_model_name,
            chat_base_url=self.settings.chat_base_url if self._use_generic else None,
            chat_model=self._chat_model if self._use_generic else None,
            cosmos_account=self.corpus.account_uri,
            cosmos_db=self.corpus.database,
            cosmos_container=self.corpus.container,
            embed_base_url=self.corpus.embed_base_url,
            embed_model=self.corpus.embed_model,
            embed_query_instruction=self.corpus.embed_query_instruction,
            reranker=type(self._reranker).__name__ if self._reranker is not None else None,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def search(
        self,
        query: str,
        *,
        max_documents: int = 20,
        max_turns: int | None = None,
        threshold_budget: int | None = None,
        token_budget: int | None = None,
    ) -> RetrievalResult:
        """Run the multi-turn search agent and return its curated documents.

        Args:
            query: Natural-language question.
            max_documents: Cap on the number of documents to ask the model
                to surface (rendered into the system prompt).
            max_turns: Override the default ``COSMOS_RETRIEVER_MAX_TURNS``.
            threshold_budget / token_budget: Override the default token
                budgets for this single call.

        Returns:
            A :class:`RetrievalResult` containing the ranked documents, the
            number of turns the agent took, and the model's final-channel
            text (used to extract document IDs/justifications).
        """

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
        """Drive the upstream ``SlidingWindowSearchEnv`` for one query.

        Mirrors ``inference/vllm_policy.py:run_single_episode`` from the
        upstream harness-1 repo so that recall on BrowseComp+ matches the
        published Harness-1 numbers (the env owns the ``WorkingMemory`` /
        ``curate`` / ``fan_out_search`` machinery the trained model relies on).
        """

        if self._use_chat:
            return self._search_chat(query, max_documents)
        if self._use_responses:
            return self._search_responses(query, max_documents)

        from cosmos_retriever.env_rl import (  # noqa: PLC0415 — heavy, harmony-only
            SlidingWindowSearchEnv,
        )
        from cosmos_retriever.inference.vllm_policy import (  # noqa: PLC0415
            VllmTokenCompleter,
            run_single_episode,
        )

        search_tool = self.toolset.get_tool("search_corpus")
        if not isinstance(search_tool, SearchCorpusTool):
            raise RuntimeError("toolset is missing a search_corpus tool")

        env = SlidingWindowSearchEnv(
            toolset=self.toolset,
            search_tool=search_tool,
            query_id="adhoc",
            query_text=query,
            dataset_name="web",  # inference mode: only used to key the rerank instruction
            text_token_counter=self._text_token_counter,
            max_turns=max_turns,
        )

        policy = VllmTokenCompleter(
            base_url=self.settings.vllm_base_url,
            model=self.settings.vllm_model_name,
            max_tokens=2048,
            temperature=1.0,
            top_p=0.9,
            timeout=int(self.settings.vllm_timeout_s),
        )

        start = time.perf_counter()
        episode = asyncio.run(run_single_episode(env=env, policy=policy))
        elapsed = time.perf_counter() - start

        documents: list[RetrievedDocument] = []
        for rank, chunk_id in enumerate(env.wm.curated_ids[:max_documents]):
            entry = env.wm.doc_store.get(chunk_id) or env.wm.doc_store.get(
                chunk_id.split("_")[0]
            )
            text = (entry or {}).get("full_text") or (entry or {}).get("snippet") or ""
            documents.append(
                RetrievedDocument(
                    id=chunk_id,
                    text=text,
                    justification=env.wm.curated_notes.get(chunk_id) if hasattr(env.wm, "curated_notes") else None,
                    rank=rank,
                )
            )

        trajectory = {
            "search_history": list(getattr(env.wm, "search_history", []) or []),
            "turn_summaries": list(getattr(env, "_result_summaries", []) or []),
            "curated_importance": dict(getattr(env.wm, "curated_importance", {}) or {}),
            "turn_tools": [
                [
                    getattr(getattr(t, "tool_schema", None), "name", type(t).__name__)
                    for t in getattr(action, "tools", [])
                ]
                for action in getattr(env, "_all_actions", []) or []
            ],
        }

        result = RetrievalResult(
            query=query,
            documents=documents,
            num_turns=int(episode.get("turns", 0)),
            final_text="",
            elapsed_s=round(elapsed, 3),
            pool_doc_ids=sorted({cid.split("__")[0] for cid in env.wm.pool_ids}),
            trajectory=trajectory,
            metadata={
                "n_pool": len(env.wm.pool_ids),
                "n_curated": len(env.wm.curated_ids),
                "total_curate_calls": episode.get("total_curate_calls", 0),
                "tool_types_used": ",".join(sorted(set(episode.get("tool_types_used", [])))),
            },
        )
        logger.info(
            "search_complete",
            query=query[:200],
            num_documents=len(result.documents),
            num_turns=result.num_turns,
            n_pool=len(env.wm.pool_ids),
            n_curated=len(env.wm.curated_ids),
            elapsed_s=result.elapsed_s,
        )
        return result

    def _search_chat(self, query: str, max_documents: int) -> RetrievalResult:
        """Drive a generic OpenAI-compatible chat model via function-calling.

        Used when ``INFERENCE_BACKEND=openai_chat``. The chat agent talks to
        the same Cosmos :class:`ToolSet`, so retrieval quality depends on the
        chosen model's tool-use ability rather than the fine-tuned Harness-1
        checkpoint.
        """

        from cosmos_retriever.inference.openai_chat import (  # noqa: PLC0415
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
        """Drive a generic OpenAI **/responses** model (e.g. gpt-5.x reasoning).

        Used when ``INFERENCE_BACKEND=openai_responses``. Same Cosmos tools as
        the chat backend, but routed through the responses API which reasoning
        models require.
        """

        from cosmos_retriever.inference.openai_chat import (  # noqa: PLC0415
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

    def _trajectory_token_counter(self, trajectory: Trajectory) -> int:
        return len(
            self._enc.render_conversation(
                trajectory.to_openai_harmony_format(),
                config=RenderConversationConfig(auto_drop_analysis=False),
            )
        )

    @staticmethod
    def _extract_documents(
        trajectory: Trajectory,
    ) -> tuple[list[RetrievedDocument], str]:
        """Pull ranked document IDs + justifications out of the model's final turn."""

        # Find the last Action with a UserText final turn.
        final_text = ""
        for entry in reversed(trajectory.actions_and_observations):
            if not isinstance(entry, Action):
                continue
            for tool, params, _source in zip(
                entry.tools, entry.params, entry.sources, strict=True
            ):
                if tool.tool_schema.name == "user_text":
                    final_text = params.get("text", "") or ""
                    break
            if final_text:
                break

        documents: list[RetrievedDocument] = []
        seen: set[str] = set()
        for rank, match in enumerate(_DOCUMENT_BLOCK_PATTERN.finditer(final_text)):
            doc_id = match.group("id")
            if doc_id in seen:
                continue
            seen.add(doc_id)
            justification = match.group("justification")
            documents.append(
                RetrievedDocument(
                    id=doc_id,
                    justification=justification.strip() if justification else None,
                    rank=rank,
                )
            )
        return documents, final_text

    @staticmethod
    def _hydrate_document_text(
        trajectory: Trajectory,
        documents: list[RetrievedDocument],
    ) -> None:
        """Best-effort: copy the first chunk-text we saw for each document into the result.

        We walk every Search/Grep observation's metadata to find the
        ``returned_chunk_ids`` and pull the first matching ``# DOCUMENT ID:
        ...`` block out of the observation text. This avoids a second Cosmos
        round-trip and keeps the response self-contained.
        """

        if not documents:
            return

        wanted: dict[str, RetrievedDocument] = {d.id: d for d in documents}
        from cosmos_retriever.tasks import DOC_ID_PATTERN  # noqa: PLC0415 — internal helper

        for entry in trajectory.actions_and_observations:
            if not isinstance(entry, Observation):
                continue
            for obs_text, metadata in zip(entry.observations, entry.tool_metadata, strict=True):
                if not isinstance(metadata, SearchCorpusToolCallMetadata):
                    continue
                if not any(cid in wanted for cid in metadata.returned_chunk_ids):
                    continue
                # Walk the formatted text to extract per-doc text.
                matches = list(DOC_ID_PATTERN.finditer(obs_text))
                for idx, match in enumerate(matches):
                    chunk_id = match.group("chunk_id")
                    target_id = chunk_id.split("_")[0] if "_" in chunk_id else chunk_id
                    target = wanted.get(target_id) or wanted.get(chunk_id)
                    if target is None or target.text:
                        continue
                    start = match.end()
                    end = matches[idx + 1].start() if idx + 1 < len(matches) else len(obs_text)
                    target.text = obs_text[start:end].strip()


__all__ = ["CosmosRetriever", "RetrievalResult", "RetrievedDocument"]
