"""
This 'inference' sub-folder contains the inference logic for the Cosmos Retriever. 
All the code that interacts with the LLMs as well as the token budgeting system for when it does, is contained here.
The rest of the codebase is model-agnostic and does not need to know about the LLMs or how they are used.
"""


from __future__ import annotations

from cosmos_retriever.inference.agent_loop import (
    ChatDocument,
    AgentSearchResult,
    run_anthropic_search,
    run_chat_search,
    run_responses_search,
)

__all__ = [
    "ChatDocument",
    "AgentSearchResult",
    "run_anthropic_search",
    "run_chat_search",
    "run_responses_search",
]
