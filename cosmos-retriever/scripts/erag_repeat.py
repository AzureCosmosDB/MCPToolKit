"""Run agentic search 3x against ERAG and check whether gold doc surfaces."""

from __future__ import annotations

import json
import os
import subprocess
import sys

REPO = "/nvme/cosmos-retriever"
QUERY = (
    "What was the temporary mitigation applied to the internal load balancer "
    "serving the gen-infer VIPs around 03:40 UTC that immediately reduced TCP "
    "retransmits?"
)
GOLD = "dsid_fa2d9f0bda0e4d6b9174ae6b15f7b37e"

env = os.environ.copy()


def run_once(idx: int) -> None:
    cmd = [
        f"{REPO}/.venv/bin/python",
        "-m",
        "cosmos_retriever",
        "search",
        "--container",
        "enterprise_ragbench_corpus",
        "--query",
        QUERY,
        "--max-documents",
        "5",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)
    if proc.returncode != 0:
        print(f"run {idx}: subprocess exit={proc.returncode}", file=sys.stderr)
        print(proc.stderr[-2000:], file=sys.stderr)
        return
    data = json.loads(proc.stdout)
    ids = [d["id"].split("__")[0] for d in data["documents"]]
    print(
        f"run {idx}: turns={data['num_turns']:>2} "
        f"elapsed={data['elapsed_s']:>5.1f}s "
        f"gold_hit={GOLD in ids:>5} "
        f"ranked_ids={ids}"
    )


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    for i in range(1, n + 1):
        run_once(i)
