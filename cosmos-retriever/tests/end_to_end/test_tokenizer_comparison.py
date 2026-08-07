"""Cross-tokenizer drift on ENGLISH text: o200k_harmony (what the service counts
with) vs the real tokenizers of the models that actually run.

CosmosRetriever budgets every request with ``tiktoken.get_encoding("o200k_harmony")``
regardless of the configured inference model. These tests quantify how far that
estimate drifts from other model families' real tokenizers (Llama 3.1, Claude,
Gemini/Gemma, Qwen, Mistral, and older OpenAI encodings) on pure English prose,
using the actual ``_text_token_counter`` for the harmony side.

The corpus, tokenizer loaders, and harmony reference counts live in
``tokenizer_panel`` (run ``python tests/end_to_end/tokenizer_panel.py`` to regenerate the
numbers pinned below). English is the convergence case: modern BPE tokenizers
agree closely here, so the drift is small and the bounds are tight. Tokenizers
come from tiktoken (bundled), the local HF cache (Qwen, gpt-oss), and HF community
ports for the closed models (Claude/Gemini publish no tokenizer file). Anything
unavailable offline is skipped, never faked.

How to run.
1. Install tiktoken and tokenizers into the virtual environment.
2. Allow network access so the model tokenizers can download from Hugging Face, or prime the local cache first.
3. Run pytest on tests/end_to_end/test_tokenizer_comparison.py.

See tests/README.md for the full setup.
"""
from __future__ import annotations

import pytest

pytest.importorskip("tiktoken")
pytest.importorskip("tokenizers")

from tokenizer_panel import (  # noqa: E402
    HARMONY_PER_SAMPLE,
    HARMONY_TOTAL,
)
from tokenizer_panel import (
    hf_counts as _hf_counts,
)
from tokenizer_panel import (
    local_counts as _local_counts,
)
from tokenizer_panel import (
    tik_counts as _tik_counts,
)


def _require(counts):
    if counts is None:
        pytest.skip("tokenizer not available offline")
    return counts


def _total(counts) -> int:
    return sum(counts)


def _ratio(counts) -> float:
    return _total(counts) / HARMONY_TOTAL


# ═══════════════════════ anchor: harmony itself ═══════════════════════════


def test_harmony_canonical_counts_pinned() -> None:
    assert HARMONY_PER_SAMPLE == [20, 18, 23, 22]
    assert HARMONY_TOTAL == 83


# ═══════════════════════ exact-match family (o200k) ════════════════════════


def test_o200k_base_identical_to_harmony() -> None:
    # GPT-4o's tokenizer: harmony is o200k_base + special tokens -> identical on text.
    assert _tik_counts("o200k_base") == HARMONY_PER_SAMPLE


def test_gpt_oss_local_identical_to_harmony() -> None:
    counts = _require(_local_counts("models--openai--gpt-oss-20b"))
    assert counts == HARMONY_PER_SAMPLE


# ═══════════════════════ legacy OpenAI encodings ══════════════════════════


def test_cl100k_within_two_percent_on_english() -> None:
    # gpt-4 / gpt-3.5 / text-embedding-3: on clean English the gap is tiny.
    counts = _tik_counts("cl100k_base")
    assert counts is not None
    assert 1.0 <= _ratio(counts) <= 1.03
    assert all(c >= h for c, h in zip(counts, HARMONY_PER_SAMPLE, strict=True))


@pytest.mark.parametrize("name", ["p50k_base", "r50k_base"])
def test_legacy_gpt2_era_close_on_english(name: str) -> None:
    # Finding: the large legacy drift comes from CJK/whitespace, NOT English --
    # on clean English prose the gpt-2/codex encodings essentially tie harmony.
    counts = _tik_counts(name)
    assert counts is not None
    assert _ratio(counts) <= 1.03


# ═══════════════════════ real other-model tokenizers ══════════════════════


def test_llama3_drift() -> None:
    counts = _require(_hf_counts("NousResearch/Meta-Llama-3.1-8B-Instruct"))
    assert 1.02 <= _ratio(counts) <= 1.12  # ~6% more on English


def test_claude_drift() -> None:
    # Anthropic ships no public tokenizer; Xenova/claude-tokenizer is the port.
    counts = _require(_hf_counts("Xenova/claude-tokenizer"))
    assert 1.0 <= _ratio(counts) <= 1.10


def test_gemini_gemma_drift() -> None:
    # Gemini has no public tokenizer; Gemma is the open proxy.
    counts = _require(_hf_counts("Xenova/gemma-tokenizer"))
    assert 1.0 <= _ratio(counts) <= 1.10


def test_qwen3_local_drift() -> None:
    counts = _require(_local_counts("models--Qwen--Qwen3-8B"))
    assert 1.0 <= _ratio(counts) <= 1.06


def test_mistral_is_the_english_outlier() -> None:
    # Mistral's 32k-vocab tokenizer is the only common one that drifts materially
    # on English (~17% more tokens than harmony).
    counts = _require(_hf_counts("Xenova/mistral-tokenizer"))
    assert 1.08 <= _ratio(counts) <= 1.30


# ═══════════════════════ the actionable findings ══════════════════════════


def test_harmony_is_the_efficiency_floor_on_english() -> None:
    # No common tokenizer counts fewer tokens than harmony on English, so the
    # service's estimate is a lower bound: it never over-counts English budgets,
    # but under-counts (mildly) for every non-o200k model.
    panel = {
        "cl100k_base": _tik_counts("cl100k_base"),
        "llama3.1": _hf_counts("NousResearch/Meta-Llama-3.1-8B-Instruct"),
        "claude": _hf_counts("Xenova/claude-tokenizer"),
        "gemma": _hf_counts("Xenova/gemma-tokenizer"),
        "qwen3": _local_counts("models--Qwen--Qwen3-8B"),
        "mistral": _hf_counts("Xenova/mistral-tokenizer"),
    }
    available = {k: v for k, v in panel.items() if v is not None}
    if not available:
        pytest.skip("no comparison tokenizers available offline")
    for name, counts in available.items():
        assert _total(counts) >= HARMONY_TOTAL, f"{name} counted fewer than harmony"


def test_modern_models_all_within_ten_percent_on_english() -> None:
    # General closeness statement: every modern-model tokenizer lands within ~10%
    # of harmony on English (Mistral, the legacy-vocab outlier, is excluded).
    modern = {
        "cl100k_base": _tik_counts("cl100k_base"),
        "llama3.1": _hf_counts("NousResearch/Meta-Llama-3.1-8B-Instruct"),
        "claude": _hf_counts("Xenova/claude-tokenizer"),
        "gemma": _hf_counts("Xenova/gemma-tokenizer"),
        "qwen3": _local_counts("models--Qwen--Qwen3-8B"),
    }
    available = {k: v for k, v in modern.items() if v is not None}
    if not available:
        pytest.skip("no comparison tokenizers available offline")
    for name, counts in available.items():
        assert _ratio(counts) <= 1.10, f"{name} drifted more than 10% on English"
