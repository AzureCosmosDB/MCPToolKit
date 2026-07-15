"""Run an N-question slice of EnterpriseRAG-Bench (ERAG) through the standalone
retriever, score recall@curated against gold docs, and save per-query records
as JSONL.

Mirrors ``bench_browsecomp.py`` but loads the ERAG questions parquet
(``question_id``, ``question``, ``expected_doc_ids``) instead of the BrowseComp
JSONL, and defaults to the ``enterprise_ragbench_corpus`` container.

Usage::

    python scripts/bench_erag.py \\
        --n 500 --seed 42 --parallel 4 \\
        --container enterprise_ragbench_corpus \\
        --output runs/bench_erag500.jsonl

Budget / turn knobs are read from the environment (COSMOS_RETRIEVER_MAX_TURNS,
COSMOS_RETRIEVER_THRESHOLD_BUDGET, COSMOS_RETRIEVER_TOKEN_BUDGET) via RetrieverSettings.

Records contain: query_id, query, gold_docids, retrieved_chunk_ids,
retrieved_docids (chunk_id.split('__')[0]), pool_docids, recall,
trajectory_recall, precision, num_turns, elapsed_s, usage, trajectory, error.

The ``usage`` field holds token counts for the run: prompt_tokens,
completion_tokens, reasoning_tokens (responses/reasoning models only),
total_tokens, and llm_calls (number of model round-trips).

The ``trajectory`` field holds the agent's step-by-step actions for the query:
the search queries it issued (``search_history``), the tool calls per turn
(``turn_tools``), the programmatic per-turn status summaries (``turn_summaries``),
and the final per-doc importance tags from curation (``curated_importance``).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pyarrow.parquet as pq

from cosmos_retriever.config import RetrieverSettings, init_logging
from cosmos_retriever.retriever import CosmosRetriever

DATASET = Path(
    "/nvme/hf-cache/hub/datasets--onyx-dot-app--EnterpriseRAG-Bench/"
    "snapshots/69916e31c68aa5963c00248fd7f0bc12d04fd235/data/questions/test.parquet"
)


def load_dataset(n: int, seed: int) -> list[dict]:
    table = pq.read_table(DATASET, columns=["question_id", "question", "expected_doc_ids"])
    cols = table.to_pydict()
    rows = [
        {
            "query_id": qid,
            "query": q,
            "gold_docids": list(gold) if gold else [],
        }
        for qid, q, gold in zip(
            cols["question_id"], cols["question"], cols["expected_doc_ids"], strict=True
        )
    ]
    rng = random.Random(seed)
    rng.shuffle(rows)
    return rows[:n]


def score(retrieved_chunk_ids: list[str], gold_docids: set[str]) -> tuple[float, float]:
    if not gold_docids:
        return 0.0, 0.0
    retrieved_docids = {cid.split("__")[0] for cid in retrieved_chunk_ids}
    hit = retrieved_docids & gold_docids
    recall = len(hit) / len(gold_docids)
    precision = len(hit) / len(retrieved_docids) if retrieved_docids else 0.0
    return recall, precision


def run_one(retriever: CosmosRetriever, row: dict, max_docs: int) -> dict:
    qid = row["query_id"]
    query = row["query"]
    gold_docids = set(row["gold_docids"])
    started = time.perf_counter()
    try:
        result = retriever.search(query=query, max_documents=max_docs)
        elapsed = time.perf_counter() - started
        retrieved = [d.id for d in result.documents]
        recall, precision = score(retrieved, gold_docids)
        # Trajectory recall: gold docs found anywhere in the agent's traversal
        # pool (every chunk seen), not just the final curated set.
        pool_docids = {d.split("__")[0] for d in result.pool_doc_ids}
        trajectory_recall = (
            len(pool_docids & gold_docids) / len(gold_docids) if gold_docids else 0.0
        )
        return {
            "query_id": qid,
            "query": query,
            "gold_docids": sorted(gold_docids),
            "retrieved_chunk_ids": retrieved,
            "retrieved_docids": sorted({c.split("__")[0] for c in retrieved}),
            "pool_docids": sorted(pool_docids),
            "num_curated": len(retrieved),
            "num_pool": len(pool_docids),
            "recall": recall,
            "trajectory_recall": trajectory_recall,
            "precision": precision,
            "num_turns": result.num_turns,
            "elapsed_s": round(elapsed, 2),
            "usage": getattr(result, "usage", {}) or {},
            "trajectory": result.trajectory,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 — record all failures so the bench keeps going
        return {
            "query_id": qid,
            "query": query,
            "gold_docids": sorted(gold_docids),
            "retrieved_chunk_ids": [],
            "retrieved_docids": [],
            "pool_docids": [],
            "num_curated": 0,
            "num_pool": 0,
            "recall": 0.0,
            "trajectory_recall": 0.0,
            "precision": 0.0,
            "num_turns": None,
            "elapsed_s": round(time.perf_counter() - started, 2),
            "usage": {},
            "trajectory": {},
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--container", default="enterprise_ragbench_corpus")
    ap.add_argument("--max-documents", type=int, default=20)
    ap.add_argument(
        "--backend",
        choices=["cosmos", "foundry"],
        default="cosmos",
        help="cosmos = CosmosRetriever (INFERENCE_BACKEND); "
        "foundry = FoundryHarnessAgent (generic model over the full 9-tool harness).",
    )
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    init_logging()
    settings = RetrieverSettings()
    print(
        f"[bench] reranker={'ON' if settings.vllm_reranker_url else 'OFF'} "
        f"backend={settings.inference_backend} chat_model={settings.chat_model} "
        f"container={args.container} n={args.n} "
        f"parallel={args.parallel} max_turns={settings.cosmos_retriever_max_turns} "
        f"threshold={settings.cosmos_retriever_threshold_budget} token={settings.cosmos_retriever_token_budget}",
        file=sys.stderr,
    )

    rows = load_dataset(args.n, args.seed)
    if args.backend == "foundry":
        from foundry_harness import FoundryHarnessAgent

        retriever = FoundryHarnessAgent(
            settings=settings,
            corpus_name=args.container,
            max_turns=settings.cosmos_retriever_max_turns,
        )
        print(
            f"[bench] backend=foundry model={retriever.model} "
            f"reasoning_effort={retriever.reasoning_effort} max_turns={retriever.max_turns}",
            file=sys.stderr,
        )
    else:
        retriever = CosmosRetriever(settings=settings, corpus_name=args.container)
        # Shared-quota endpoints 429 easily on the chat/responses backend, which
        # has no explicit backoff. Raise the OpenAI SDK's built-in retry budget
        # (it honors Retry-After + exponential backoff) so throttles are ridden
        # out instead of failing the query.
        if getattr(retriever, "_chat_client", None) is not None:
            try:
                retriever._chat_client = retriever._chat_client.with_options(max_retries=12)
            except Exception:
                pass

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = 0
    recall_sum = 0.0
    traj_recall_sum = 0.0
    err_count = 0
    elapsed_sum = 0.0
    total_tokens_sum = 0
    prompt_tokens_sum = 0
    completion_tokens_sum = 0
    reasoning_tokens_sum = 0
    with out.open("w") as f, ThreadPoolExecutor(max_workers=args.parallel) as ex:
        futures = {ex.submit(run_one, retriever, row, args.max_documents): row for row in rows}
        for fut in as_completed(futures):
            rec = fut.result()
            f.write(json.dumps(rec) + "\n")
            f.flush()
            done += 1
            recall_sum += rec["recall"]
            traj_recall_sum += rec["trajectory_recall"]
            elapsed_sum += rec["elapsed_s"]
            u = rec.get("usage") or {}
            total_tokens_sum += int(u.get("total_tokens", 0) or 0)
            prompt_tokens_sum += int(u.get("prompt_tokens", 0) or 0)
            completion_tokens_sum += int(u.get("completion_tokens", 0) or 0)
            reasoning_tokens_sum += int(u.get("reasoning_tokens", 0) or 0)
            if rec["error"]:
                err_count += 1
            print(
                f"[bench] {done}/{len(rows)} qid={rec['query_id']} "
                f"recall={rec['recall']:.2f} traj_recall={rec['trajectory_recall']:.2f} "
                f"n={rec['num_curated']} pool={rec.get('num_pool', 0)} "
                f"turns={rec['num_turns']} tok={u.get('total_tokens', 0)} "
                f"elapsed={rec['elapsed_s']}s "
                f"err={'Y' if rec['error'] else 'N'}",
                file=sys.stderr,
            )

    avg_recall = recall_sum / max(done, 1)
    avg_traj_recall = traj_recall_sum / max(done, 1)
    avg_elapsed = elapsed_sum / max(done, 1)
    avg_total_tokens = total_tokens_sum / max(done, 1)
    avg_prompt_tokens = prompt_tokens_sum / max(done, 1)
    avg_completion_tokens = completion_tokens_sum / max(done, 1)
    avg_reasoning_tokens = reasoning_tokens_sum / max(done, 1)
    print(
        f"[bench] DONE n={done} mean_recall={avg_recall:.3f} "
        f"mean_trajectory_recall={avg_traj_recall:.3f} errors={err_count}\n"
        f"[bench]   mean_elapsed_s={avg_elapsed:.1f} "
        f"mean_total_tokens={avg_total_tokens:.0f} "
        f"(prompt={avg_prompt_tokens:.0f} completion={avg_completion_tokens:.0f} "
        f"reasoning={avg_reasoning_tokens:.0f})\n"
        f"[bench]   sum_total_tokens={total_tokens_sum} "
        f"sum_prompt_tokens={prompt_tokens_sum} sum_completion_tokens={completion_tokens_sum} "
        f"sum_reasoning_tokens={reasoning_tokens_sum}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
