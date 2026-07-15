"""Foundry-driven full-harness retrieval agent.

``FoundryHarnessAgent.search`` drives a generic OpenAI-compatible ``/responses``
model (an Azure AI Foundry deployment such as ``gpt-5.x``) through the complete
nine-tool agentic search harness. The model plans with the same tool vocabulary
the fine-tuned Harness-1 model uses; every tool call is executed by the real
:class:`~cosmos_retriever.env_rl.SlidingWindowSearchEnv` dispatch against a live
``WorkingMemory``, and the final result is the curated set the model built with
the ``curate`` tool.

Requirements (env vars, read via :func:`cosmos_retriever.config.get_settings`):

* ``INFERENCE_BACKEND=openai_responses`` — so the underlying
  :class:`~cosmos_retriever.retriever.CosmosRetriever` builds a chat client
  (not the vLLM Harmony model) and never contacts a vLLM server.
* ``CHAT_BASE_URL`` / ``CHAT_MODEL`` / ``CHAT_API_KEY`` — the Foundry deployment.
  Leave ``CHAT_API_VERSION`` unset for a ``/openai/v1`` surface (plain OpenAI
  client); set it for a classic Azure OpenAI resource.
* The usual corpus/embedding vars (``ACCOUNT_URI``, ``COSMOS_*``,
  ``AZURE_OPENAI_EMBED_*``) plus ``VLLM_RERANKER_URL`` if a reranker is used.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import openai
import structlog

from cosmos_retriever.config import RetrieverSettings, get_settings
from cosmos_retriever.env_rl import SlidingWindowSearchEnv
from cosmos_retriever.retriever import (
    CosmosRetriever,
    RetrievalResult,
    RetrievedDocument,
)
from cosmos_retriever.tools import SearchCorpusTool
from cosmos_retriever.ultra_core import get_system_prompt
from cosmos_retriever.utils import ProviderFormat

try:  # tolerant JSON parsing for model-emitted tool arguments
    import json_repair
except Exception:  # pragma: no cover - json_repair is a hard dep of cosmos_retriever
    json_repair = None
import json

logger = structlog.get_logger("foundry_harness.agent")

# Full agentic vocabulary. The env's ``_build_full_toolset`` assembles the same
# set (respecting the ``V8D_VERIFY_TOOL`` flag for ``verify``); we advertise
# whatever it returns so schema and dispatch never drift apart.
_TERMINAL_TOOL = "end_search"

# Result alias so callers can import a domain-named type without caring that it
# is structurally identical to the harmony backend's result.
FoundryHarnessResult = RetrievalResult


def _empty_usage() -> dict[str, int]:
    return {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
        "llm_calls": 0,
    }


def _acc_responses_usage(usage: dict[str, int], resp: Any) -> None:
    """Accumulate ``/responses`` token usage from one API response."""
    u = getattr(resp, "usage", None)
    if u is None:
        return
    usage["prompt_tokens"] += int(getattr(u, "input_tokens", 0) or 0)
    usage["completion_tokens"] += int(getattr(u, "output_tokens", 0) or 0)
    usage["total_tokens"] += int(getattr(u, "total_tokens", 0) or 0)
    details = getattr(u, "output_tokens_details", None)
    if details is not None:
        usage["reasoning_tokens"] += int(getattr(details, "reasoning_tokens", 0) or 0)
    usage["llm_calls"] += 1


def _create_with_retry(
    client: openai.OpenAI, *, max_retries: int = 10, base_delay: float = 4.0, **kwargs: Any
) -> Any:
    """Call ``responses.create`` with exponential backoff on rate limits.

    The Foundry deployment quota is easily shared (e.g. with a concurrent
    benchmark) and small regional deployments throttle hard, so a 429 is
    transient. Backs off up to ``max_retries`` times before re-raising, with
    jitter so parallel workers desynchronize instead of retrying in lockstep.
    """
    delay = base_delay
    for attempt in range(max_retries + 1):
        try:
            return client.responses.create(**kwargs)
        except openai.RateLimitError:
            if attempt >= max_retries:
                raise
            sleep_s = delay + random.uniform(0, delay)
            logger.warning("foundry_rate_limited", attempt=attempt + 1, sleep_s=round(sleep_s, 1))
            time.sleep(sleep_s)
            delay = min(delay * 2, 90.0)


def _parse_tool_arguments(raw: Optional[str]) -> dict:
    """Parse a tool-call ``arguments`` JSON string, tolerating minor breakage."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        if json_repair is None:
            return {}
        try:
            parsed = json_repair.loads(raw)
        except Exception:  # noqa: BLE001 — last-ditch; bad args become {}
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _dispatch_tool(env: SlidingWindowSearchEnv, name: str, params: dict) -> str:
    """Route a single function-call to the env's real tool executors.

    Mirrors :meth:`SlidingWindowSearchEnv._execute_tools` but for JSON args
    instead of Harmony-parsed actions. All state mutations (pool, curated set,
    search history) land in ``env.wm``.
    """
    if name == "fan_out_search":
        output, _meta = env._exec_fan_out_search(params)
        return output
    if name == "search_corpus":
        output, _meta = env._exec_search(params)
        return output
    if name == "grep_corpus":
        output, _meta = env._exec_grep(params)
        return output
    if name == "read_document":
        output, _meta = env._exec_read_doc(params)
        return output
    if name == "curate":
        return env._exec_curate(params)
    if name == "review_docs":
        return env._exec_review_docs(params)
    if name == "verify":
        return env._exec_verify(params)
    if name == _TERMINAL_TOOL:
        return "Search concluded. Your curated set has been submitted."
    if name == "prune_chunks":
        return "Context is managed via working memory. No pruning needed."
    return f"Unknown tool: {name}"


