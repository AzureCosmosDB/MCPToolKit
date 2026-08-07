"""Run a compiled query against Cosmos DB and hand back the rows.

Once a search has been turned into SQL (for details on how that is done, refer to the compiler), 
this module is what actually sends it to Cosmos DB and collects the results. It is the last step 
before raw rows flow back into the retriever.

Running a query here comes with three safeguards. Transient failures are 
retried automatically with growing pauses between attempts, so a momentary hiccup 
doesn't sink a request. 

The number of queries allowed to run at the same time is capped, 
so a burst of searches can't overwhelm the account. 

the cap defaults to a sensible value 
and can be raised or lowered through an environment variable. And any query that takes
unusually long is logged, to make slow spots easy to spot.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

import structlog
import tenacity
from azure.cosmos import ContainerProxy
from azure.cosmos.exceptions import CosmosHttpResponseError

from cosmos_retriever.retrieval.models import CompiledCosmosQuery

logger = structlog.get_logger("cosmos_retriever.retrieval.executor")


def _read_positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("invalid_int_env", name=name, value=raw, default=default)
        return default
    if value < 1:
        logger.warning("invalid_positive_int_env", name=name, value=raw, default=default)
        return default
    return value


COSMOS_QUERY_MAX_CONCURRENCY = _read_positive_int_env("COSMOS_QUERY_MAX_CONCURRENCY", 8)
_COSMOS_QUERY_SEMAPHORE = threading.BoundedSemaphore(COSMOS_QUERY_MAX_CONCURRENCY)


def _is_retryable_cosmos_error(exc: BaseException) -> bool:
    if not isinstance(exc, CosmosHttpResponseError):
        return False
    status = getattr(exc, "status_code", None)
    return status in (408, 429, 449, 500, 502, 503, 504)


@tenacity.retry(
    stop=tenacity.stop_after_attempt(5),
    wait=tenacity.wait_exponential(multiplier=1, min=4, max=15),
    retry=tenacity.retry_if_exception(_is_retryable_cosmos_error),
    before_sleep=lambda retry_state: logger.warning(
        "retry_cosmos_query",
        attempt=retry_state.attempt_number,
        error=str(retry_state.outcome.exception()) if retry_state.outcome else None,
    ),
)
def _query_items(
    container: ContainerProxy,
    query: str,
    parameters: list[dict[str, Any]],
    *,
    partition_key: Any | None,
    enable_cross_partition_query: bool,
) -> list[dict[str, Any]]:
    start = time.perf_counter()
    with _COSMOS_QUERY_SEMAPHORE:
        kwargs: dict[str, Any] = {"query": query, "parameters": parameters}
        if partition_key is not None:
            kwargs["partition_key"] = partition_key
        elif enable_cross_partition_query:
            kwargs["enable_cross_partition_query"] = True
        result = list(container.query_items(**kwargs))
    elapsed_ms = (time.perf_counter() - start) * 1000
    if elapsed_ms > 4500:
        logger.warning(
            "slow_cosmos_query",
            elapsed_ms=round(elapsed_ms, 1),
            cosmos_max_concurrency=COSMOS_QUERY_MAX_CONCURRENCY,
        )
    return result


class CosmosExecutor:
    

    def __init__(self, container: ContainerProxy) -> None:
        self._container = container

    def run(self, compiled: CompiledCosmosQuery) -> list[dict[str, Any]]:
        return _query_items(
            self._container,
            compiled.sql,
            compiled.parameters,
            partition_key=compiled.partition_key,
            enable_cross_partition_query=compiled.enable_cross_partition_query,
        )
