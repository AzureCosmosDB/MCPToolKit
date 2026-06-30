from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import time
from typing import TYPE_CHECKING, Callable, List, Optional

import requests
import structlog

from cosmos_retriever.config import get_config

if TYPE_CHECKING:
    from baseten_performance_client import ClassificationResponse, PerformanceClient

logger = structlog.get_logger("search_agent.rerank")


@dataclass
class RerankResult:
    """Result of reranking a single document."""

    document: str
    score: float
    original_index: int
    tokens: Optional[int] = None  # Token count, populated if token_counter is available


class Reranker(ABC):
    """Abstract base class for reranking documents based on a query."""

    def __init__(
        self,
        token_counter: Optional[Callable[[str], int]] = None,
        max_tokens: Optional[int] = None,
    ):
        """
        Initialize the reranker.

        Args:
            token_counter: Optional callable that counts tokens in a string.
            max_tokens: Maximum total tokens for the output. Documents are returned
                in reranked order until this budget is exhausted.

        Raises:
            ValueError: If max_tokens is specified without a token_counter.
        """
        if max_tokens is not None and token_counter is None:
            raise ValueError("token_counter is required when max_tokens is specified")
        self.token_counter = token_counter
        self.max_tokens = max_tokens

    def _truncate_results(
        self, results: List[RerankResult], max_tokens: Optional[int] = None
    ) -> List[RerankResult]:
        """Truncate results to fit within max_tokens total.

        Also populates the tokens field for each result if token_counter is available.

        Args:
            results: List of RerankResult objects to truncate.
            max_tokens: Optional override for max_tokens. If not provided,
                uses the instance's max_tokens setting.
        """
        # If we have a token_counter, populate tokens for all results
        if self.token_counter is not None:
            for result in results:
                result.tokens = self.token_counter(result.document)

        effective_max_tokens = max_tokens if max_tokens is not None else self.max_tokens
        if self.token_counter is None or effective_max_tokens is None:
            return results

        truncated: List[RerankResult] = []
        total_tokens = 0
        for result in results:
            doc_tokens = result.tokens  # Already calculated above
            assert doc_tokens is not None
            if total_tokens + doc_tokens > effective_max_tokens:
                logger.info(
                    "truncating_results",
                    kept=len(truncated),
                    dropped=len(results) - len(truncated),
                    total_tokens=total_tokens,
                    max_tokens=effective_max_tokens,
                )
                break
            truncated.append(result)
            total_tokens += doc_tokens

        return truncated

    @abstractmethod
    def _rerank(
        self,
        query: str,
        documents: List[str],
        instruction: Optional[str] = None,
    ) -> List[RerankResult]:
        """
        Rerank documents based on relevance to the query.

        Subclasses must implement this method to perform the actual reranking.

        Args:
            query: The search query to rank documents against.
            documents: List of document strings to rerank.
            instruction: Optional instruction for the reranker.

        Returns:
            List of RerankResult objects sorted by relevance (highest first).
        """
        pass

    def __call__(
        self,
        query: str,
        documents: List[str],
        instruction: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> List[RerankResult]:
        """
        Rerank documents based on relevance to the query.

        Args:
            query: The search query to rank documents against.
            documents: List of document strings to rerank.
            instruction: Optional instruction for the reranker.
            max_tokens: Optional override for max_tokens budget. If provided,
                overrides the instance's max_tokens for this call only.

        Returns:
            List of RerankResult objects sorted by relevance (highest first),
            truncated to fit within max_tokens if token_counter is provided.
        """
        start = time.perf_counter()
        results = self._rerank(query, documents, instruction)
        elapsed_ms = (time.perf_counter() - start) * 1000
        if elapsed_ms > 1500:
            logger.warning(
                "Extremely slow reranking",
                elapsed_ms=round(elapsed_ms, 1),
            )
        return self._truncate_results(results, max_tokens=max_tokens)


class BasetenReranker(Reranker):
    """Reranker implementation using Baseten's classification API on top of Qwen 3 8B"""

    PREFIX = '<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n'
    SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
    DEFAULT_INSTRUCTION = (
        "Given a web search query, retrieve relevant passages that answer the query"
    )

    def __init__(
        self,
        client: Optional[PerformanceClient] = None,
        token_counter: Optional[Callable[[str], int]] = None,
        max_tokens: Optional[int] = None,
        batch_size: int = 16,
        max_concurrent_requests: int = 256,
        timeout_s: int = 360,
    ):
        """
        Initialize the Baseten reranker.

        Args:
            client: Optional PerformanceClient. If not provided, uses config.
            token_counter: Optional callable that counts tokens in a string.
            max_tokens: Maximum total tokens for the output.
            batch_size: Batch size for classification requests.
            max_concurrent_requests: Maximum concurrent requests.
            timeout_s: Timeout in seconds.
        """
        super().__init__(token_counter=token_counter, max_tokens=max_tokens)
        if client is None:
            config = get_config()
            client = config.get_baseten_client()  # type: ignore[assignment]


            
        self.client = client
        self.batch_size = batch_size
        self.max_concurrent_requests = max_concurrent_requests
        self.timeout_s = timeout_s

    def _format_input(
        self, instruction: Optional[str], query: str, document: str
    ) -> str:
        """Format input for the classification model."""
        if instruction is None:
            instruction = self.DEFAULT_INSTRUCTION
        return f"{self.PREFIX}<Instruct>: {instruction}\n<Query>: {query}\n<Document>: {document}{self.SUFFIX}"

    def _rerank(
        self,
        query: str,
        documents: list[str],
        instruction: Optional[str] = None,
    ) -> list[RerankResult]:
        if not documents:
            return []

        # Format all documents for classification
        inputs = [self._format_input(instruction, query, doc) for doc in documents]

        # Classify all inputs
        response: ClassificationResponse = self.client.classify(
            inputs=inputs,
            truncate=True,
            batch_size=self.batch_size,
            max_concurrent_requests=self.max_concurrent_requests,
            timeout_s=self.timeout_s,
        )

        # Extract scores for "yes" labels
        results = []
        for idx, (doc, group) in enumerate(zip(documents, response.data)):
            score = 0.0
            for result in group:
                if result.label == "yes":
                    score = result.score
                    break
            results.append(RerankResult(document=doc, score=score, original_index=idx))

        # Sort by score descending
        results.sort(key=lambda x: x.score, reverse=True)
        return results


class VLLMQwen3Reranker(Reranker):
    """Drop-in replacement for BasetenReranker backed by a local vLLM server.

    Serves Qwen3-Reranker-8B locally via vLLM's /score endpoint (original
    Qwen3-reranker sequence-classification conversion). The prompt template and
    yes/no scoring match BasetenReranker exactly, so scores match the Baseten
    deployment up to numerics — use it when the Baseten reranker deployment is
    unavailable.

    Server launch:
        vllm serve Qwen/Qwen3-Reranker-8B --port 8011 \
          --hf-overrides '{"architectures": ["Qwen3ForSequenceClassification"],
                           "classifier_from_token": ["no", "yes"],
                           "is_original_qwen3_reranker": true}'
    Point at it with VLLM_RERANKER_URL (default http://127.0.0.1:8011).
    """

    PREFIX = '<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n'
    SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
    DEFAULT_INSTRUCTION = (
        "Given a web search query, retrieve relevant passages that answer the query"
    )

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: str = "Qwen/Qwen3-Reranker-8B",
        token_counter: Optional[Callable[[str], int]] = None,
        max_tokens: Optional[int] = None,
        batch_size: int = 32,
        timeout_s: int = 360,
    ):
        super().__init__(token_counter=token_counter, max_tokens=max_tokens)
        import os

        self.base_url = (
            base_url or os.getenv("VLLM_RERANKER_URL", "http://127.0.0.1:8011")
        ).rstrip("/")
        self.model = model
        self.batch_size = batch_size
        self.timeout_s = timeout_s

    def _rerank(
        self,
        query: str,
        documents: List[str],
        instruction: Optional[str] = None,
    ) -> List[RerankResult]:
        if not documents:
            return []
        if instruction is None:
            instruction = self.DEFAULT_INSTRUCTION

        text_1 = f"{self.PREFIX}<Instruct>: {instruction}\n<Query>: {query}\n"
        scores: List[float] = []
        for start in range(0, len(documents), self.batch_size):
            batch = documents[start : start + self.batch_size]
            payload = {
                "model": self.model,
                "text_1": text_1,
                "text_2": [f"<Document>: {doc}{self.SUFFIX}" for doc in batch],
                "truncate_prompt_tokens": -1,
            }
            last_error: Optional[Exception] = None
            for attempt in range(3):
                try:
                    response = requests.post(
                        f"{self.base_url}/score",
                        json=payload,
                        timeout=self.timeout_s,
                    )
                    response.raise_for_status()
                    data = response.json()["data"]
                    scores.extend(float(item["score"]) for item in data)
                    last_error = None
                    break
                except requests.exceptions.RequestException as exc:
                    last_error = exc
                    logger.warning(
                        "vllm_rerank_retry", attempt=attempt + 1, error=str(exc)
                    )
                    time.sleep(2**attempt)
            if last_error is not None:
                logger.error("vllm_rerank_failed", error=str(last_error))
                raise last_error

        results = [
            RerankResult(document=doc, score=score, original_index=idx)
            for idx, (doc, score) in enumerate(zip(documents, scores))
        ]
        results.sort(key=lambda x: x.score, reverse=True)
        return results