def run_foundry_harness_search(
    *,
    env: SlidingWindowSearchEnv,
    client: openai.OpenAI,
    model: str,
    query: str,
    max_documents: int = 20,
    max_turns: int = 35,
    max_tokens: int = 4096,
    reasoning_effort: Optional[str] = None,
) -> RetrievalResult:
    """Drive a ``/responses`` model through the full harness for one query.

    The loop mirrors :func:`cosmos_retriever.inference.openai_chat.run_responses_search`
    (string first ``input``, flat function schemas, ``previous_response_id`` +
    ``function_call_output`` continuation) but advertises **all nine** harness
    tools and executes them against ``env`` rather than reconstructing the final
    set from ``<Document>`` blocks.
    """
    full_toolset = env._build_full_toolset()
    tool_specs = [
        tool.get_format(ProviderFormat.OPENAI)
        for tool in full_toolset.tools.values()
    ]

    prompt = (
        get_system_prompt(query)
        + "\n\nUse the tools above to search, curate, and refine. Call `curate` "
        "after every search to build your final set, and call `end_search` when "
        "you have thoroughly covered the query. Your curated set IS the answer — "
        "do not write out document blocks yourself."
    )

    common: dict = {"model": model, "tools": tool_specs, "max_output_tokens": max_tokens}
    if reasoning_effort:
        common["reasoning"] = {"effort": reasoning_effort}

    usage = _empty_usage()
    turn_tools: list[list[str]] = []
    tool_types_used: set[str] = set()
    tool_call_count = 0
    final_text = ""
    ended = False

    start = time.perf_counter()
    response = _create_with_retry(client, input=prompt, **common)
    num_turns = 1
    _acc_responses_usage(usage, response)

    while True:
        function_calls = [
            o for o in response.output if getattr(o, "type", None) == "function_call"
        ]
        if not function_calls:
            final_text = getattr(response, "output_text", "") or ""
            break

        turn_tools.append([fc.name for fc in function_calls])
        outputs: list[dict] = []
        for fc in function_calls:
            name = fc.name
            tool_types_used.add(name)
            tool_call_count += 1
            args = _parse_tool_arguments(fc.arguments)
            try:
                output = _dispatch_tool(env, name, args)
            except Exception as exc:  # noqa: BLE001 — surface tool errors to the model
                logger.warning("foundry_tool_error", tool=name, error=str(exc)[:200])
                output = f"Error executing '{name}': {str(exc)[:200]}"
            if name == _TERMINAL_TOOL:
                ended = True
            outputs.append(
                {"type": "function_call_output", "call_id": fc.call_id, "output": output}
            )

        if ended or num_turns >= max_turns:
            break

        response = _create_with_retry(
            client, previous_response_id=response.id, input=outputs, **common
        )
        num_turns += 1
        _acc_responses_usage(usage, response)

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
                justification=(
                    env.wm.curated_notes.get(chunk_id)
                    if hasattr(env.wm, "curated_notes")
                    else None
                ),
                rank=rank,
            )
        )

    trajectory = {
        "search_history": list(getattr(env.wm, "search_history", []) or []),
        "curated_importance": dict(getattr(env.wm, "curated_importance", {}) or {}),
        "turn_tools": turn_tools,
        "final_docs": [d.id for d in documents],
        "ended": ended,
    }

    logger.info(
        "foundry_harness_complete",
        model=model,
        num_turns=num_turns,
        tool_calls=tool_call_count,
        n_curated=len(env.wm.curated_ids),
        n_pool=len(env.wm.pool_ids),
        ended=ended,
    )

    return RetrievalResult(
        query=query,
        documents=documents,
        num_turns=num_turns,
        final_text=final_text,
        elapsed_s=round(elapsed, 3),
        pool_doc_ids=sorted({cid.split("__")[0] for cid in env.wm.pool_ids}),
        trajectory=trajectory,
        usage=usage,
        metadata={
            "backend": "foundry_full_harness",
            "model": model,
            "tool_calls": tool_call_count,
            "tool_types_used": ",".join(sorted(tool_types_used)),
            "n_pool": len(env.wm.pool_ids),
            "n_curated": len(env.wm.curated_ids),
        },
    )


