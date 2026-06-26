"""Unit tests for :mod:`cosmos_retriever.tools`."""

from __future__ import annotations

from cosmos_retriever.tools import (
    GREP_CORPUS_SCHEMA,
    PRUNE_CHUNKS_SCHEMA,
    SEARCH_CORPUS_SCHEMA,
    PruneChunksTool,
    ToolSet,
    UserTextTool,
    _fts_literal_args,
    _tokenize_for_fts,
)
from cosmos_retriever.utils import ProviderFormat


class TestStopwordTokenisation:
    def test_drops_stopwords_and_lowercases(self) -> None:
        assert _tokenize_for_fts("The quick brown FOX") == ["quick", "brown", "fox"]

    def test_dedupes_preserving_order(self) -> None:
        assert _tokenize_for_fts("alpha BETA alpha gamma beta") == ["alpha", "beta", "gamma"]

    def test_caps_at_30_terms(self) -> None:
        words = " ".join(f"word{i}" for i in range(50))
        terms = _tokenize_for_fts(words)
        assert len(terms) == 30
        assert terms[0] == "word0" and terms[-1] == "word29"

    def test_empty_after_stopwords_returns_empty(self) -> None:
        # Every token in this string is a stopword.
        assert _tokenize_for_fts("the and or but please") == []


class TestFtsLiteralArgs:
    def test_emits_quoted_csv(self) -> None:
        assert _fts_literal_args(["alpha", "beta"]) == '"alpha", "beta"'

    def test_escapes_quotes_and_backslashes(self) -> None:
        out = _fts_literal_args(['he said "hi"', "back\\slash"])
        assert out == '"he said \\"hi\\"", "back\\\\slash"'


class TestSchemaProviderFormat:
    def test_openai_format_contains_function_metadata(self) -> None:
        f = SEARCH_CORPUS_SCHEMA.to_provider_format(ProviderFormat.OPENAI)
        assert f["type"] == "function"
        assert f["name"] == "search_corpus"
        assert "query" in f["parameters"]["properties"]
        assert f["parameters"]["required"] == ["query"]

    def test_harmony_format_nests_function_object(self) -> None:
        f = GREP_CORPUS_SCHEMA.to_provider_format(ProviderFormat.OPENAI_HARMONY)
        assert f["type"] == "function"
        assert f["function"]["name"] == "grep_corpus"
        assert f["function"]["parameters"]["required"] == ["pattern"]


class TestToolSetBasics:
    def test_add_get_remove(self) -> None:
        ts = ToolSet()
        prune = PruneChunksTool()
        user = UserTextTool()
        ts.add_tool(prune)
        ts.add_tool(user)
        assert ts.get_tool("prune_chunks") is prune
        assert ts.get_tool("user_text") is user
        assert ts.get_tool("missing") is None
        ts.remove_tool("prune_chunks")
        assert ts.get_tool("prune_chunks") is None

    def test_duplicate_name_raises(self) -> None:
        ts = ToolSet()
        ts.add_tool(PruneChunksTool())
        try:
            ts.add_tool(PruneChunksTool())
        except ValueError as exc:
            assert "already exists" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("expected ValueError")


class TestPruneTool:
    def test_returns_pruned_string(self) -> None:
        tool = PruneChunksTool()
        out, metadata = tool({"chunk_ids": ["a", "b"]})
        assert out == "Pruned"
        assert metadata is None

    def test_rejects_missing_arg(self) -> None:
        tool = PruneChunksTool()
        try:
            tool({})
        except ValueError as exc:
            assert "Invalid params" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("expected ValueError")


def test_prune_chunks_schema_round_trip() -> None:
    f = PRUNE_CHUNKS_SCHEMA.to_provider_format(ProviderFormat.OPENAI)
    assert f["parameters"]["properties"]["chunk_ids"]["type"] == "array"
    assert f["parameters"]["required"] == ["chunk_ids"]