class ContextualReranker(Reranker):
    """Reranker implementation using Contextual AI's rerank API."""

    API_URL = "https://api.contextual.ai/v1/rerank"
    DEFAULT_MODEL = "ctxl-rerank-v2-instruct-multilingual"
    DEFAULT_INSTRUCTION = "Prioritize results that most closely align with the criteria outlined in the query"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        token_counter: Optional[Callable[[str], int]] = None,
        max_tokens: Optional[int] = None,
        top_n: Optional[int] = None,
        timeout_s: int = 60,
    ):
        """
        Initialize the Contextual AI reranker.

        Args:
            api_key: Optional API key. If not provided, uses config.
            model: Model to use for reranking. Defaults to ctxl-rerank-en-v1-instruct.
            token_counter: Optional callable that counts tokens in a string.
            max_tokens: Maximum total tokens for the output.
            top_n: Optional number of top results to return from the API.
            timeout_s: Timeout in seconds for API requests.
        """
        super().__init__(token_counter=token_counter, max_tokens=max_tokens)
        if api_key is None:
            config = get_config()
            api_key = config.contextual_api_key.get_secret_value()
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL
        self.top_n = top_n
        self.timeout_s = timeout_s

    def _rerank(
        self,
        query: str,
        documents: list[str],
        instruction: Optional[str] = None,
    ) -> list[RerankResult]:
        if not documents:
            return []

        payload: dict[str, str | list[str] | int] = {
            "query": query,
            "documents": documents,
            "model": self.model,
        }

        if self.top_n is not None:
            payload["top_n"] = self.top_n

        if instruction is not None:
            payload["instruction"] = instruction
        else:
            payload["instruction"] = self.DEFAULT_INSTRUCTION

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                self.API_URL,
                json=payload,
                headers=headers,
                timeout=self.timeout_s,
            )
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            logger.error("contextual_rerank_failed", error=str(e))
            raise

        # Parse response and build results
        results = []
        for item in data.get("results", []):
            idx = item["index"]
            score = item["relevance_score"]
            results.append(
                RerankResult(
                    document=documents[idx],
                    score=score,
                    original_index=idx,
                )
            )

        # Results should already be sorted by relevance, but ensure descending order
        results.sort(key=lambda x: x.score, reverse=True)
        return results


