
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

import json_repair
import openai
import requests
import structlog

from cosmos_retriever.prompts import (
    get_retrieval_subagent_budget_exhausted_message,
    get_retrieval_subagent_prompt,
)
from cosmos_retriever.tools import ToolSet
from cosmos_retriever.utils import ProviderFormat

logger = structlog.get_logger("cosmos_retriever.inference.agent_loop")


_DEFAULT_THRESHOLD_BUDGET = 16384   # soft cap: prompt prune/conclude + restrict to prune
_DEFAULT_TOKEN_BUDGET = 32268       # hard cap
_DEFAULT_TOOL_OUTPUT_BUDGET = 4096  # clamp search/read output when remaining < this
_DEFAULT_SPILLAGE_FRACTION = 0.5    # allowed spillage past threshold before hard reject

# Marker appended to each observation so pruning never removes past it (upstream parity).
_TOKEN_MARKER_RE = re.compile(r"\n\n\[Token usage:")


def _remove_chunks_from_text(text: str, chunk_ids: set[str]) -> str:
    """Replace pruned ``# DOCUMENT ID: <id>`` blocks with a tombstone marker.

    Rather than deleting the block outright (which silently rewrites the single
    physical copy of the chunk that lives in an earlier observation), the block
    body is swapped for a compact ``# DOCUMENT ID: <id> [pruned]`` line. This
    reclaims almost all of the tokens while leaving a trace so the model can see
    that *it* pruned the chunk. The operation is idempotent: re-pruning a
    tombstone yields the same tombstone.
    """
    if not text or not chunk_ids:
        return text
    matches = list(_DOC_RESULT_RE.finditer(text))
    if not matches:
        return text
    marker = _TOKEN_MARKER_RE.search(text)
    text_end = marker.start() if marker else len(text)

    prune_ranges: list[tuple[int, int, str]] = []
    for idx, match in enumerate(matches):
        doc_id = match.group("id")
        if doc_id in chunk_ids:
            start = match.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else text_end
            prune_ranges.append((start, end, doc_id))
    if not prune_ranges:
        return text

    parts: list[str] = []
    last = 0
    for start, end, doc_id in prune_ranges:
        parts.append(text[last:start])
        parts.append(f"# DOCUMENT ID: {doc_id} [pruned]\n\n")
        last = end
    parts.append(text[last:])
    pruned = re.sub(r"\n{3,}", "\n\n", "".join(parts))
    return pruned.strip()


