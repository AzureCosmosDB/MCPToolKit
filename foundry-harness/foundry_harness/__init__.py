"""Drive the FULL Cosmos retrieval harness with a generic Foundry model.

This experimental package lets an Azure AI Foundry ``/responses`` deployment
(e.g. ``gpt-5.x``) drive the *complete* nine-tool agentic search harness —
``fan_out_search``, ``search_corpus``, ``grep_corpus``, ``read_document``,
``review_docs``, ``curate``, ``verify``, ``prune_chunks`` and ``end_search`` —
backed by the harness's real ``WorkingMemory`` (two-tier curated set + pool).

It contrasts with :mod:`cosmos_retriever.inference.openai_chat`, which exposes
only the four *directly executable* tools to a stock model and reconstructs the
final set from ``<Document id=...>`` blocks. Here the model uses the same tool
vocabulary as the fine-tuned Harness-1 model, and the final output is the real
``WorkingMemory.curated_ids`` set produced by the ``curate`` tool.

The committed harness code in ``cosmos_retriever`` is *not* modified: this
driver instantiates :class:`cosmos_retriever.env_rl.SlidingWindowSearchEnv`
purely as a stateful tool dispatcher and routes JSON function-calls to its
``_exec_*`` methods, guaranteeing identical tool semantics.
"""

from foundry_harness.agent import (
    FoundryHarnessAgent,
    FoundryHarnessResult,
    run_foundry_harness_search,
)

__all__ = [
    "FoundryHarnessAgent",
    "FoundryHarnessResult",
    "run_foundry_harness_search",
]
