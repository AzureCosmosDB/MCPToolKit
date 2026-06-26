"""Tests for the generic OpenAI-compatible chat backend.

These never touch a real model or Cosmos: a fake chat client returns scripted
responses and a stub tool returns canned search results, so we only exercise
the agent loop, tool dispatch, doc-text hydration, and final-answer parsing.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from cosmos_retriever.config import RetrieverSettings
from cosmos_retriever.inference.openai_chat import run_chat_search, run_responses_search
from cosmos_retriever.tools import SEARCH_CORPUS_SCHEMA, Tool, ToolCallMetadata, ToolSet


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------
class _StubSearchTool(Tool):
    """Returns one canned search hit formatted like the real SearchCorpusTool."""

    def __call__(
        self, params: dict[Any, Any], overrides: dict[Any, Any] | None = None
    ) -> tuple[str, ToolCallMetadata | None]:
        return (
            "\n# DOCUMENT ID: doc_1 (12 tokens) \nMarie Curie discovered radium in 1898.",
            None,
        )


def _toolset() -> ToolSet:
    ts = ToolSet()
    ts.add_tool(_StubSearchTool(tool_schema=SEARCH_CORPUS_SCHEMA))
    return ts


class _FakeFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, call_id: str, name: str, arguments: str) -> None:
        self.id = call_id
        self.type = "function"
        self.function = _FakeFunction(name, arguments)


class _FakeMessage:
    def __init__(self, content: str | None = None, tool_calls: list | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls


class FakeChatClient:
    """Mimics the subset of openai.OpenAI used by run_chat_search."""

    def __init__(self, scripted_messages: list[_FakeMessage]) -> None:
        self._scripted = list(scripted_messages)
        self.calls: list[dict] = []

    # client.chat.completions.create(...)
    @property
    def chat(self) -> FakeChatClient:
        return self

    @property
    def completions(self) -> FakeChatClient:
        return self

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        message = self._scripted.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


# --------------------------------------------------------------------------
# Chat agent tests
# --------------------------------------------------------------------------
def test_chat_search_executes_tool_then_parses_final_docs() -> None:
    client = FakeChatClient(
        [
            _FakeMessage(
                content="",
                tool_calls=[_FakeToolCall("call_1", "search_corpus", '{"query": "radium"}')],
            ),
            _FakeMessage(
                content=(
                    "<Document id=doc_1>\n"
                    "<Justification>States Curie discovered radium.</Justification>\n"
                    "</Document>"
                ),
                tool_calls=None,
            ),
        ]
    )

    result = run_chat_search(
        toolset=_toolset(),
        client=client,
        model="gpt-4o-foundry",
        query="Who discovered radium?",
        max_documents=5,
    )

    assert result.num_turns == 2
    assert len(result.documents) == 1
    doc = result.documents[0]
    assert doc.id == "doc_1"
    assert "Marie Curie discovered radium" in doc.text  # hydrated from the search result
    assert doc.justification == "States Curie discovered radium."
    assert doc.rank == 0
    assert result.metadata["backend"] == "openai_chat"
    assert result.metadata["tool_calls"] == 1
    # The model + tools were actually forwarded.
    assert client.calls[0]["model"] == "gpt-4o-foundry"
    assert any(t["function"]["name"] == "search_corpus" for t in client.calls[0]["tools"])


def test_chat_search_handles_immediate_final_answer() -> None:
    client = FakeChatClient(
        [_FakeMessage(content="<Document id=doc_9></Document>", tool_calls=None)]
    )
    result = run_chat_search(
        toolset=_toolset(), client=client, model="m", query="q", max_documents=3
    )
    assert result.num_turns == 1
    assert [d.id for d in result.documents] == ["doc_9"]


def test_chat_search_respects_max_turns_without_final() -> None:
    # Always returns a tool call → never a final answer; loop must stop at max_turns.
    looping = [
        _FakeMessage(
            content="thinking",
            tool_calls=[_FakeToolCall(f"c{i}", "search_corpus", "{}")],
        )
        for i in range(10)
    ]
    client = FakeChatClient(looping)
    result = run_chat_search(
        toolset=_toolset(), client=client, model="m", query="q", max_turns=3
    )
    assert result.num_turns == 3
    assert result.documents == []  # no <Document> blocks ever emitted


# --------------------------------------------------------------------------
# Config tests
# --------------------------------------------------------------------------
def test_use_chat_backend_flag() -> None:
    harmony = RetrieverSettings(inference_backend="harmony_vllm")  # type: ignore[call-arg]
    chat = RetrieverSettings(inference_backend="openai_chat")  # type: ignore[call-arg]
    assert harmony.use_chat_backend is False
    assert chat.use_chat_backend is True


def test_build_chat_client_requires_base_url_and_model() -> None:
    s = RetrieverSettings(inference_backend="openai_chat")  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="CHAT_BASE_URL"):
        s.build_chat_client()

    s2 = RetrieverSettings(inference_backend="openai_chat", chat_base_url="http://x/v1")  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="CHAT_MODEL"):
        s2.build_chat_client()


def test_build_chat_client_returns_openai_client() -> None:
    s = RetrieverSettings(  # type: ignore[call-arg]
        inference_backend="openai_chat",
        chat_base_url="http://foundry.example/v1",
        chat_model="gpt-4o",
        chat_api_key="secret-key",
    )
    client = s.build_chat_client()
    assert str(client.base_url).rstrip("/") == "http://foundry.example/v1"


# --------------------------------------------------------------------------
# Responses-API backend
# --------------------------------------------------------------------------
class _FakeFunctionCall:
    """A /responses ``function_call`` output item."""

    type = "function_call"

    def __init__(self, call_id: str, name: str, arguments: str) -> None:
        self.call_id = call_id
        self.name = name
        self.arguments = arguments


class _FakeResponse:
    def __init__(self, response_id: str, output: list, output_text: str = "") -> None:
        self.id = response_id
        self.output = output
        self.output_text = output_text


class FakeResponsesClient:
    """Mimics the subset of openai.OpenAI used by run_responses_search."""

    def __init__(self, scripted: list[_FakeResponse]) -> None:
        self._scripted = list(scripted)
        self.calls: list[dict] = []

    @property
    def responses(self) -> FakeResponsesClient:
        return self

    def create(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        return self._scripted.pop(0)


def test_responses_search_executes_tool_then_parses_final_docs() -> None:
    client = FakeResponsesClient(
        [
            _FakeResponse(
                "resp_1",
                output=[_FakeFunctionCall("call_1", "search_corpus", '{"query": "radium"}')],
            ),
            _FakeResponse(
                "resp_2",
                output=[],
                output_text=(
                    "<Document id=doc_1><Justification>Curie discovered radium.</Justification></Document>"
                ),
            ),
        ]
    )

    result = run_responses_search(
        toolset=_toolset(),
        client=client,
        model="gpt-5.4",
        query="Who discovered radium?",
        max_documents=5,
        reasoning_effort="low",
    )

    assert result.num_turns == 2
    assert [d.id for d in result.documents] == ["doc_1"]
    assert "Marie Curie discovered radium" in result.documents[0].text
    assert result.documents[0].justification == "Curie discovered radium."
    assert result.metadata["backend"] == "openai_responses"
    # First turn uses a plain-string input + flat function tool schema + reasoning.
    assert isinstance(client.calls[0]["input"], str)
    assert client.calls[0]["tools"][0]["name"] == "search_corpus"
    assert client.calls[0]["reasoning"] == {"effort": "low"}
    # Second turn continues via previous_response_id + function_call_output.
    assert client.calls[1]["previous_response_id"] == "resp_1"
    assert client.calls[1]["input"][0]["type"] == "function_call_output"


def test_responses_search_respects_max_turns() -> None:
    looping = [
        _FakeResponse(f"resp_{i}", output=[_FakeFunctionCall(f"c{i}", "search_corpus", "{}")])
        for i in range(10)
    ]
    client = FakeResponsesClient(looping)
    result = run_responses_search(
        toolset=_toolset(), client=client, model="gpt-5.4", query="q", max_turns=3
    )
    assert result.num_turns == 3
    assert result.documents == []