class _BudgetController:
    """Per-query token-budget + dedup enforcer.
    """

    def __init__(
        self,
        *,
        text_token_counter,
        threshold_budget: int = _DEFAULT_THRESHOLD_BUDGET,
        token_budget: int = _DEFAULT_TOKEN_BUDGET,
        tool_output_budget: int = _DEFAULT_TOOL_OUTPUT_BUDGET,
        spillage_fraction: float = _DEFAULT_SPILLAGE_FRACTION,
    ) -> None:
        self._count = text_token_counter or (lambda s: len(s) // 4)
        self.threshold_budget = threshold_budget
        self.token_budget = token_budget
        self.tool_output_budget = tool_output_budget
        spillage = int((token_budget - threshold_budget) * spillage_fraction)
        self.rejection_budget = threshold_budget + spillage
        # dedup state
        self._ids_seen: set[str] = set()
        self._doc_id_to_query: dict[str, str] = {}

        # prune state
        self._pruned_chunk_ids: set[str] = set()

        # per-step (parallel tool calls in one turn) token tracking
        self._step_tokens_used: int = 0

    def search_overrides(self) -> dict:
        return {"ignore_ids": list(self._ids_seen)}

    def record_search(self, returned_chunk_ids, query: str) -> None:
        self._ids_seen.update(returned_chunk_ids)
        for chunk_id in returned_chunk_ids:
            doc_id = chunk_id.split("_")[0] if "_" in chunk_id else chunk_id
            self._doc_id_to_query.setdefault(doc_id, query)

    def read_overrides(self, params: dict) -> dict:
        doc_id = params.get("doc_id") or params.get("id", "")
        if "_" in doc_id:
            doc_id = doc_id.split("_")[0]
        if doc_id in self._doc_id_to_query:
            return {"query": self._doc_id_to_query[doc_id]}
        return {}

    def record_prune(self, chunk_ids) -> None:
        if isinstance(chunk_ids, (list, tuple, set)):
            self._pruned_chunk_ids.update(str(c) for c in chunk_ids)

    def prune_text(self, text: str) -> str:
        return _remove_chunks_from_text(text, self._pruned_chunk_ids)

    # ── token accounting (TokenBudgetRetrievalSubagent) ──────────────────
    def reset_step(self) -> None:
        self._step_tokens_used = 0

    def add_step_tokens(self, text: str) -> None:
        self._step_tokens_used += self._count(text)

    def annotate(self, text: str, current_usage: int) -> str:
        return f"{text}\n\n[Token usage: {current_usage}/{self.threshold_budget}]"

    def tool_max_tokens(self, tool_name: str, current_usage: int) -> int | None:
        """_call_tool(): clamp search/read output when budget is tight."""
        if tool_name in ("search_corpus", "read_document"):
            remaining = self.token_budget - current_usage - self._step_tokens_used
            if remaining < self.tool_output_budget:
                return max(512, remaining // 2)
        return None

    def should_reject(self, tool_name: str, current_usage: int) -> bool:
        """_call_tool(): hard-reject non-prune tools past the rejection budget."""
        effective = current_usage + self._step_tokens_used
        return effective > self.rejection_budget and tool_name != "prune_chunks"

    def rejection_message(self, current_usage: int) -> str:
        effective = current_usage + self._step_tokens_used
        return (
            f"Error: Token budget exceeded ({effective}/{self.threshold_budget} tokens). "
            "You must use prune_chunks to reduce context size or provide your final answer."
        )

    def over_threshold(self, current_usage: int) -> bool:
        return current_usage > self.threshold_budget

    def over_token_budget(self, current_usage: int) -> bool:
        return current_usage > self.token_budget

_CHAT_TOOL_NAMES = (
    "search_corpus",
    "grep_corpus",
    "read_document",
    "prune_chunks",
    "execute_query",
)

_DOC_RESULT_RE = re.compile(r"#\s*DOCUMENT ID:\s*(?P<id>\S+)(?:\s*\(\d+\s*tokens\))?")

_FINAL_DOC_RE = re.compile(
    r"<Document\s+id=[\"']?(?P<id>[^\"'\s>]+)[\"']?\s*>\s*"
    r"(?:<Justification>\s*(?P<justification>.*?)\s*</Justification>\s*)?"
    r"</Document>",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class ChatDocument:

    id: str
    text: str = ""
    justification: str | None = None
    rank: int | None = None


@dataclass
class AgentSearchResult:

    documents: list[ChatDocument]
    num_turns: int
    final_text: str = ""
    pool_doc_ids: list[str] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    trajectory: dict[str, object] = field(default_factory=dict)
    metadata: dict[str, str | int | float] = field(default_factory=dict)
    timing: dict[str, float] = field(default_factory=dict)


def _empty_usage() -> dict[str, int]:
    return {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
        "llm_calls": 0,
    }


def _acc_chat_usage(usage: dict[str, int], resp) -> None:
    u = getattr(resp, "usage", None)
    if u is None:
        return
    usage["prompt_tokens"] += int(getattr(u, "prompt_tokens", 0) or 0)
    usage["completion_tokens"] += int(getattr(u, "completion_tokens", 0) or 0)
    usage["total_tokens"] += int(getattr(u, "total_tokens", 0) or 0)
    usage["llm_calls"] += 1


def _acc_responses_usage(usage: dict[str, int], resp) -> None:
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


def _parse_tool_arguments(raw: str | None) -> dict:

    if not raw:
        return {}
    parsed: object = raw
    # Some models (e.g. gpt-oss via vLLM/Harmony) double-encode tool arguments,
    # yielding a JSON string that itself contains JSON. Unwrap up to a few levels.
    for _ in range(3):
        if isinstance(parsed, dict):
            return parsed
        if not isinstance(parsed, str):
            break
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError:
            try:
                parsed = json_repair.loads(parsed)
            except Exception:
                return {}
    return parsed if isinstance(parsed, dict) else {}


def _collect_doc_text(observation: str, store: dict[str, str]) -> None:

    matches = list(_DOC_RESULT_RE.finditer(observation))
    for idx, match in enumerate(matches):
        chunk_id = match.group("id")
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(observation)
        body = observation[start:end].strip()
        if body and not store.get(chunk_id):
            store[chunk_id] = body


def _extract_documents(
    final_text: str, doc_text: dict[str, str], max_documents: int
) -> list[ChatDocument]:

    documents: list[ChatDocument] = []
    seen: set[str] = set()
    for match in _FINAL_DOC_RE.finditer(final_text):
        doc_id = match.group("id")
        if doc_id in seen:
            continue
        seen.add(doc_id)
        justification = match.group("justification")
        text = doc_text.get(doc_id) or doc_text.get(doc_id.split("__")[0]) or ""
        documents.append(
            ChatDocument(
                id=doc_id,
                text=text,
                justification=justification.strip() if justification else None,
                rank=len(documents),
            )
        )
        if len(documents) >= max_documents:
            break
    return documents


def _count_messages(messages: list[dict], counter) -> int:
    """Token count of a chat-completions transcript (post-prune)."""
    total = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            total += counter(c)
        for tc in m.get("tool_calls", []) or []:
            fn = tc.get("function", {})
            for key in ("name", "arguments"):
                v = fn.get(key)
                if isinstance(v, str):
                    total += counter(v)
    return total


def run_chat_search(
    *,
    toolset: ToolSet,
    client: openai.OpenAI,
    model: str,
    query: str,
    max_documents: int = 20,
    max_turns: int = 20,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    text_token_counter=None,
    threshold_budget: int = _DEFAULT_THRESHOLD_BUDGET,
    token_budget: int = _DEFAULT_TOKEN_BUDGET,
) -> AgentSearchResult:

    tool_specs = [
        tool.get_format(ProviderFormat.OPENAI_HARMONY)
        for name, tool in toolset.tools.items()
        if name in _CHAT_TOOL_NAMES
    ]
    prune_specs = [
        tool.get_format(ProviderFormat.OPENAI_HARMONY)
        for name, tool in toolset.tools.items()
        if name == "prune_chunks"
    ]

    budget = _BudgetController(
        text_token_counter=text_token_counter,
        threshold_budget=threshold_budget,
        token_budget=token_budget,
    )

    messages: list[dict] = [
        {"role": "system", "content": get_retrieval_subagent_prompt(query, num_output_docs=max_documents)},
        {
            "role": "user",
            "content": (
                "Use the available tools to search the corpus, then return ONLY the "
                "ranked <Document id=...> blocks (with a <Justification>) for the most "
                "relevant documents. Do not answer the question yourself."
            ),
        },
    ]

    doc_text: dict[str, str] = {}
    tool_types_used: set[str] = set()
    tool_call_count = 0
    final_text = ""
    num_turns = 0
    usage = _empty_usage()

    import collections as _collections
    timing = {"llm_s": 0.0, "tools_s": 0.0, "retrieval_s": 0.0, "rerank_s": 0.0}
    tool_s = _collections.defaultdict(float)

    for _ in range(max_turns):
        # ── prepare_for_inference: prune tool messages, count, decide state
        for m in messages:
            if m.get("role") == "tool" and isinstance(m.get("content"), str):
                m["content"] = budget.prune_text(m["content"])
        current_usage = _count_messages(messages, budget._count)

        turn_messages = messages
        turn_specs = tool_specs
        if budget.over_threshold(current_usage) and not budget.over_token_budget(current_usage):
            turn_messages = messages + [
                {
                    "role": "user",
                    "content": get_retrieval_subagent_budget_exhausted_message(
                        current_usage, budget.threshold_budget
                    ),
                }
            ]
            turn_specs = prune_specs or tool_specs

        out_cap = max(256, min(max_tokens, budget.token_budget - current_usage))

        _t = time.perf_counter()
        response = client.chat.completions.create(
            model=model,
            messages=turn_messages,
            tools=turn_specs,
            tool_choice="auto",
            temperature=temperature,
            max_tokens=out_cap,
        )
        timing["llm_s"] += time.perf_counter() - _t
        num_turns += 1
        _acc_chat_usage(usage, response)
        message = response.choices[0].message
        tool_calls = message.tool_calls or []

        assistant_entry: dict = {"role": "assistant", "content": message.content or ""}
        if tool_calls:
            assistant_entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ]
        messages.append(assistant_entry)

        if not tool_calls:
            final_text = message.content or ""
            break

        budget.reset_step()
        for tc in tool_calls:
            name = tc.function.name
            tool_types_used.add(name)
            tool_call_count += 1
            args = _parse_tool_arguments(tc.function.arguments)
            tool = toolset.get_tool(name)
            if tool is None:
                output = f"Error: unknown tool '{name}'."
            elif budget.should_reject(name, current_usage):
                output = budget.rejection_message(current_usage)
                logger.warning("tool_rejected_over_budget", tool=name, usage=current_usage)
            else:
                overrides: dict = {}
                if name == "search_corpus":
                    overrides.update(budget.search_overrides())
                elif name == "read_document":
                    overrides.update(budget.read_overrides(args))
                clamp = budget.tool_max_tokens(name, current_usage)
                if clamp is not None:
                    overrides["max_tokens"] = clamp
                try:
                    _tt = time.perf_counter()
                    output, _metadata = tool(args, overrides or None)
                    _dt = time.perf_counter() - _tt
                    timing["tools_s"] += _dt
                    tool_s[name] += _dt
                    _rs = getattr(_metadata, "retrieval_s", None)
                    if _rs is not None:
                        timing["retrieval_s"] += _rs
                        timing["rerank_s"] += getattr(_metadata, "rerank_s", 0.0) or 0.0
                    _collect_doc_text(output, doc_text)
                    if name == "search_corpus" and _metadata is not None:
                        budget.record_search(
                            getattr(_metadata, "returned_chunk_ids", []) or [], str(args.get("query", ""))
                        )
                    elif name == "prune_chunks":
                        budget.record_prune(args.get("chunk_ids"))
                    budget.add_step_tokens(output)
                except Exception as exc:  # noqa: BLE001 — surface tool errors to the model
                    logger.warning("chat_tool_error", tool=name, error=str(exc))
                    output = f"Error executing '{name}': {exc}"

            output = budget.annotate(output, current_usage)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": output})
    else:
        for entry in reversed(messages):
            if entry.get("role") == "assistant" and entry.get("content"):
                final_text = entry["content"]
                break

    documents = _extract_documents(final_text, doc_text, max_documents)
    pool_doc_ids = sorted({cid.split("__")[0] for cid in doc_text})

    logger.info(
        "chat_search_complete",
        model=model,
        num_turns=num_turns,
        num_documents=len(documents),
        tool_calls=tool_call_count,
        pruned_chunks=len(budget._pruned_chunk_ids),
    )

    return AgentSearchResult(
        documents=documents,
        num_turns=num_turns,
        final_text=final_text,
        pool_doc_ids=pool_doc_ids,
        usage=usage,
        trajectory={"final_docs": [d.id for d in documents]},
        metadata={
            "backend": "openai_chat",
            "model": model,
            "tool_calls": tool_call_count,
            "tool_types_used": ",".join(sorted(tool_types_used)),
        },
        timing={
            "llm_s": round(timing["llm_s"], 2),
            "tools_s": round(timing["tools_s"], 2),
            "retrieval_s": round(timing["retrieval_s"], 2),
            "rerank_s": round(timing["rerank_s"], 2),
            **{f"tool.{k}_s": round(v, 2) for k, v in tool_s.items()},
        },
    )


def _responses_output_to_call_item(fc) -> dict:
    """Render a model function_call output item back into an input item so the
    transcript can be resent (we drive the /responses API without
    previous_response_id, which is what makes real pruning possible)."""
    return {
        "type": "function_call",
        "call_id": fc.call_id,
        "name": fc.name,
        "arguments": fc.arguments,
    }


def _count_items(items: list[dict], counter) -> int:
    """Token count of a /responses input-items transcript (post-prune)."""
    total = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        for key in ("content", "output", "arguments", "name"):
            val = it.get(key)
            if isinstance(val, str):
                total += counter(val)
    return total


def run_responses_search(
    *,
    toolset: ToolSet,
    client: openai.OpenAI,
    model: str,
    query: str,
    max_documents: int = 20,
    max_turns: int = 20,
    max_tokens: int = 4096,
    reasoning_effort: str | None = None,
    text_token_counter=None,
    threshold_budget: int = _DEFAULT_THRESHOLD_BUDGET,
    token_budget: int = _DEFAULT_TOKEN_BUDGET,
) -> AgentSearchResult:

    tool_specs = [
        tool.get_format(ProviderFormat.OPENAI)
        for name, tool in toolset.tools.items()
        if name in _CHAT_TOOL_NAMES
    ]
    # Prune-only toolset for the over-threshold "prune or conclude" state.
    prune_specs = [
        tool.get_format(ProviderFormat.OPENAI)
        for name, tool in toolset.tools.items()
        if name == "prune_chunks"
    ]

    budget = _BudgetController(
        text_token_counter=text_token_counter,
        threshold_budget=threshold_budget,
        token_budget=token_budget,
    )

    prompt = (
        get_retrieval_subagent_prompt(query, num_output_docs=max_documents)
        + "\n\nUse the available tools to search the corpus, then return ONLY the "
        "ranked <Document id=...> blocks (each with a <Justification>) for the most "
        "relevant documents. Do not answer the question yourself."
    )

    common: dict = {"model": model, "tools": tool_specs}
    if reasoning_effort:
        common["reasoning"] = {"effort": reasoning_effort}

    # Local transcript (no previous_response_id) so we can prune it in place.
    input_items: list[dict] = [{"role": "user", "content": prompt}]

    doc_text: dict[str, str] = {}
    tool_types_used: set[str] = set()
    tool_call_count = 0
    final_text = ""
    usage = _empty_usage()
    search_history: list[str] = []
    turn_tools: list[list[str]] = []

    import collections as _collections
    timing = {"llm_s": 0.0, "tools_s": 0.0, "retrieval_s": 0.0, "rerank_s": 0.0}
    tool_s = _collections.defaultdict(float)

    num_turns = 0
    while True:
        # ── prepare_for_inference: prune the transcript, count tokens, decide state
        for it in input_items:
            if isinstance(it, dict) and it.get("type") == "function_call_output":
                it["output"] = budget.prune_text(it["output"])
        current_usage = _count_items(input_items, budget._count)

        turn_input = input_items
        turn_specs = tool_specs
        if budget.over_threshold(current_usage) and not budget.over_token_budget(current_usage):
            # Force prune-or-conclude: inject the budget message and restrict to prune.
            turn_input = input_items + [
                {
                    "role": "user",
                    "content": get_retrieval_subagent_budget_exhausted_message(
                        current_usage, budget.threshold_budget
                    ),
                }
            ]
            turn_specs = prune_specs or tool_specs

        out_cap = max(256, min(max_tokens, budget.token_budget - current_usage))
        call_kwargs = {**common, "tools": turn_specs, "max_output_tokens": out_cap}

        _t = time.perf_counter()
        response = client.responses.create(input=turn_input, **call_kwargs)
        timing["llm_s"] += time.perf_counter() - _t
        num_turns += 1
        _acc_responses_usage(usage, response)

        function_calls = [o for o in response.output if getattr(o, "type", None) == "function_call"]
        if not function_calls:
            final_text = getattr(response, "output_text", "") or ""
            break
        if num_turns >= max_turns:
            final_text = getattr(response, "output_text", "") or ""
            break

        turn_tools.append([fc.name for fc in function_calls])
        # ── act: execute tools with dedup + reject + clamp; observe: annotate
        budget.reset_step()
        for fc in function_calls:
            name = fc.name
            tool_types_used.add(name)
            tool_call_count += 1
            args = _parse_tool_arguments(fc.arguments)
            if name in ("search_corpus", "grep_corpus"):
                q = args.get("query") or args.get("pattern") or args.get("q") or ""
                if q:
                    search_history.append(f"{name}: {str(q)[:100]}")

            input_items.append(_responses_output_to_call_item(fc))

            tool = toolset.get_tool(name)
            if tool is None:
                output = f"Error: unknown tool '{name}'."
            elif budget.should_reject(name, current_usage):
                output = budget.rejection_message(current_usage)
                logger.warning("tool_rejected_over_budget", tool=name, usage=current_usage)
            else:
                overrides: dict = {}
                if name == "search_corpus":
                    overrides.update(budget.search_overrides())
                elif name == "read_document":
                    overrides.update(budget.read_overrides(args))
                clamp = budget.tool_max_tokens(name, current_usage)
                if clamp is not None:
                    overrides["max_tokens"] = clamp
                try:
                    _tt = time.perf_counter()
                    output, _metadata = tool(args, overrides or None)
                    _dt = time.perf_counter() - _tt
                    timing["tools_s"] += _dt
                    tool_s[name] += _dt
                    _rs = getattr(_metadata, "retrieval_s", None)
                    if _rs is not None:
                        timing["retrieval_s"] += _rs
                        timing["rerank_s"] += getattr(_metadata, "rerank_s", 0.0) or 0.0
                    _collect_doc_text(output, doc_text)
                    if name == "search_corpus" and _metadata is not None:
                        budget.record_search(
                            getattr(_metadata, "returned_chunk_ids", []) or [], str(args.get("query", ""))
                        )
                    elif name == "prune_chunks":
                        budget.record_prune(args.get("chunk_ids"))
                    budget.add_step_tokens(output)
                except Exception as exc:  # noqa: BLE001 — surface tool errors to the model
                    logger.warning("responses_tool_error", tool=name, error=str(exc))
                    output = f"Error executing '{name}': {exc}"

            output = budget.annotate(output, current_usage)
            input_items.append(
                {"type": "function_call_output", "call_id": fc.call_id, "output": output}
            )

    documents = _extract_documents(final_text, doc_text, max_documents)
    pool_doc_ids = sorted({cid.split("__")[0] for cid in doc_text})

    logger.info(
        "responses_search_complete",
        model=model,
        num_turns=num_turns,
        num_documents=len(documents),
        tool_calls=tool_call_count,
        pool_size=len(pool_doc_ids),
        pruned_chunks=len(budget._pruned_chunk_ids),
    )

    return AgentSearchResult(
        documents=documents,
        num_turns=num_turns,
        final_text=final_text,
        pool_doc_ids=pool_doc_ids,
        usage=usage,
        trajectory={
            "search_history": search_history,
            "turn_tools": turn_tools,
            "final_docs": [d.id for d in documents],
        },
        metadata={
            "backend": "openai_responses",
            "model": model,
            "tool_calls": tool_call_count,
            "tool_types_used": ",".join(sorted(tool_types_used)),
        },
        timing={
            "llm_s": round(timing["llm_s"], 2),
            "tools_s": round(timing["tools_s"], 2),
            "retrieval_s": round(timing["retrieval_s"], 2),
            "rerank_s": round(timing["rerank_s"], 2),
            **{f"tool.{k}_s": round(v, 2) for k, v in tool_s.items()},
        },
    )


def _acc_anthropic_usage(usage: dict[str, int], data: dict) -> None:
    u = data.get("usage") or {}
    inp = int(u.get("input_tokens") or 0)
    out = int(u.get("output_tokens") or 0)
    usage["prompt_tokens"] += inp
    usage["completion_tokens"] += out
    usage["total_tokens"] += inp + out
    usage["llm_calls"] += 1


def _anthropic_messages_url(base_url: str) -> str:
    b = base_url.rstrip("/")
    if b.endswith("/messages"):
        return b
    if b.endswith("/v1"):
        return b + "/messages"
    return b + "/v1/messages"


def run_anthropic_search(
    *,
    toolset: ToolSet,
    base_url: str,
    api_key: str,
    model: str,
    query: str,
    max_documents: int = 20,
    max_turns: int = 20,
    max_tokens: int = 4096,
    anthropic_version: str = "2023-06-01",
    auth_header: str = "x-api-key",
    timeout_s: int = 600,
) -> AgentSearchResult:
    tools = [
        tool.get_format(ProviderFormat.ANTHROPIC)
        for name, tool in toolset.tools.items()
        if name in _CHAT_TOOL_NAMES
    ]
    system = get_retrieval_subagent_prompt(query, num_output_docs=max_documents)
    messages: list[dict] = [
        {
            "role": "user",
            "content": (
                "Use the available tools to search the corpus, then return ONLY the "
                "ranked <Document id=...> blocks (each with a <Justification>) for the most "
                "relevant documents. Do not answer the question yourself."
            ),
        }
    ]

    url = _anthropic_messages_url(base_url)
    headers = {
        "content-type": "application/json",
        "anthropic-version": anthropic_version,
        auth_header: api_key,
    }

    doc_text: dict[str, str] = {}
    tool_types_used: set[str] = set()
    tool_call_count = 0
    final_text = ""
    num_turns = 0
    usage = _empty_usage()
    search_history: list[str] = []
    turn_tools: list[list[str]] = []

    for _ in range(max_turns):
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
            "tools": tools,
        }
        response = requests.post(url, json=payload, headers=headers, timeout=timeout_s)
        response.raise_for_status()
        data = response.json()
        num_turns += 1
        _acc_anthropic_usage(usage, data)

        content = data.get("content") or []
        messages.append({"role": "assistant", "content": content})

        tool_uses = [b for b in content if b.get("type") == "tool_use"]
        if not tool_uses:
            final_text = "".join(
                b.get("text", "") for b in content if b.get("type") == "text"
            )
            break

        turn_tools.append([tu.get("name", "") for tu in tool_uses])
        tool_results: list[dict] = []
        for tu in tool_uses:
            name = tu.get("name", "")
            tool_types_used.add(name)
            tool_call_count += 1
            args = tu.get("input") or {}
            if name in ("search_corpus", "grep_corpus"):
                q = args.get("query") or args.get("pattern") or ""
                if q:
                    search_history.append(f"{name}: {str(q)[:100]}")
            tool = toolset.get_tool(name)
            if tool is None:
                output = f"Error: unknown tool '{name}'."
            else:
                try:
                    output, _metadata = tool(args)
                    _collect_doc_text(output, doc_text)
                except Exception as exc:
                    logger.warning("anthropic_tool_error", tool=name, error=str(exc))
                    output = f"Error executing '{name}': {exc}"
            tool_results.append(
                {"type": "tool_result", "tool_use_id": tu.get("id"), "content": output}
            )
        messages.append({"role": "user", "content": tool_results})
    else:
        final_text = ""

    documents = _extract_documents(final_text, doc_text, max_documents)
    pool_doc_ids = sorted({cid.split("__")[0] for cid in doc_text})

    logger.info(
        "anthropic_search_complete",
        model=model,
        num_turns=num_turns,
        num_documents=len(documents),
        tool_calls=tool_call_count,
        pool_size=len(pool_doc_ids),
    )

    return AgentSearchResult(
        documents=documents,
        num_turns=num_turns,
        final_text=final_text,
        pool_doc_ids=pool_doc_ids,
        usage=usage,
        trajectory={
            "search_history": search_history,
            "turn_tools": turn_tools,
            "final_docs": [d.id for d in documents],
        },
        metadata={
            "backend": "anthropic_messages",
            "model": model,
            "tool_calls": tool_call_count,
            "tool_types_used": ",".join(sorted(tool_types_used)),
        },
    )


__all__ = [
    "ChatDocument",
    "AgentSearchResult",
    "run_anthropic_search",
    "run_chat_search",
    "run_responses_search",
]
