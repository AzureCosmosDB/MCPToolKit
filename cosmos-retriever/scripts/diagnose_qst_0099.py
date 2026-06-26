"""Diagnose where the gold doc loses rank for qst_0099 in the ERAG corpus."""

from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("CORPUS_REGISTRY_FILE", "/nvme/cosmos-retriever/corpus_registry.json")

from cosmos_retriever.config import get_settings  # noqa: E402

QUERY = (
    "What was the temporary mitigation applied to the internal load balancer "
    "serving the gen-infer VIPs around 03:40 UTC that immediately reduced TCP "
    "retransmits?"
)
GOLD = "dsid_fa2d9f0bda0e4d6b9174ae6b15f7b37e"


def with_retry(label, fn, attempts=4):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            wait = 2**i
            print(
                f"  [{label}] attempt {i + 1} failed: {type(e).__name__}: {str(e)[:120]} — retry in {wait}s"
            )
            time.sleep(wait)
    raise last  # type: ignore[misc]


def main() -> int:
    settings = get_settings()
    corpus = settings.resolve_corpus("enterprise_ragbench_corpus")
    print("=== corpus ===")
    print(f"  account_uri = {corpus.account_uri}")
    print(f"  database    = {corpus.database}")
    print(f"  container   = {corpus.container}")
    print(f"  embed_model = {corpus.embed_model}  url={corpus.embed_base_url}")
    print()

    db = settings.build_cosmos_database(corpus)
    container = db.get_container_client(corpus.container)
    oc = settings.build_openai_client(corpus)

    print("=== 1. gold-doc presence (partition-key lookup) ===")
    rows = with_retry(
        "presence",
        lambda: list(
            container.query_items(
                query="SELECT TOP 5 c.id, c.docid, c.chunk_idx FROM c WHERE c.docid = @d",
                parameters=[{"name": "@d", "value": GOLD}],
                partition_key=GOLD,
            )
        ),
    )
    print(f"  {len(rows)} chunks for {GOLD}:")
    for r in rows:
        print(f"    id={r['id']}  chunk_idx={r['chunk_idx']}")
    if not rows:
        print("  FATAL: gold doc not in container.")
        return 1
    print()

    from cosmos_retriever.tools import _fts_literal_args, _query_with_retry, _tokenize_for_fts

    emb_text = QUERY
    if corpus.embed_query_instruction:
        emb_text = f"Instruct: {corpus.embed_query_instruction}\nQuery: {QUERY}"
    emb = with_retry(
        "embed",
        lambda: oc.embeddings.create(model=corpus.embed_model, input=[emb_text]).data[0].embedding,
    )
    print(f"=== 2. RRF top-50 (no rerank) — embed_dim={len(emb)} ===")
    terms = _tokenize_for_fts(QUERY) or [QUERY]
    sql = (
        "SELECT TOP @k c.id, c.docid, c.chunk_idx FROM c\n"
        "ORDER BY RANK RRF("
        "VectorDistance(c.embedding, @qVec), "
        f"FullTextScore(c.text, {_fts_literal_args(terms)})"
        ")"
    )
    rrf_rows = with_retry(
        "rrf",
        lambda: _query_with_retry(
            container,
            sql,
            [{"name": "@k", "value": 50}, {"name": "@qVec", "value": emb}],
        ),
    )
    gold_rank = None
    for rank, r in enumerate(rrf_rows, 1):
        if r["docid"] == GOLD:
            gold_rank = rank
            break
    print(f"  pool size = {len(rrf_rows)}  gold_rank = {gold_rank}")
    print("  top-10 ids:")
    for rank, r in enumerate(rrf_rows[:10], 1):
        marker = "  GOLD ✓" if r["docid"] == GOLD else ""
        print(f"    rank={rank:>2}  {r['id']}{marker}")
    print()

    if gold_rank is None:
        print("Gold doc not in top-50. Retrieval itself is missing it.")
        return 0

    if not settings.vllm_reranker_url:
        print("=== 3. (no VLLM_RERANKER_URL set, skipping rerank check) ===")
        return 0

    from cosmos_retriever.rerank import VLLMReranker

    reranker = VLLMReranker(base_url=settings.vllm_reranker_url)
    print("=== 3. Qwen3-Reranker reordering of those 50 ===")

    docs: list[str] = []
    for r in rrf_rows:
        text_rows = with_retry(
            f"fetch_{r['id']}",
            lambda r=r: list(
                container.query_items(
                    query="SELECT TOP 1 c.text FROM c WHERE c.id = @i",
                    parameters=[{"name": "@i", "value": r["id"]}],
                    partition_key=r["docid"],
                )
            ),
            attempts=3,
        )
        docs.append(text_rows[0]["text"] if text_rows else "")

    reranked = reranker(QUERY, docs)
    new_gold_rank = None
    for new_rank, rr in enumerate(reranked, 1):
        if rrf_rows[rr.original_index]["docid"] == GOLD:
            new_gold_rank = new_rank
            print(
                f"  rerank position = {new_rank} (was {gold_rank})  score={rr.score:.4f}  GOLD ✓"
            )
            break
    print("  top-5 after rerank:")
    for new_rank, rr in enumerate(reranked[:5], 1):
        rid = rrf_rows[rr.original_index]["id"]
        marker = "  GOLD ✓" if rrf_rows[rr.original_index]["docid"] == GOLD else ""
        print(f"    rank={new_rank:>2}  score={rr.score:.4f}  {rid}{marker}")
    if new_gold_rank is None:
        print("  GOLD ABSENT in reranked list — reranker scored other docs higher.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
