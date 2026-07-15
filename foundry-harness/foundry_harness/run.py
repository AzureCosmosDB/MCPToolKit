"""CLI: run one query through the Foundry full-harness agent.

Usage (from a shell with the cosmos-retriever venv + env vars loaded):

    set -a; source /nvme/harness-1/.env.local; set +a
    export INFERENCE_BACKEND=openai_responses \
           CHAT_BASE_URL="$ANSWER_OPENAI_ENDPOINT" \
           CHAT_MODEL="$ANSWER_MODEL" \
           CHAT_API_KEY="$ANSWER_OPENAI_API_KEY" \
           CHAT_REASONING_EFFORT=medium
    unset CHAT_API_VERSION
    python -m foundry_harness.run "your question here" --max-turns 35

Requires ``cosmos_retriever`` to be importable (installed in the same venv).
"""

from __future__ import annotations

import argparse
import json
import sys

from foundry_harness.agent import FoundryHarnessAgent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Natural-language question to retrieve for.")
    parser.add_argument("--corpus", default=None, help="Corpus name (registry key).")
    parser.add_argument("--max-documents", type=int, default=20)
    parser.add_argument("--max-turns", type=int, default=35)
    parser.add_argument(
        "--reasoning-effort",
        default=None,
        choices=[None, "low", "medium", "high"],
        help="Override CHAT_REASONING_EFFORT for reasoning models.",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit the full result as JSON."
    )
    args = parser.parse_args(argv)

    agent = FoundryHarnessAgent(
        corpus_name=args.corpus,
        reasoning_effort=args.reasoning_effort,
        max_turns=args.max_turns,
    )
    result = agent.search(args.query, max_documents=args.max_documents)

    if args.json:
        print(
            json.dumps(
                {
                    "query": result.query,
                    "num_turns": result.num_turns,
                    "elapsed_s": result.elapsed_s,
                    "usage": result.usage,
                    "metadata": result.metadata,
                    "trajectory": result.trajectory,
                    "documents": [
                        {"id": d.id, "rank": d.rank, "justification": d.justification}
                        for d in result.documents
                    ],
                },
                indent=2,
            )
        )
        return 0

    print(f"query: {result.query}")
    print(
        f"turns={result.num_turns} elapsed={result.elapsed_s}s "
        f"tokens={result.usage.get('total_tokens')} "
        f"llm_calls={result.usage.get('llm_calls')} "
        f"curated={result.metadata.get('n_curated')} "
        f"pool={result.metadata.get('n_pool')}"
    )
    print(f"tools used: {result.metadata.get('tool_types_used')}")
    print("curated documents:")
    for d in result.documents:
        print(f"  [{d.rank}] {d.id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
