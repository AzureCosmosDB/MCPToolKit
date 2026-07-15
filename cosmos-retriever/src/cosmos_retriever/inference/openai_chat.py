"""Retrieval agent for generic OpenAI-compatible models.

This is the inference backend for *any* standard model — an Azure AI Foundry
deployment, OpenAI, or a local OpenAI-compatible server — reached through plain
function/tool calling.

It exposes two entry points over the same Cosmos
:class:`~cosmos_retriever.tools.ToolSet`:

* :func:`run_chat_search` — the ``/v1/chat/completions`` API (``tool_calls``).
* :func:`run_responses_search` — the ``/responses`` API used by reasoning
  models, with continuation via ``previous_response_id`` and
  ``function_call_output`` items.

Both follow the same loop:

1. Render the retrieval system prompt.
2. Advertise the four real tools (``search_corpus``, ``grep_corpus``,
   ``read_document``, ``prune_chunks``) as function schemas.
3. Loop: call the model; if it requests tool calls, execute each against the
   toolset and feed the results back; otherwise treat the assistant text as the
   final answer.
4. Parse the final ``<Document id=...>`` blocks the prompt asks for and hydrate
   each with the chunk text seen during searches.

The loop is fully synchronous (the Cosmos SDK + OpenAI SDK calls are sync), so
the FastAPI server runs it on a worker thread.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import json_repair
import openai
import structlog

from cosmos_retriever.prompts import get_retrieval_subagent_prompt
from cosmos_retriever.tools import ToolSet
from cosmos_retriever.utils import ProviderFormat

logger = structlog.get_logger("cosmos_retriever.inference.openai_chat")

# The four executable tools (defined in cosmos_retriever.tools) advertised to
# the model. The model "curates" its answer by emitting the final
# <Document id=...> blocks the system prompt asks for.
_CHAT_TOOL_NAMES = ("search_corpus", "grep_corpus", "read_document", "prune_chunks")

# Matches the per-result header the search/grep tools emit:
#   "\n# DOCUMENT ID: <id> (<n> tokens) \n<body...>"
_DOC_RESULT_RE = re.compile(r"#\s*DOCUMENT ID:\s*(?P<id>\S+)(?:\s*\(\d+\s*tokens\))?")

# Matches the final answer blocks the system prompt asks the model to produce.
_FINAL_DOC_RE = re.compile(
    r"<Document\s+id=[\"']?(?P<id>[^\"'\s>]+)[\"']?\s*>\s*"
    r"(?:<Justification>\s*(?P<justification>.*?)\s*</Justification>\s*)?"
    r"</Document>",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class ChatDocument:
    """A single curated document produced by the chat agent."""

    id: str
    text: str = ""
    justification: str | None = None
    rank: int | None = None


@dataclass
class ChatSearchResult:
    """Output of :func:`run_chat_search`."""

    documents: list[ChatDocument]
    num_turns: int
    final_text: str = ""
    pool_doc_ids: list[str] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    trajectory: dict[str, object] = field(default_factory=dict)
    metadata: dict[str, str | int | float] = field(default_factory=dict)


def _empty_usage() -> dict[str, int]:
    return {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
        "llm_calls": 0,
    }


def _acc_chat_usage(usage: dict[str, int], resp) -> None:
    """Accumulate /chat/completions usage (prompt/completion/total)."""
    u = getattr(resp, "usage", None)
    if u is None:
        return
    usage["prompt_tokens"] += int(getattr(u, "prompt_tokens", 0) or 0)
    usage["completion_tokens"] += int(getattr(u, "completion_tokens", 0) or 0)
    usage["total_tokens"] += int(getattr(u, "total_tokens", 0) or 0)
    usage["llm_calls"] += 1


def _acc_responses_usage(usage: dict[str, int], resp) -> None:
    """Accumulate /responses usage (input/output/reasoning tokens)."""
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
    """Parse a tool-call ``arguments`` JSON string, tolerating minor breakage."""

    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        try:
            parsed = json_repair.loads(raw)
        except Exception:  # noqa: BLE001 — last-ditch; bad args become {}
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _collect_doc_text(observation: str, store: dict[str, str]) -> None:
    """Record the first chunk text seen for each ``# DOCUMENT ID:`` in a result."""

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
    """Pull ranked ``<Document id=...>`` blocks out of the model's final answer."""

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
) -> ChatSearchResult:
    """Run the multi-turn retrieval agent against a generic chat model.

    Args:
        toolset: The Cosmos-backed :class:`ToolSet` (built **without** the
            ultra stub tools).
        client: An OpenAI-compatible client (``openai.OpenAI`` /
            ``openai.AzureOpenAI``).
        model: Model or Foundry deployment name passed as ``model=``.
        query: Natural-language information need.
        max_documents: Cap on curated documents to return / ask for.
        max_turns: Hard cap on chat round-trips.
        temperature / max_tokens: Sampling controls per call.

    Returns:
        A :class:`ChatSearchResult` with ranked documents and run metadata.
    """

    tool_specs = [
        tool.get_format(ProviderFormat.OPENAI_HARMONY)  # Chat-Completions function shape
        for name, tool in toolset.tools.items()
        if name in _CHAT_TOOL_NAMES
    ]

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

    for _ in range(max_turns):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tool_specs,
            tool_choice="auto",
            temperature=temperature,
            max_tokens=max_tokens,
        )
        num_turns += 1
        _acc_chat_usage(usage, response)
        message = response.choices[0].message
        tool_calls = message.tool_calls or []

        # Echo the assistant turn back into the transcript.
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

        for tc in tool_calls:
            name = tc.function.name
            tool_types_used.add(name)
            tool_call_count += 1
            args = _parse_tool_arguments(tc.function.arguments)
            tool = toolset.get_tool(name)
            if tool is None:
                output = f"Error: unknown tool '{name}'."
            else:
                try:
                    output, _metadata = tool(args)
                    _collect_doc_text(output, doc_text)
                except Exception as exc:  # noqa: BLE001 — surface tool errors to the model
                    logger.warning("chat_tool_error", tool=name, error=str(exc))
                    output = f"Error executing '{name}': {exc}"
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": output})
    else:
        # Loop exhausted without a final (no-tool-call) turn: fall back to the
        # last assistant text we saw, if any.
        for entry in reversed(messages):
            if entry.get("role") == "assistant" and entry.get("content"):
                final_text = entry["content"]
                break

    documents = _extract_documents(final_text, doc_text, max_documents)

    logger.info(
        "chat_search_complete",
        model=model,
        num_turns=num_turns,
        num_documents=len(documents),
        tool_calls=tool_call_count,
    )

    return ChatSearchResult(
        documents=documents,
        num_turns=num_turns,
        final_text=final_text,
        usage=usage,
        metadata={
            "backend": "openai_chat",
            "model": model,
            "tool_calls": tool_call_count,
            "tool_types_used": ",".join(sorted(tool_types_used)),
        },
    )


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
) -> ChatSearchResult:
    """Run the retrieval agent against an OpenAI **/responses** API model.

    Reasoning models such as ``gpt-5.x`` are exposed only through the
    ``responses`` endpoint, which uses a different shape from chat-completions:
    a plain-string first ``input``, flat function tool schemas, and multi-turn
    continuation via ``previous_response_id`` + ``function_call_output`` items.

    Args mirror :func:`run_chat_search`, plus ``reasoning_effort`` which (when
    set) is forwarded as ``reasoning={"effort": ...}`` for reasoning models.
    """

    tool_specs = [
        tool.get_format(ProviderFormat.OPENAI)  # flat Responses function shape
        for name, tool in toolset.tools.items()
        if name in _CHAT_TOOL_NAMES
    ]

    prompt = (
        get_retrieval_subagent_prompt(query, num_output_docs=max_documents)
        + "\n\nUse the available tools to search the corpus, then return ONLY the "
        "ranked <Document id=...> blocks (each with a <Justification>) for the most "
        "relevant documents. Do not answer the question yourself."
    )

    common: dict = {"model": model, "tools": tool_specs, "max_output_tokens": max_tokens}
    if reasoning_effort:
        common["reasoning"] = {"effort": reasoning_effort}

    doc_text: dict[str, str] = {}
    tool_types_used: set[str] = set()
    tool_call_count = 0
    final_text = ""
    usage = _empty_usage()
    search_history: list[str] = []
    turn_tools: list[list[str]] = []

    response = client.responses.create(input=prompt, **common)
    num_turns = 1
    _acc_responses_usage(usage, response)

    while True:
        function_calls = [o for o in response.output if getattr(o, "type", None) == "function_call"]
        if not function_calls:
            final_text = getattr(response, "output_text", "") or ""
            break
        if num_turns >= max_turns:
            final_text = getattr(response, "output_text", "") or ""
            break

        turn_tools.append([fc.name for fc in function_calls])
        outputs: list[dict] = []
        for fc in function_calls:
            name = fc.name
            tool_types_used.add(name)
            tool_call_count += 1
            args = _parse_tool_arguments(fc.arguments)
            if name in ("search_corpus", "grep_corpus"):
                q = args.get("query") or args.get("pattern") or args.get("q") or ""
                if q:
                    search_history.append(f"{name}: {str(q)[:100]}")
            tool = toolset.get_tool(name)
            if tool is None:
                output = f"Error: unknown tool '{name}'."
            else:
                try:
                    output, _metadata = tool(args)
                    _collect_doc_text(output, doc_text)
                except Exception as exc:  # noqa: BLE001 — surface tool errors to the model
                    logger.warning("responses_tool_error", tool=name, error=str(exc))
                    output = f"Error executing '{name}': {exc}"
            outputs.append(
                {"type": "function_call_output", "call_id": fc.call_id, "output": output}
            )

        response = client.responses.create(
            previous_response_id=response.id, input=outputs, **common
        )
        num_turns += 1
        _acc_responses_usage(usage, response)

    documents = _extract_documents(final_text, doc_text, max_documents)

    # Every chunk surfaced by any tool call across the whole trajectory lands in
    # ``doc_text``; its doc-level projection is the "pool" used for trajectory_recall.
    pool_doc_ids = sorted({cid.split("__")[0] for cid in doc_text})

    logger.info(
        "responses_search_complete",
        model=model,
        num_turns=num_turns,
        num_documents=len(documents),
        tool_calls=tool_call_count,
        pool_size=len(pool_doc_ids),
    )

    return ChatSearchResult(
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
    )


__all__ = ["ChatDocument", "ChatSearchResult", "run_chat_search", "run_responses_search"]
