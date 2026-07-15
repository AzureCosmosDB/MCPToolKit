"""Retrieval-layer benchmark for EnterpriseRAG-Bench.

Unlike ``bench_erag.py`` (which drives the full multi-turn agent and therefore
needs an inference backend), this benchmarks *only* the refactored retrieval
path: it issues a single ``search_corpus`` call per question and scores
recall@k of the returned chunk ids against the gold document ids. It exercises
the compiler -> executor -> normalization -> tool pipeline against the real
Cosmos container and real query embeddings, so it validates the schema-decoupling
refactor without requiring the agent model.

Usage::

    ACCOUNT_URI=... COSMOS_DATABASE=... COSMOS_CORPUS_CONTAINER=... \\
    CORPUS_REGISTRY_FILE=corpus_registry.json \\
    python scripts/bench_erag_retrieval.py --n 100 --k 50 --parallel 8 \\
        --container enterprise_ragbench_corpus --output runs/bench_erag_retrieval.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pyarrow.parquet as pq

from cosmos_retriever.config import RetrieverSettings, init_logging
from cosmos_retriever.tools import SearchCorpusTool, ToolSet

DATASET = Path(
    "/nvme/hf-cache/hub/datasets--onyx-dot-app--EnterpriseRAG-Bench/"
    "snapshots/69916e31c68aa5963c00248fd7f0bc12d04fd235/data/questions/test.parquet"
)


def load_dataset(n: int, seed: int) -> list[dict]:
    table = pq.read_table(DATASET, columns=["question_id", "question", "expected_doc_ids"])
    cols = table.to_pydict()
    rows = [
        {"query_id": qid, "query": q, "gold_docids": list(gold) if gold else []}
        for qid, q, gold in zip(
            cols["question_id"], cols["question"], cols["expected_doc_ids"], strict=True
        )
    ]
    random.Random(seed).shuffle(rows)
    return rows[:n]


def run_one(tool: SearchCorpusTool, row: dict) -> dict:
    qid, query = row["query_id"], row["query"]
    gold = set(row["gold_docids"])
    started = time.perf_counter()
    try:
        _, meta = tool({"query": query})
        elapsed = time.perf_counter() - started
        chunk_ids = list(meta.returned_chunk_ids) if meta else []
        retrieved_docids = {cid.split("__")[0] for cid in chunk_ids}
        hit = retrieved_docids & gold
        recall = len(hit) / len(gold) if gold else 0.0
        precision = len(hit) / len(retrieved_docids) if retrieved_docids else 0.0
        return {
            "query_id": qid,
            "query": query,
            "gold_docids": sorted(gold),
            "retrieved_chunk_ids": chunk_ids,
            "retrieved_docids": sorted(retrieved_docids),
            "recall": recall,
            "precision": precision,
            "n_returned": len(chunk_ids),
            "elapsed_s": round(elapsed, 3),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 — record failures so the bench keeps going
        return {
            "query_id": qid,
            "query": query,
            "gold_docids": sorted(gold),
            "retrieved_chunk_ids": [],
            "retrieved_docids": [],
            "recall": 0.0,
            "precision": 0.0,
            "n_returned": 0,
            "elapsed_s": round(time.perf_counter() - started, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--k", type=int, default=50, help="search + display limit (recall@k)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--parallel", type=int, default=8)
    ap.add_argument("--container", default="enterprise_ragbench_corpus")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    init_logging()
    settings = RetrieverSettings()
    corpus = settings.resolve_corpus(args.container)
    db = settings.build_cosmos_database(corpus)
    oai = settings.build_openai_client(corpus)
    toolset = ToolSet.build(
        cosmos_database=db,
        cosmos_container_name=corpus.container,
        openai_client=oai,
        openai_embedding_model=corpus.embed_model,
        embed_query_instruction=corpus.embed_query_instruction,
        search_limit=args.k,
        search_display_limit=args.k,
    )
    tool = toolset.get_tool("search_corpus")
    assert isinstance(tool, SearchCorpusTool)

    print(
        f"[bench] container={corpus.container} embed={corpus.embed_model} "
        f"n={args.n} k={args.k} parallel={args.parallel}",
        file=sys.stderr,
    )

    rows = load_dataset(args.n, args.seed)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = recall_sum = prec_sum = elapsed_sum = 0.0
    done = 0
    err = 0
    with out.open("w") as f, ThreadPoolExecutor(max_workers=args.parallel) as ex:
        futures = {ex.submit(run_one, tool, row): row for row in rows}
        for fut in as_completed(futures):
            rec = fut.result()
            f.write(json.dumps(rec) + "\n")
            f.flush()
            done += 1
            recall_sum += rec["recall"]
            prec_sum += rec["precision"]
            elapsed_sum += rec["elapsed_s"]
            err += 1 if rec["error"] else 0
            print(
                f"[bench] {done}/{len(rows)} qid={rec['query_id']} "
                f"recall={rec['recall']:.2f} prec={rec['precision']:.2f} "
                f"n={rec['n_returned']} t={rec['elapsed_s']}s "
                f"err={'Y' if rec['error'] else 'N'}",
                file=sys.stderr,
            )

    n = max(done, 1)
    print(
        f"[bench] DONE n={done} mean_recall@{args.k}={recall_sum / n:.3f} "
        f"mean_precision={prec_sum / n:.3f} mean_elapsed_s={elapsed_sum / n:.2f} "
        f"errors={err}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