class FoundryHarnessAgent:
    """Reusable driver: a Foundry ``/responses`` model over the full harness.

    Construct once (it wires up the Cosmos toolset, reranker, and chat client
    via :class:`~cosmos_retriever.retriever.CosmosRetriever`), then call
    :meth:`search` many times.
    """

    def __init__(
        self,
        settings: Optional[RetrieverSettings] = None,
        *,
        corpus_name: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
        max_turns: int = 35,
        max_tokens: int = 4096,
    ) -> None:
        self.settings = settings or get_settings()
        if not self.settings.use_generic_llm_backend:
            raise RuntimeError(
                "FoundryHarnessAgent requires a generic chat/responses backend. "
                "Set INFERENCE_BACKEND=openai_responses (or openai_chat) so the "
                "underlying retriever builds a chat client instead of vLLM."
            )
        # Reuse the retriever purely for its wired toolset + chat client; its
        # own vLLM inference model is never constructed for a generic backend.
        self._retriever = CosmosRetriever(self.settings, corpus_name=corpus_name)
        self.toolset = self._retriever.toolset
        self.client = self._retriever._chat_client
        self.model = self._retriever._chat_model
        self.reasoning_effort = reasoning_effort or self.settings.chat_reasoning_effort
        self.max_turns = max_turns
        self.max_tokens = max_tokens

        search_tool = self.toolset.get_tool("search_corpus")
        if not isinstance(search_tool, SearchCorpusTool):
            raise RuntimeError("toolset is missing a search_corpus tool")
        self._search_tool = search_tool

    def search(
        self,
        query: str,
        *,
        query_id: str = "adhoc",
        max_documents: int = 20,
        max_turns: Optional[int] = None,
    ) -> RetrievalResult:
        """Run the full harness for one query and return the curated documents."""
        if not query or not query.strip():
            raise ValueError("query must be a non-empty string")

        turns = max_turns or self.max_turns
        env = SlidingWindowSearchEnv(
            toolset=self.toolset,
            search_tool=self._search_tool,
            query_id=query_id,
            query_text=query,
            dataset_name="web",  # only keys the rerank instruction at inference
            text_token_counter=self._retriever._text_token_counter,
            max_turns=turns,
        )
        return run_foundry_harness_search(
            env=env,
            client=self.client,
            model=self.model,
            query=query,
            max_documents=max_documents,
            max_turns=turns,
            max_tokens=self.max_tokens,
            reasoning_effort=self.reasoning_effort,
        )
