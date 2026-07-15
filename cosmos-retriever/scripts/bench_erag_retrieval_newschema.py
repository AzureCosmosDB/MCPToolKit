"""Retrieval-layer benchmark for EnterpriseRAG-Bench using an EXPLICIT schema.

This is identical in scoring to ``bench_erag_retrieval.py`` but it deliberately
does **not** use ``retrieval/legacy.py`` (no ``build_legacy_retriever`` /
``build_legacy_schema`` / ``legacy_capabilities_for``). Instead it constructs a
:class:`CorpusSchema` + :class:`RetrievalCapabilities` inline — exactly the way a
real custom-corpus integrator would — and hands the resulting
:class:`CorpusRetriever` to ``ToolSet.build(retriever=...)``.

It therefore validates that the *new* schema-driven pipeline
(planner -> strategy -> compiler -> executor -> normalizer) produces the same
recall as the legacy preset, driven purely by an externally-supplied schema.

Usage::

    ACCOUNT_URI=... COSMOS_DATABASE=... COSMOS_CORPUS_CONTAINER=... \\
    CORPUS_REGISTRY_FILE=corpus_registry.json \\
    python scripts/bench_erag_retrieval_newschema.py --n 100 --k 50 --parallel 8 \\
        --container enterprise_ragbench_corpus \\
        --output runs/bench_erag_retrieval_newschema.jsonl
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
from cosmos_retriever.retrieval import (
    CorpusRetriever,
    CorpusSchema,
    RetrievalCapabilities,
    SupportLevel,
    VectorCapability,
    VectorFieldConfig,
)
from cosmos_retriever.retrieval.embedding import QueryEmbedder
from cosmos_retriever.retrieval.models import PartitionQueryPolicy
from cosmos_retriever.retrieval.schema import LegacyDunderCodec
from cosmos_retriever.tools import SearchCorpusTool, ToolSet

DATASET = Path(
    "/nvme/hf-cache/hub/datasets--onyx-dot-app--EnterpriseRAG-Bench/"
    "snapshots/69916e31c68aa5963c00248fd7f0bc12d04fd235/data/questions/test.parquet"
)


def build_explicit_retriever(
    *, container, embedder: QueryEmbedder, embed_model: str, dimensions: int
) -> CorpusRetriever:
    """Construct a retriever from an inline schema — no ``legacy.py`` involved.

    This describes the EnterpriseRAG-Bench physical layout explicitly:
    id at ``/id``, text at ``/text``, embedding at ``/embedding``, parent doc at
    ``/docid`` (also the partition key), chunk order at ``/chunk_idx``, and the
    ``<docid>__<chunk_idx>`` chunk-id convention.
    """

    schema = CorpusSchema(
        item_id_path="/id",
        text_paths=["/text"],
        primary_text_path="/text",
        vector_fields=[
            VectorFieldConfig(
                path="/embedding",
                embedding_model=embed_model,
                dimensions=dimensions,
                distance_function="cosine",
            )
        ],
        document_id_path="/docid",
        chunk_id_path="/id",
        chunk_order_path="/chunk_idx",
        partition_key_paths=["/docid"],
    )
    # Chunk-id -> document-id codec (lives in schema.py, not legacy.py).
    schema.identity_codec = LegacyDunderCodec()

    capabilities = RetrievalCapabilities(
        vector_fields=[
            VectorCapability(
                path="/embedding",
                dimensions=dimensions,
                distance_function="cosine",
                support=SupportLevel.INDEXED,
            )
        ],
        full_text_paths=["/text"],
        partition_key_paths=["/docid"],
        native_hybrid_supported=True,
        full_text_supported=True,
        vector_supported=True,
        efficient_document_lookup_supported=True,
    )

    return CorpusRetriever(
        container=container,
        schema=schema,
        capabilities=capabilities,
        query_embedder=embedder,
        partition_policy=PartitionQueryPolicy(),
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
    container = db.get_container_client(corpus.container)

    embedder = QueryEmbedder(
        client=oai,
        model=corpus.embed_model,
        query_instruction=corpus.embed_query_instruction,
    )
    # Probe the true embedding dimensionality (qwen3-embed is not 1536-dim).
    dimensions = len(embedder.embed("dimension probe"))

    retriever = build_explicit_retriever(
        container=container,
        embedder=embedder,
        embed_model=corpus.embed_model,
        dimensions=dimensions,
    )
    toolset = ToolSet.build(
        retriever=retriever,
        search_limit=args.k,
        search_display_limit=args.k,
    )
    tool = toolset.get_tool("search_corpus")
    assert isinstance(tool, SearchCorpusTool)

    print(
        f"[bench] EXPLICIT-SCHEMA (no legacy.py) container={corpus.container} "
        f"embed={corpus.embed_model} dims={dimensions} "
        f"n={args.n} k={args.k} parallel={args.parallel}",
        file=sys.stderr,
    )

    rows = load_dataset(args.n, args.seed)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    recall_sum = prec_sum = elapsed_sum = 0.0
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
