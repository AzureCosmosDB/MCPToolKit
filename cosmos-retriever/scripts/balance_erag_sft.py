"""Select a class-balanced SFT subset from an ERAG trajectory pool.

Reads the raw pool produced by ``datagen_erag_sft.py`` (one JSON object per
query with ``meta.question_type`` and ``meta.recall``) and writes a balanced
training file so no single ``question_type`` dominates.

Per class it keeps up to ``--per-class`` examples, **preferring perfect-recall
trajectories** and filling any remaining quota with the highest-recall
non-perfect ones — capped at ``--nonperfect-frac`` of the class so non-perfect
trajectories stay a minority.

Usage::

    python scripts/balance_erag_sft.py --input runs/erag_sft_pool.jsonl \
        --per-class 40 --nonperfect-frac 0.4 --min-recall 0.5 \
        --output runs/erag_sft_balanced.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--per-class", type=int, default=40, help="Max examples kept per question_type.")
    ap.add_argument(
        "--nonperfect-frac",
        type=float,
        default=0.4,
        help="Max fraction of a class's kept examples that may be non-perfect recall.",
    )
    ap.add_argument("--min-recall", type=float, default=0.5, help="Ignore pool records below this recall.")
    ap.add_argument("--perfect-thresh", type=float, default=0.999, help="Recall >= this counts as perfect.")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    pool = [json.loads(l) for l in Path(args.input).open() if l.strip()]
    by_class: dict[str, list[dict]] = defaultdict(list)
    for r in pool:
        r["_recall"] = float((r.get("meta") or {}).get("recall", 0.0))
        by_class[(r.get("meta") or {}).get("question_type", "unknown")].append(r)

    rng = random.Random(args.seed)
    selected: list[dict] = []
    print(f"{'question_type':24s} {'avail':>5s} {'perf':>4s} {'kept':>4s} {'(nonperf)':>9s}", file=sys.stderr)
    for cls in sorted(by_class):
        recs = [r for r in by_class[cls] if r["_recall"] >= args.min_recall]
        perfect = [r for r in recs if r["_recall"] >= args.perfect_thresh]
        nonperf = [r for r in recs if r["_recall"] < args.perfect_thresh]
        rng.shuffle(perfect)
        nonperf.sort(key=lambda r: r["_recall"], reverse=True)

        cap = args.per_class
        keep = perfect[:cap]
        slots = cap - len(keep)
        max_nonperf = int(round(args.nonperfect_frac * cap))
        take_nonperf = nonperf[: min(slots, max_nonperf)]
        keep += take_nonperf
        selected.extend(keep)
        print(
            f"{cls:24s} {len(by_class[cls]):>5d} {len(perfect):>4d} {len(keep):>4d} {len(take_nonperf):>9d}",
            file=sys.stderr,
        )

    rng.shuffle(selected)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        for r in selected:
            r.pop("_recall", None)
            f.write(json.dumps(r) + "\n")
    print(f"\n[balance] wrote {len(selected)} examples across {len(by_class)} classes -> {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
