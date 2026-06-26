#!/usr/bin/env python3
"""Generate SFT/RL query splits for all datasets.

Splits each dataset's train queries into:
  - SFT: 30% of train queries
  - RL:  70% of train queries

Output: JSON files per dataset with query_id lists for each split.

Usage:
    python -m datagen.generate_sft_rl_splits --output_dir datagen/splits
    python -m datagen.generate_sft_rl_splits --output_dir datagen/splits --datasets browsecompplus sec patents web
"""

import argparse
import json
import os
import sys

from cosmos_retriever.datagen.search_dataset import get_dataset


DATASETS = ["browsecompplus", "sec", "patents", "web"]


def generate_splits(dataset_name: str) -> dict:
    """Generate SFT/RL splits for a single dataset.
    
    Returns a dict with split info and query_id lists.
    """
    print(f"\n{'='*60}")
    print(f"Dataset: {dataset_name}")
    print(f"{'='*60}")
    
    ds = get_dataset(dataset_name)
    
    all_ids = ds.get_all_query_ids()
    train_ids = ds.get_train_query_ids()
    test_ids = ds.get_test_query_ids()
    sft_ids = ds.get_sft_query_ids()
    rl_ids = ds.get_rl_query_ids()
    
    # Verify no overlap
    sft_set = set(sft_ids)
    rl_set = set(rl_ids)
    train_set = set(train_ids)
    test_set = set(test_ids)
    
    assert sft_set & rl_set == set(), "SFT and RL sets overlap!"
    assert sft_set | rl_set == train_set, f"SFT + RL != train set! diff={train_set - (sft_set | rl_set)}"
    
    overlap = train_set & test_set
    if overlap:
        print(f"  WARNING: {len(overlap)} query IDs overlap between train and test (pre-split dataset artifact)")
        # For pre-split datasets, train/test may share IDs — this is expected
    
    print(f"  Total queries:  {len(all_ids)}")
    print(f"  Train queries:  {len(train_ids)} ({len(train_ids)/len(all_ids)*100:.1f}%)")
    print(f"  Test queries:   {len(test_ids)} ({len(test_ids)/len(all_ids)*100:.1f}%)")
    print(f"  ── SFT queries: {len(sft_ids)} ({len(sft_ids)/len(train_ids)*100:.1f}% of train, {len(sft_ids)/len(all_ids)*100:.1f}% of total)")
    print(f"  ── RL queries:  {len(rl_ids)} ({len(rl_ids)/len(train_ids)*100:.1f}% of train, {len(rl_ids)/len(all_ids)*100:.1f}% of total)")
    
    return {
        "dataset": dataset_name,
        "total_queries": len(all_ids),
        "train_queries": len(train_ids),
        "test_queries": len(test_ids),
        "sft_queries": len(sft_ids),
        "rl_queries": len(rl_ids),
        "sft_ratio": len(sft_ids) / len(train_ids) if train_ids else 0,
        "rl_ratio": len(rl_ids) / len(train_ids) if train_ids else 0,
        "sft_query_ids": sorted(sft_ids),
        "rl_query_ids": sorted(rl_ids),
        "test_query_ids": sorted(test_ids),
    }


def main():
    parser = argparse.ArgumentParser(description="Generate SFT/RL query splits")
    parser.add_argument(
        "--output_dir",
        type=str,
        default="datagen/splits",
        help="Output directory for split files (default: datagen/splits)",
    )
    parser.add_argument(
        "--datasets",
        nargs="+",
        default=DATASETS,
        help=f"Datasets to process (default: {' '.join(DATASETS)})",
    )
    args = parser.parse_args()
    
    os.makedirs(args.output_dir, exist_ok=True)
    
    summary = []
    
    for ds_name in args.datasets:
        try:
            split_info = generate_splits(ds_name)
            
            # Save per-dataset split file
            output_path = os.path.join(args.output_dir, f"{ds_name}_splits.json")
            with open(output_path, "w") as f:
                json.dump(split_info, f, indent=2)
            print(f"  Saved to: {output_path}")
            
            summary.append({
                "dataset": ds_name,
                "total": split_info["total_queries"],
                "train": split_info["train_queries"],
                "test": split_info["test_queries"],
                "sft": split_info["sft_queries"],
                "rl": split_info["rl_queries"],
            })
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    # Save summary
    summary_path = os.path.join(args.output_dir, "summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    
    # Print summary table
    print(f"\n{'='*60}")
    print("Summary")
    print(f"{'='*60}")
    print(f"{'Dataset':<18} {'Total':>6} {'Train':>6} {'Test':>6} {'SFT':>6} {'RL':>6}")
    print(f"{'-'*18} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*6}")
    for s in summary:
        print(f"{s['dataset']:<18} {s['total']:>6} {s['train']:>6} {s['test']:>6} {s['sft']:>6} {s['rl']:>6}")
    print(f"\nAll splits saved to: {args.output_dir}")


if __name__ == "__main__":
    main()

