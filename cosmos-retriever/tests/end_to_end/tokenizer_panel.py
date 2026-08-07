"""Reproducible token-count panel for the o200k_harmony drift tests.

Single source of truth for ``test_tokenizer_comparison.py``: the English corpus,
the tokenizer loaders, and the harmony reference counts live here so the test's
pinned numbers can be regenerated on demand. Run it directly to print the table
used to derive/refresh those assertions::

    python tests/tokenizer_panel.py

The harmony side uses the real ``CosmosRetriever._text_token_counter``. Tokenizers
come from tiktoken (bundled), the local HF cache (Qwen, gpt-oss), and HF community
ports for the closed models (Claude/Gemini publish no tokenizer file — the Xenova
Claude port and the open Gemma tokenizer are the closest real artifacts). Any
tokenizer unavailable offline is reported as ``n/a`` and skipped by the tests.
"""
from __future__ import annotations

import glob
from types import SimpleNamespace

import tiktoken
from tokenizers import Tokenizer

from cosmos_retriever.retriever import CosmosRetriever

# ─────────────────────── canonical English corpus ─────────────────────────

CORPUS: list[str] = [
    "Retrieval augmented generation grounds a language model in the indexed corpus so its answers cite real source documents.",
    "The quarterly report shows revenue increased twelve percent while operating costs remained essentially flat year over year.",
    "To reset your password, open the settings page, click security, and follow the emailed verification link within one hour.",
    "She argued that the experiment, though elegant, failed to control for several confounding variables in the second cohort.",
]

_HARMONY = tiktoken.get_encoding("o200k_harmony")


def hcount(text: str) -> int:
    """Real service counter (CosmosRetriever._text_token_counter)."""
    return CosmosRetriever._text_token_counter(SimpleNamespace(_tiktoken=_HARMONY), text)


HARMONY_PER_SAMPLE: list[int] = [hcount(s) for s in CORPUS]
HARMONY_TOTAL: int = sum(HARMONY_PER_SAMPLE)


# ─────────────────────────── tokenizer loaders ────────────────────────────


def tik_counts(name: str) -> list[int] | None:
    try:
        enc = tiktoken.get_encoding(name)
    except Exception:
        return None
    return [len(enc.encode(s)) for s in CORPUS]


def hf_counts(repo: str) -> list[int] | None:
    """Load a tokenizer.json from HF (cache first, then network); None if unavailable."""
    try:
        from huggingface_hub import hf_hub_download
    except Exception:
        return None
    path = None
    for kwargs in ({"local_files_only": True}, {}):
        try:
            path = hf_hub_download(repo_id=repo, filename="tokenizer.json", **kwargs)
            break
        except Exception:
            continue
    if path is None:
        return None
    tok = Tokenizer.from_file(path)
    return [len(tok.encode(s).ids) for s in CORPUS]


def local_counts(model_dir: str) -> list[int] | None:
    hits = glob.glob(f"/nvme/hf-cache/hub/{model_dir}/snapshots/*/tokenizer.json")
    if not hits:
        return None
    tok = Tokenizer.from_file(hits[0])
    return [len(tok.encode(s).ids) for s in CORPUS]


# Ordered panel: label -> zero-arg loader. Keep in sync with the test assertions.
PANEL: dict[str, object] = {
    "o200k_base (gpt-4o)": lambda: tik_counts("o200k_base"),
    "gpt-oss (harmony)": lambda: local_counts("models--openai--gpt-oss-20b"),
    "cl100k (gpt-4/3.5)": lambda: tik_counts("cl100k_base"),
    "p50k (codex)": lambda: tik_counts("p50k_base"),
    "r50k (gpt-2)": lambda: tik_counts("r50k_base"),
    "qwen3": lambda: local_counts("models--Qwen--Qwen3-8B"),
    "llama3.1": lambda: hf_counts("NousResearch/Meta-Llama-3.1-8B-Instruct"),
    "claude (xenova)": lambda: hf_counts("Xenova/claude-tokenizer"),
    "gemma (gemini proxy)": lambda: hf_counts("Xenova/gemma-tokenizer"),
    "mistral": lambda: hf_counts("Xenova/mistral-tokenizer"),
}


def build_report() -> list[tuple[str, list[int] | None, int | None, float | None]]:
    rows: list[tuple[str, list[int] | None, int | None, float | None]] = []
    for label, loader in PANEL.items():
        counts = loader()  # type: ignore[operator]
        if counts is None:
            rows.append((label, None, None, None))
        else:
            total = sum(counts)
            rows.append((label, counts, total, total / HARMONY_TOTAL))
    return rows


def main() -> None:
    print(f"corpus: {len(CORPUS)} English samples")
    print(f"harmony per-sample = {HARMONY_PER_SAMPLE}  total = {HARMONY_TOTAL}\n")
    print(f"{'tokenizer':24} {'total':>6} {'ratio':>7}  per-sample")
    print(f"{'o200k_harmony (service)':24} {HARMONY_TOTAL:>6} {1.0:>7.3f}  {HARMONY_PER_SAMPLE}")
    for label, counts, total, ratio in build_report():
        if counts is None:
            print(f"{label:24} {'n/a':>6} {'n/a':>7}")
        else:
            print(f"{label:24} {total:>6} {ratio:>7.3f}  {counts}")


if __name__ == "__main__":
    main()
