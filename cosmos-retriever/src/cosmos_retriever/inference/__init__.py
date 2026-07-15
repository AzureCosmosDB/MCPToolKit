"""Inference-model adapters that drive the agent loop.

The agent is driven exclusively by OpenAI-compatible models via standard
function/tool calling over the four Cosmos tools — either the
``/chat/completions`` API (:func:`run_chat_search`) or the ``/responses`` API
(:func:`run_responses_search`, used by reasoning models such as gpt-5.x).
"""

from __future__ import annotations

from cosmos_retriever.inference.openai_chat import (
    ChatDocument,
    ChatSearchResult,
    run_chat_search,
    run_responses_search,
)

__all__ = [
    "ChatDocument",
    "ChatSearchResult",
    "run_chat_search",
    "run_responses_search",
]
