"""Run an N-question slice of BrowseComp+ through the standalone retriever,
score recall@curated against gold docs, and save per-query records as JSONL.

Usage::

    # with reranker (default — VLLM_RERANKER_URL must be set in the env)
    python scripts/bench_browsecomp.py \\
        --n 83 --seed 42 --parallel 4 \\
        --container browsecomp_corpus_container \\
        --output runs/bench_bc83_rerank.jsonl

    # without reranker
    VLLM_RERANKER_URL= python scripts/bench_browsecomp.py \\
        --n 83 --seed 42 --parallel 4 \\
        --container browsecomp_corpus_container \\
        --output runs/bench_bc83_norerank.jsonl

Records contain: query_id, query, gold_docids, retrieved_chunk_ids,
retrieved_docids (chunk_id.split('__')[0]), recall, precision, num_turns,
elapsed_s, error.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from cosmos_retriever.config import RetrieverSettings, init_logging
from cosmos_retriever.retriever import CosmosRetriever

DATASET = Path("/nvme/harness-1/external/BrowseComp-Plus/data/browsecomp_plus_decrypted.jsonl")
QREL_GOLD = Path("/nvme/harness-1/external/BrowseComp-Plus/topics-qrels/qrel_golds.txt")
QREL_EVIDENCE = Path("/nvme/harness-1/external/BrowseComp-Plus/topics-qrels/qrel_evidence.txt")


def load_qrels(path: Path) -> dict[str, set[str]]:
    """TREC qrels: ``query_id Q0 doc_id relevance`` -> {qid: {docid, ...}}."""
    d: dict[str, set[str]] = defaultdict(set)
    if not path.exists():
        return d
    for line in path.open():
        parts = line.split()
        if len(parts) == 4:
            d[parts[0]].add(parts[2])
    return d


_GOLD = load_qrels(QREL_GOLD)
_EVIDENCE = load_qrels(QREL_EVIDENCE)
# Reference positives for "Recall" = gold ∪ evidence (search_dataset.py BrowseCompPlusDataset).
_UNION: dict[str, set[str]] = defaultdict(set)
for _q in set(_GOLD) | set(_EVIDENCE):
    _UNION[_q] = _GOLD.get(_q, set()) | _EVIDENCE.get(_q, set())


def load_dataset(n: int, seed: int) -> list[dict]:
    rows = [json.loads(l) for l in DATASET.open()]
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


def _recall(found: set[str], positives: set[str]) -> float:
    return len(found & positives) / len(positives) if positives else 0.0


def run_one(retriever: CosmosRetriever, row: dict, max_docs: int) -> dict:
    qid = row["query_id"]
    query = row["query"]
    gold_pos = _GOLD.get(str(qid), set())            # final-answer positives
    union_pos = _UNION.get(str(qid), set())          # reference "Recall" positives = gold ∪ evidence
    started = time.perf_counter()
    try:
        result = retriever.search(query=query, max_documents=max_docs)
        elapsed = time.perf_counter() - started
        curated_docids = {d.id.split("__")[0] for d in result.documents}
        pool_docids = set(result.pool_doc_ids)
        recall = _recall(curated_docids, union_pos)                  # Recall (curated set)
        trajectory_recall = _recall(pool_docids, union_pos)          # Trajectory Recall (pool)
        final_answer_recall = _recall(curated_docids, gold_pos)      # Final-Answer Recall (curated vs gold)
        precision = (
            len(curated_docids & union_pos) / len(curated_docids) if curated_docids else 0.0
        )
        return {
            "query_id": qid,
            "query": query,
            "union_pos": sorted(union_pos),
            "gold_pos": sorted(gold_pos),
            "curated_docids": sorted(curated_docids),
            "pool_docids": sorted(pool_docids),
            "num_curated": len(curated_docids),
            "n_pool": len(pool_docids),
            "recall": recall,
            "trajectory_recall": trajectory_recall,
            "final_answer_recall": final_answer_recall,
            "precision": precision,
            "num_turns": result.num_turns,
            "elapsed_s": round(elapsed, 2),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 — record all failures so the bench keeps going
        return {
            "query_id": qid,
            "query": query,
            "union_pos": sorted(union_pos),
            "gold_pos": sorted(gold_pos),
            "curated_docids": [],
            "pool_docids": [],
            "num_curated": 0,
            "n_pool": 0,
            "recall": 0.0,
            "trajectory_recall": 0.0,
            "final_answer_recall": 0.0,
            "precision": 0.0,
            "num_turns": None,
            "elapsed_s": round(time.perf_counter() - started, 2),
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=83)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--container", default="browsecomp_corpus_container")
    ap.add_argument("--max-documents", type=int, default=30)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    init_logging()
    settings = RetrieverSettings()
    print(
        f"[bench] reranker={'ON' if settings.vllm_reranker_url else 'OFF'} "
        f"vllm={settings.vllm_base_url} container={args.container} n={args.n} parallel={args.parallel}",
        file=sys.stderr,
    )

    rows = load_dataset(args.n, args.seed)
    retriever = CosmosRetriever(settings=settings, corpus_name=args.container)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = 0
    recall_sum = 0.0
    traj_sum = 0.0
    fa_sum = 0.0
    err_count = 0
    with out.open("w") as f, ThreadPoolExecutor(max_workers=args.parallel) as ex:
        futures = {ex.submit(run_one, retriever, row, args.max_documents): row for row in rows}
        for fut in as_completed(futures):
            rec = fut.result()
            f.write(json.dumps(rec) + "\n")
            f.flush()
            done += 1
            recall_sum += rec["recall"]
            traj_sum += rec["trajectory_recall"]
            fa_sum += rec["final_answer_recall"]
            if rec["error"]:
                err_count += 1
            print(
                f"[bench] {done}/{len(rows)} qid={rec['query_id']} "
                f"recall={rec['recall']:.2f} traj={rec['trajectory_recall']:.2f} fa={rec['final_answer_recall']:.2f} "
                f"n_cur={rec['num_curated']} n_pool={rec['n_pool']} "
                f"turns={rec['num_turns']} elapsed={rec['elapsed_s']}s "
                f"err={'Y' if rec['error'] else 'N'}",
                file=sys.stderr,
            )

    n = max(done, 1)
    print(
        f"[bench] DONE n={done}  Recall={recall_sum/n:.3f}  "
        f"Trajectory={traj_sum/n:.3f}  Final-Answer={fa_sum/n:.3f}  errors={err_count}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
