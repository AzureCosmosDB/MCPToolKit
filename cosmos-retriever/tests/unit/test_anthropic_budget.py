from __future__ import annotations

import copy
from typing import Any

import cosmos_retriever.inference.agent_loop as agent_loop


class _FakeTool:
    def __init__(self, name: str, output: str) -> None:
        self._name = name
        self._output = output
        self.received: list[tuple[dict, Any]] = []

    def get_format(self, provider: Any) -> dict:
        return {"name": self._name}

    def __call__(self, args: dict, overrides: Any = None) -> tuple[str, None]:
        self.received.append((args, overrides))
        return self._output, None


class _FakeToolSet:
    def __init__(self, tools: dict[str, _FakeTool]) -> None:
        self.tools = tools

    def get_tool(self, name: str) -> _FakeTool | None:
        return self.tools.get(name)


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _install_fake_http(monkeypatch, scripted: list[dict]) -> list[dict]:
    """Patch requests.post to replay `scripted` responses; capture sent payloads."""
    captured: list[dict] = []
    seq = iter(scripted)

    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        captured.append(copy.deepcopy(json))
        return _FakeResponse(next(seq))

    monkeypatch.setattr(agent_loop.requests, "post", fake_post)
    return captured


def _tool_use(tid: str, name: str, **inp: Any) -> dict:
    return {"content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}


def _final(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def _toolset() -> _FakeToolSet:
    return _FakeToolSet(
        {
            "search_corpus": _FakeTool("search_corpus", "# DOCUMENT ID: doc1\nbody text"),
            "prune_chunks": _FakeTool("prune_chunks", "pruned"),
        }
    )


def test_anthropic_annotates_output_and_passes_budget_overrides(monkeypatch) -> None:
    ts = _toolset()
    captured = _install_fake_http(
        monkeypatch,
        [
            _tool_use("t1", "search_corpus", query="a"),
            _final("<Document id=doc1><Justification>j</Justification></Document>"),
        ],
    )

    result = agent_loop.run_anthropic_search(
        toolset=ts,  # type: ignore[arg-type]
        base_url="https://example/v1",
        api_key="k",
        model="claude",
        query="q",
        max_documents=5,
        max_turns=5,
        text_token_counter=len,
        threshold_budget=100_000,
        token_budget=200_000,
    )

    # The tool was invoked with a budget overrides dict (not the old bare tool(args)).
    args, overrides = ts.tools["search_corpus"].received[0]
    assert isinstance(overrides, dict) and "ignore_ids" in overrides

    # The observation returned to the model carries the budget annotation.
    turn2_msgs = captured[1]["messages"]
    tool_result = turn2_msgs[-1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert "[Token usage:" in tool_result["content"]

    assert [d.id for d in result.documents] == ["doc1"]
    assert result.timing["llm_s"] >= 0.0


def test_anthropic_rejects_non_prune_tools_when_over_budget(monkeypatch) -> None:
    ts = _FakeToolSet(
        {
            "search_corpus": _FakeTool("search_corpus", "X" * 5000),
            "prune_chunks": _FakeTool("prune_chunks", "pruned"),
        }
    )
    captured = _install_fake_http(
        monkeypatch,
        [
            _tool_use("t1", "search_corpus", query="a"),  # huge output blows the budget
            _tool_use("t2", "search_corpus", query="b"),  # must be rejected
            _final("<Document id=doc1></Document>"),
        ],
    )

    agent_loop.run_anthropic_search(
        toolset=ts,  # type: ignore[arg-type]
        base_url="https://example/v1",
        api_key="k",
        model="claude",
        query="q",
        max_documents=5,
        max_turns=5,
        text_token_counter=len,
        threshold_budget=1000,
        token_budget=2000,
    )

    # Second search_corpus was rejected before execution → tool called only once.
    assert len(ts.tools["search_corpus"].received) == 1

    # The rejection observation is what got sent back on the following turn.
    turn3_msgs = captured[2]["messages"]
    rejected = turn3_msgs[-1]["content"][0]
    assert rejected["type"] == "tool_result"
    assert "Token budget exceeded" in rejected["content"]