if __name__ == "__main__":
    import argparse
    import tiktoken

    parser = argparse.ArgumentParser(description="Run reranker example")
    parser.add_argument(
        "--reranker",
        choices=["baseten", "contextual"],
        default="baseten",
        help="Reranker to use (default: baseten)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=30,
        help="Maximum tokens for output (default: 30)",
    )
    args = parser.parse_args()

    logger.info(
        "Running reranker example", reranker=args.reranker, max_tokens=args.max_tokens
    )

    # Simple token counter just to demonstrate the concept, not accurate token for all models of course
    enc = tiktoken.get_encoding("o200k_harmony")
    token_counter = lambda text: len(enc.encode(text))

    # Create reranker based on argument
    reranker: Reranker
    if args.reranker == "contextual":
        reranker = ContextualReranker(
            token_counter=token_counter,
            max_tokens=args.max_tokens,
        )
    elif args.reranker == "baseten":
        reranker = BasetenReranker(
            token_counter=token_counter,
            max_tokens=args.max_tokens,
        )
    else:
        raise ValueError(f"Invalid reranker: {args.reranker}")

    query = "What is the capital of China?"
    documents = [
        "The capital of France is Paris.",
        "The capital of China is Beijing.",
        "The capital of Poland is Warsaw.",
        "The capital of Germany is Berlin.",
        "Chocolate is a delicious treat.",
        "Pizza is a food",
        "China has a population of 1.4 billion.",
        "Germany has a population of 83 million.",
        "Poland has a population of 38 million.",
        "Warsaw is the capital of Poland.",
        "Berlin is the capital of Germany.",
        "Paris is the capital of France.",
        "Beijing is the capital of China.",
        "Warsaw is the capital of Poland.",
        "Berlin is the capital of Germany.",
        "Shanghai is not the capital of China.",
        "Japan is closer to China than to the United States.",
        "The capital of China has been Beijing for a long time.",
    ]
    results = reranker(query, documents)
    logger.info("rerank_complete", num_results=len(results), max_tokens=args.max_tokens)
    for result in results:
        logger.info("result", score=result.score, document=result.document)

# Back-compat alias kept for callers of the original cosmos-retriever API.
VLLMReranker = VLLMQwen3Reranker
