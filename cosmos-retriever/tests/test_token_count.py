"""Token-count accuracy tests for the o200k_harmony counter.

The retrieval service budgets/truncates using ``CosmosRetriever._text_token_counter``,
a one-line wrapper over ``tiktoken.get_encoding("o200k_harmony").encode``. These
tests treat tiktoken's o200k_harmony as the ground-truth tokenizer for
gpt-oss/Harmony and o200k-family models and verify:

  * exactness of the real counter against the encoder,
  * cross-model agreement (o200k_harmony == o200k_base on real text) and the
    divergence from the older cl100k_base tokenizer,
  * accuracy of the crude ``len//4`` fallback estimate vs the real count,
  * edge behaviour (empty, whitespace, Unicode/CJK/emoji, determinism,
    monotonicity, sub-additivity, and special-token rejection).

Ground-truth counts are pinned for tiktoken 0.13.0.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
import tiktoken

from cosmos_retriever.retriever import CosmosRetriever

# ────────────────────────── encoders / real counter ───────────────────────

HARMONY = tiktoken.get_encoding("o200k_harmony")
O200K_BASE = tiktoken.get_encoding("o200k_base")
CL100K = tiktoken.get_encoding("cl100k_base")


def count(text: str) -> int:
    """Invoke the real CosmosRetriever._text_token_counter with a fake self."""
    fake = SimpleNamespace(_tiktoken=HARMONY)
    return CosmosRetriever._text_token_counter(fake, text)


# Pinned ground truth (tiktoken 0.13.0, o200k_harmony).
_ANCHORS = {
    "": 0,
    "hello": 1,
    "Hello, world!": 4,
    "The quick brown fox jumps over the lazy dog": 9,
    "café résumé naïve": 5,
    "I love 😀 pizza 🍕": 6,
    "机器学习很有趣": 5,
    "   \n\n\t  ": 2,
    "ha" * 100: 51,
}


# ═══════════════════════ encoding identity ════════════════════════════════


def test_harmony_encoding_name_and_superset_of_base() -> None:
    assert HARMONY.name == "o200k_harmony"
    # harmony is o200k_base plus Harmony special tokens -> strictly larger vocab
    assert HARMONY.n_vocab > O200K_BASE.n_vocab


# ═══════════════════════ counter exactness ════════════════════════════════


@pytest.mark.parametrize("text,expected", list(_ANCHORS.items()))
def test_counter_matches_pinned_ground_truth(text: str, expected: int) -> None:
    assert count(text) == expected


@pytest.mark.parametrize("text", list(_ANCHORS))
def test_counter_equals_encoder_length(text: str) -> None:
    assert count(text) == len(HARMONY.encode(text))


def test_counter_returns_nonnegative_int() -> None:
    for text in _ANCHORS:
        n = count(text)
        assert isinstance(n, int) and n >= 0


def test_empty_string_is_zero() -> None:
    assert count("") == 0


def test_counter_is_deterministic() -> None:
    text = "The quick brown fox jumps over the lazy dog"
    assert count(text) == count(text) == 9


def test_counter_is_monotonic_under_append() -> None:
    base = "the quick brown fox"
    assert count(base) <= count(base + " jumps over the lazy dog")


@pytest.mark.parametrize(
    "a,b",
    [
        ("hello", "world"),
        ("machine", "learning"),
        ("The quick brown", " fox jumps"),
        ("café", "résumé"),
    ],
)
def test_concatenation_is_subadditive(a: str, b: str) -> None:
    # BPE only re-merges at the boundary, never splits existing tokens.
    assert count(a + b) <= count(a) + count(b)


# ═══════════════════ cross-model agreement / divergence ═══════════════════


@pytest.mark.parametrize("text", list(_ANCHORS))
def test_harmony_equals_o200k_base_on_real_text(text: str) -> None:
    # For non-special text, harmony reduces to o200k_base -> identical counts.
    assert len(HARMONY.encode(text)) == len(O200K_BASE.encode(text))


@pytest.mark.parametrize("text", list(_ANCHORS))
def test_harmony_never_exceeds_cl100k(text: str) -> None:
    # The newer o200k tokenizer is at least as efficient as legacy cl100k.
    assert len(HARMONY.encode(text)) <= len(CL100K.encode(text))


@pytest.mark.parametrize("text", ["café résumé naïve", "I love 😀 pizza 🍕", "机器学习很有趣"])
def test_harmony_strictly_more_efficient_than_cl100k_on_non_ascii(text: str) -> None:
    assert len(HARMONY.encode(text)) < len(CL100K.encode(text))


def test_cjk_divergence_is_large() -> None:
    # 机器学习很有趣: harmony 5 vs cl100k 10 -> harmony halves the CJK cost.
    assert len(HARMONY.encode("机器学习很有趣")) == 5
    assert len(CL100K.encode("机器学习很有趣")) == 10


# ═══════════════════ crude len//4 estimate vs real count ══════════════════


def _crude(s: str) -> int:
    # Mirrors the agent_loop ContextTracker default fallback counter.
    return len(s) // 4


def test_crude_estimate_close_for_english_prose() -> None:
    prose = (
        "Retrieval augmented generation combines a search index with a language "
        "model so answers stay grounded in the underlying corpus documents."
    )
    real = count(prose)
    est = _crude(prose)
    # For English prose the char/4 heuristic stays within ~40% of the real count.
    assert 0.6 <= est / real <= 1.6


def test_crude_estimate_underestimates_dense_scripts() -> None:
    cjk = "机器学习很有趣"
    # len//4 = 1 but the real cost is 5 -> the char heuristic massively underestimates.
    assert _crude(cjk) < count(cjk)
    assert count(cjk) >= 3 * max(_crude(cjk), 1)


def test_real_count_beats_crude_as_accuracy_reference() -> None:
    # The tiktoken count equals o200k_base (exact for the target models); the crude
    # estimate does not — demonstrating why the service uses tiktoken, not len//4.
    for text in ("Hello, world!", "机器学习很有趣", "I love 😀 pizza 🍕"):
        assert count(text) == len(O200K_BASE.encode(text))
        # crude only coincidentally matches; assert it diverges on at least the CJK case
    assert _crude("机器学习很有趣") != count("机器学习很有趣")


# ═══════════════════════ special-token handling ═══════════════════════════


@pytest.mark.parametrize("marker", ["<|end|>", "<|start|>", "<|message|>", "<|return|>"])
def test_special_token_text_is_rejected(marker: str) -> None:
    # Default encode disallows special tokens; document text containing Harmony
    # markers would raise rather than silently mis-count.
    with pytest.raises(ValueError):
        count(marker)


def test_special_token_counts_as_single_when_explicitly_allowed() -> None:
    # Sanity check on the tokenizer itself: the marker is one special token.
    assert HARMONY.encode("<|end|>", allowed_special="all") == [200007]


# ═══════════════════════ scaling / whitespace ═════════════════════════════


def test_whitespace_and_newlines_are_counted() -> None:
    assert count("   \n\n\t  ") == 2


def test_repeated_token_scales_sublinearly_in_chars() -> None:
    text = "ha" * 100  # 200 chars
    n = count(text)
    assert n == 51  # far below 200 chars thanks to BPE merges
    assert n < len(text) // 2
