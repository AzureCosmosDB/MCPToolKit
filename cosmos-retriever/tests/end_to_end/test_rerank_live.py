"""Live integration test for VLLMQwen3Reranker against a REAL reranker server.

Unlike test_rerank.py (which fakes all HTTP), this exercises the full
`VLLMQwen3Reranker` code path against an actual running Qwen3-Reranker server
that exposes a vLLM-compatible ``/score`` endpoint returning
``{"data": [{"score": float}, ...]}``.

The test is skipped unless a reachable server is found. Point it at a server
with ``VLLM_RERANKER_URL`` (default ``http://127.0.0.1:8011``). It was validated
against the real Qwen3-Reranker-8B weights served locally.
"""
from __future__ import annotations

import os

import pytest
import requests

from cosmos_retriever.rerank import RerankResult, VLLMQwen3Reranker

RERANKER_URL = os.getenv("VLLM_RERANKER_URL", "http://127.0.0.1:8011")


def _server_reachable(url: str) -> bool:
    try:
        requests.get(f"{url}/health", timeout=2)
        return True
    except requests.exceptions.RequestException:
        return False


pytestmark = pytest.mark.skipif(
    not _server_reachable(RERANKER_URL),
    reason=f"no reranker server reachable at {RERANKER_URL} (set VLLM_RERANKER_URL)",
)


def test_live_reranker_orders_relevant_documents_first() -> None:
    reranker = VLLMQwen3Reranker(base_url=RERANKER_URL)
    query = "What is the capital of China?"
    documents = [
        "The capital of France is Paris.",
        "The capital of China is Beijing.",
        "Chocolate is a delicious treat.",
        "Beijing has been the capital of China for a long time.",
    ]

    results = reranker(query, documents)

    # Same count, all wrapped as RerankResult, original indices preserved as a set.
    assert len(results) == len(documents)
    assert all(isinstance(r, RerankResult) for r in results)
    assert {r.original_index for r in results} == set(range(len(documents)))

    # Sorted by descending score (contract of _rerank).
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)

    # The two China/Beijing documents (indices 1 and 3) must outrank the
    # irrelevant France/chocolate ones (indices 0 and 2).
    top_two = {results[0].original_index, results[1].original_index}
    assert top_two == {1, 3}
    assert results[1].score > results[2].score  # clear relevance gap


def test_live_reranker_empty_documents_returns_empty() -> None:
    reranker = VLLMQwen3Reranker(base_url=RERANKER_URL)
    assert reranker("any query", []) == []
