"""Generate an SFT dataset of full 4-tool agent trajectories on ERAG-Bench.

Re-runs the four-tool retrieval agent (the same Cosmos toolset used by
``run_responses_search``) over Enterprise RAG-Bench queries and records the
*complete* turn-by-turn transcript as OpenAI chat-completions ``messages``
(system, user, assistant-with-tool_calls, tool-outputs, final assistant) plus
the tool schemas — the format TRL's ``SFTTrainer`` consumes via a chat template.

Quality controls:
  * best-of-N sampling per query (keep the highest-recall episode),
  * rejection on recall (``--min-recall``; default keep only perfect recall),
  * observation truncation (``--obs-max-chars``) to bound sequence length,
  * skips no-gold classes (info_not_found / high_level) unless ``--keep-no-gold``.

Each output line: {"messages": [...], "tools": [...], "meta": {...}}.

Usage::

    set -a; source /nvme/harness-1/.env.local; set +a
    export INFERENCE_BACKEND=openai_responses \
           CHAT_BASE_URL="https://ng-9364-resource.openai.azure.com/openai/v1" \
           CHAT_MODEL=gpt-5.4 CHAT_API_KEY=... CHAT_REASONING_EFFORT=medium \
           VLLM_RERANKER_URL=http://172.17.0.2:8011 \
           CORPUS_REGISTRY_FILE="$PWD/corpus_registry.json"
    unset CHAT_API_VERSION
    .venv/bin/python scripts/datagen_erag_sft.py --n 500 --parallel 3 \
        --best-of 2 --min-recall 1.0 --output runs/erag_sft.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from cosmos_retriever.config import RetrieverSettings, init_logging
from cosmos_retriever.inference import openai_chat as oc
from cosmos_retriever.prompts import get_retrieval_subagent_prompt
from cosmos_retriever.retriever import CosmosRetriever
from cosmos_retriever.utils import ProviderFormat

DATASET = (
    "/nvme/hf-cache/hub/datasets--onyx-dot-app--EnterpriseRAG-Bench/snapshots/"
    "69916e31c68aa5963c00248fd7f0bc12d04fd235/data/questions/test.parquet"
)

_USER_INSTRUCTION = (
    "Use the available tools to search the corpus, then return ONLY the ranked "
    "<Document id=...> blocks (each with a <Justification>) for the most relevant "
    "documents. Do not answer the question yourself."
)


def load_dataset(n: int, seed: int) -> list[dict]:
    df = pd.read_parquet(DATASET)
    rows = [
        {
            "query_id": str(r.question_id),
            "query": str(r.question),
            "gold": {str(x) for x in list(r.expected_doc_ids)}
            if r.expected_doc_ids is not None
            else set(),
            "question_type": str(r.question_type),
        }
        for r in df.itertuples()
    ]
    rows.sort(key=lambda x: x["query_id"])
    import random

    random.Random(seed).shuffle(rows)
    return rows[:n]


def _curated_docids(final_text: str) -> set[str]:
    ids: set[str] = set()
    for m in oc._FINAL_DOC_RE.finditer(final_text):
        ids.add(m.group("id").split("__")[0])
    return ids


def run_episode(
    retriever: CosmosRetriever,
    query: str,
    *,
    max_documents: int,
    max_turns: int,
    max_tokens: int,
    reasoning_effort: str | None,
    obs_max_chars: int,
) -> dict:
    """One /responses episode; returns chat-format messages + curated docids."""

    toolset = retriever.toolset
    client = retriever._chat_client
    model = retriever._chat_model

    tool_specs = [t.get_format(ProviderFormat.OPENAI) for t in toolset.tools.values()]
    system_prompt = get_retrieval_subagent_prompt(query, num_output_docs=max_documents)
    prompt = system_prompt + "\n\n" + _USER_INSTRUCTION

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": _USER_INSTRUCTION},
    ]
    common: dict = {"model": model, "tools": tool_specs, "max_output_tokens": max_tokens}
    if reasoning_effort:
        common["reasoning"] = {"effort": reasoning_effort}

    response = client.responses.create(input=prompt, **common)
    num_turns = 1
    final_text = ""

    while True:
        function_calls = [
            o for o in response.output if getattr(o, "type", None) == "function_call"
        ]
        if not function_calls:
            final_text = getattr(response, "output_text", "") or ""
            break
        if num_turns >= max_turns:
            final_text = getattr(response, "output_text", "") or ""
            break

        # Assistant turn: the tool calls it issued.
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": fc.call_id,
                        "type": "function",
                        "function": {"name": fc.name, "arguments": fc.arguments or "{}"},
                    }
                    for fc in function_calls
                ],
            }
        )

        outputs: list[dict] = []
        for fc in function_calls:
            args = oc._parse_tool_arguments(fc.arguments)
            tool = toolset.get_tool(fc.name)
            if tool is None:
                out = f"Error: unknown tool '{fc.name}'."
            else:
                try:
                    out, _meta = tool(args)
                except Exception as exc:  # noqa: BLE001
                    out = f"Error executing '{fc.name}': {exc}"
            if obs_max_chars and len(out) > obs_max_chars:
                out = out[:obs_max_chars] + "\n...[truncated]"
            outputs.append({"type": "function_call_output", "call_id": fc.call_id, "output": out})
            messages.append(
                {"role": "tool", "tool_call_id": fc.call_id, "name": fc.name, "content": out}
            )

        response = client.responses.create(
            previous_response_id=response.id, input=outputs, **common
        )
        num_turns += 1

    messages.append({"role": "assistant", "content": final_text})
    return {
        "messages": messages,
        "curated": _curated_docids(final_text),
        "num_turns": num_turns,
    }


def process_query(retriever, row, args) -> dict | None:
    gold = row["gold"]
    if not gold and not args.keep_no_gold:
        return None  # info_not_found / high_level: nothing to reward on

    best = None
    best_recall = -1.0
    started = time.perf_counter()
    for _ in range(args.best_of):
        try:
            ep = run_episode(
                retriever,
                row["query"],
                max_documents=args.max_documents,
                max_turns=args.max_turns,
                max_tokens=args.max_tokens,
                reasoning_effort=retriever.settings.chat_reasoning_effort,
                obs_max_chars=args.obs_max_chars,
            )
        except Exception as exc:  # noqa: BLE001 — skip failed samples
            print(f"[datagen] {row['query_id']} episode error: {exc}", file=sys.stderr)
            continue
        if gold:
            recall = len(ep["curated"] & gold) / len(gold)
        else:
            # No-gold class (info_not_found / high_level): correct behaviour is
            # to abstain — reward an empty curated set, penalise hallucinated docs.
            recall = 1.0 if not ep["curated"] else 0.0
        if recall > best_recall:
            best_recall, best = recall, ep

    if best is None or best_recall < args.min_recall:
        return {"_rejected": True, "query_id": row["query_id"], "recall": best_recall}

    return {
        "messages": best["messages"],
        "tools": [t.get_format(ProviderFormat.OPENAI_HARMONY) for t in retriever.toolset.tools.values()],
        "meta": {
            "query_id": row["query_id"],
            "question_type": row["question_type"],
            "recall": round(best_recall, 3),
            "num_turns": best["num_turns"],
            "num_gold": len(gold),
            "elapsed_s": round(time.perf_counter() - started, 2),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--parallel", type=int, default=3)
    ap.add_argument("--container", default="enterprise_ragbench_corpus")
    ap.add_argument("--max-documents", type=int, default=20)
    ap.add_argument("--max-turns", type=int, default=35)
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--best-of", type=int, default=1, help="Samples per query; keep the best.")
    ap.add_argument("--min-recall", type=float, default=1.0, help="Reject episodes below this recall.")
    ap.add_argument("--obs-max-chars", type=int, default=4000, help="Truncate each tool output.")
    ap.add_argument("--keep-no-gold", action="store_true", help="Keep info_not_found/high_level queries.")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    init_logging()
    settings = RetrieverSettings()
    if not settings.use_generic_llm_backend:
        print("[datagen] set INFERENCE_BACKEND=openai_responses (or openai_chat).", file=sys.stderr)
        return 2

    rows = load_dataset(args.n, args.seed)
    retriever = CosmosRetriever(settings=settings, corpus_name=args.container)
    if getattr(retriever, "_chat_client", None) is not None:
        try:
            retriever._chat_client = retriever._chat_client.with_options(max_retries=12)
        except Exception:
            pass

    print(
        f"[datagen] n={len(rows)} parallel={args.parallel} best_of={args.best_of} "
        f"min_recall={args.min_recall} obs_max_chars={args.obs_max_chars} model={retriever._chat_model}",
        file=sys.stderr,
    )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    kept = rejected = skipped = done = 0
    with out.open("w") as f, ThreadPoolExecutor(max_workers=args.parallel) as ex:
        futs = {ex.submit(process_query, retriever, r, args): r for r in rows}
        for fut in as_completed(futs):
            done += 1
            rec = fut.result()
            if rec is None:
                skipped += 1
            elif rec.get("_rejected"):
                rejected += 1
                print(
                    f"[datagen] {done}/{len(rows)} REJECT {rec['query_id']} recall={rec['recall']:.2f}",
                    file=sys.stderr,
                )
            else:
                f.write(json.dumps(rec) + "\n")
                f.flush()
                kept += 1
                print(
                    f"[datagen] {done}/{len(rows)} KEEP {rec['meta']['query_id']} "
                    f"recall={rec['meta']['recall']:.2f} turns={rec['meta']['num_turns']} "
                    f"type={rec['meta']['question_type']}",
                    file=sys.stderr,
                )

    print(
        f"[datagen] DONE kept={kept} rejected={rejected} skipped_no_gold={skipped} -> {out}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
