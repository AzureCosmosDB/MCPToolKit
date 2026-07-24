"""Comprehensive tests for the ported token-budget system.

Covers, against the REAL agent loops (with a scripted fake LLM client + fake
tools), every feature ported from upstream harness/agent.py:

  1. Real pruning        (prune_chunks_from_trajectory parity)
  2. Cross-turn dedup    (DeduplicatingPruningSearchAgent parity)
  3. Spillage/rejection  (rejection_budget cutoff)
  4. Tool-output clamping (max_tokens override when budget tight)
  5. Token budgeting     (threshold -> prune/conclude + tool restriction, marker)

The token counter used throughout counts occurrences of the sentinel "TOK",
so budgets are fully deterministic and independent of the (large) system prompt.
"""
from __future__ import annotations

import json
import types

import pytest

from cosmos_retriever.inference.agent_loop import (
    _BudgetController,
    _remove_chunks_from_text,
    run_chat_search,
    run_responses_search,
)

TOK = "TOK"  # sentinel word the fake counter counts


def counter(s: str) -> int:
    return s.count(TOK) if isinstance(s, str) else 0


# ───────────────────────── fakes ─────────────────────────

class _Schema:
    def __init__(self, name):
        self.name = name


class FakeMeta:
    def __init__(self, returned_chunk_ids=None):
        self.returned_chunk_ids = list(returned_chunk_ids or [])
        self.retrieval_s = 0.0
        self.rerank_s = 0.0


class FakeTool:
    """Records (params, overrides) per call; returns scripted outputs."""

    def __init__(self, name, outputs=None, returned_chunk_ids=None):
        self.tool_schema = _Schema(name)
        self._outputs = list(outputs or [])
        self._rcids = returned_chunk_ids
        self.calls = []  # list of (params, overrides)

    def get_format(self, provider):
        return {"type": "function", "name": self.tool_schema.name}

    def __call__(self, params, overrides=None):
        i = len(self.calls)
        self.calls.append((params, overrides))
        out = self._outputs[min(i, len(self._outputs) - 1)] if self._outputs else "ok"
        meta = FakeMeta(self._rcids) if self.tool_schema.name == "search_corpus" else None
        return out, meta


class FakeToolSet:
    def __init__(self, tools):
        self.tools = {t.tool_schema.name: t for t in tools}

    def get_tool(self, name):
        return self.tools.get(name)


class FC:
    """Fake /responses function_call output item."""

    type = "function_call"

    def __init__(self, name, args, call_id):
        self.name = name
        self.arguments = json.dumps(args)
        self.call_id = call_id


def _usage():
    return types.SimpleNamespace(
        input_tokens=1, output_tokens=1, total_tokens=2, output_tokens_details=None
    )


class Resp:
    def __init__(self, output, output_text="", rid="r"):
        self.output = output
        self.output_text = output_text
        self.id = rid
        self.usage = _usage()


class _RespCreate:
    def __init__(self, outer):
        self.outer = outer

    def create(self, **kwargs):
        self.outer.calls.append(kwargs)
        return self.outer.queue.pop(0)


class FakeResponsesClient:
    def __init__(self, queue):
        self.queue = list(queue)
        self.calls = []  # kwargs of each create()
        self.responses = _RespCreate(self)


class _Msg:
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _ChatTC:
    def __init__(self, name, args, tid):
        self.id = tid
        self.function = types.SimpleNamespace(name=name, arguments=json.dumps(args))


class _ChatResp:
    def __init__(self, msg):
        self.choices = [types.SimpleNamespace(message=msg)]
        self.usage = types.SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)


class _ChatCreate:
    def __init__(self, outer):
        self.outer = outer

    def create(self, **kwargs):
        self.outer.calls.append(kwargs)
        return self.outer.queue.pop(0)


class FakeChatClient:
    def __init__(self, queue):
        self.queue = list(queue)
        self.calls = []
        self.completions = _ChatCreate(self)

    @property
    def chat(self):
        return types.SimpleNamespace(completions=self.completions)


def _base_tools():
    return [
        FakeTool("search_corpus", outputs=["SEARCH-OUT"], returned_chunk_ids=["c1", "c2"]),
        FakeTool("grep_corpus"),
        FakeTool("read_document"),
        FakeTool("prune_chunks", outputs=["Pruned"]),
    ]


# ═════════════════════════ 1. prune helper ═════════════════════════

def test_prune_removes_matching_block_keeps_others():
    text = "head\n# DOCUMENT ID: A \nbodyA\n# DOCUMENT ID: B \nbodyB\n\n[Token usage: 3/16]"
    out = _remove_chunks_from_text(text, {"A"})
    assert "bodyA" not in out
    assert "bodyB" in out
    assert "[Token usage:" in out  # marker preserved


def test_prune_multiple_blocks():
    text = "# DOCUMENT ID: A \nbodyA\n# DOCUMENT ID: B \nbodyB\n# DOCUMENT ID: C \nbodyC"
    out = _remove_chunks_from_text(text, {"A", "C"})
    assert "bodyA" not in out and "bodyC" not in out and "bodyB" in out


def test_prune_noop_when_no_ids_or_no_matches():
    text = "# DOCUMENT ID: A \nbodyA"
    assert _remove_chunks_from_text(text, set()) == text
    assert _remove_chunks_from_text("plain text", {"A"}) == "plain text"


def test_prune_collapses_blank_lines():
    text = "# DOCUMENT ID: A \nbodyA\n# DOCUMENT ID: B \nbodyB"
    out = _remove_chunks_from_text(text, {"A"})
    assert "\n\n\n" not in out


# ═════════════════════════ 2. controller units ═════════════════════════

def test_rejection_budget_formula():
    c = _BudgetController(text_token_counter=counter, threshold_budget=16384, token_budget=32268)
    assert c.rejection_budget == 16384 + int((32268 - 16384) * 0.5) == 24326


def test_dedup_records_and_exposes_ignore_ids():
    c = _BudgetController(text_token_counter=counter, threshold_budget=100, token_budget=200)
    assert c.search_overrides() == {"ignore_ids": []}
    c.record_search(["a_1", "b_2"], "q1")
    assert set(c.search_overrides()["ignore_ids"]) == {"a_1", "b_2"}
    # first query wins for read reranking
    c.record_search(["a_1"], "q2")
    assert c.read_overrides({"doc_id": "a_1"}) == {"query": "q1"}
    assert c.read_overrides({"doc_id": "unknown"}) == {}


def test_prune_state_removes_recorded_chunks():
    c = _BudgetController(text_token_counter=counter, threshold_budget=100, token_budget=200)
    c.record_prune(["X"])
    assert c.prune_text("# DOCUMENT ID: X \nbody") == ""


def test_reject_and_clamp_and_marker():
    c = _BudgetController(text_token_counter=counter, threshold_budget=3, token_budget=100)
    # reject non-prune past rejection budget (=51); allow prune
    assert c.should_reject("search_corpus", 60) is True
    assert c.should_reject("prune_chunks", 60) is False
    assert c.should_reject("search_corpus", 10) is False  # under rejection
    # clamp when remaining < tool_output_budget(4096)
    assert c.tool_max_tokens("search_corpus", 99) == max(512, (100 - 99) // 2)
    # ample budget -> no clamp (needs remaining >= 4096, so use a real-sized budget)
    big = _BudgetController(text_token_counter=counter, threshold_budget=16384, token_budget=32268)
    assert big.tool_max_tokens("search_corpus", 10) is None    # ample
    assert big.tool_max_tokens("grep_corpus", 32000) is None   # not a clamped tool
    # marker
    assert c.annotate("x", 20) == "x\n\n[Token usage: 20/3]"
    assert c.over_threshold(4) and not c.over_threshold(2)
    assert c.over_token_budget(101) and not c.over_token_budget(100)


# ═════════════════════════ 3. responses loop integration ═════════════════════════

def test_responses_loop_cross_turn_dedup():
    """2nd search must receive ignore_ids from the 1st search's returned ids."""
    tools = _base_tools()
    ts = FakeToolSet(tools)
    client = FakeResponsesClient([
        Resp([FC("search_corpus", {"query": "q1"}, "1")]),          # turn 1
        Resp([FC("search_corpus", {"query": "q2"}, "2")]),          # turn 2
        Resp([], output_text="<Document id=c1></Document>"),        # turn 3: conclude
    ])
    run_responses_search(
        toolset=ts, client=client, model="m", query="Q",
        max_turns=10, text_token_counter=counter,
        threshold_budget=10_000, token_budget=20_000,
    )
    search = ts.get_tool("search_corpus")
    assert len(search.calls) == 2
    # 2nd call overrides carry ignore_ids from 1st (c1,c2)
    _, ov2 = search.calls[1]
    assert set(ov2["ignore_ids"]) == {"c1", "c2"}


def test_responses_loop_real_prune_shrinks_transcript():
    """After prune_chunks, the pruned block is gone from the resent transcript."""
    tools = [
        FakeTool("search_corpus",
                 outputs=[f"\n# DOCUMENT ID: c1 \n{TOK} {TOK} bodyone"],
                 returned_chunk_ids=["c1"]),
        FakeTool("prune_chunks", outputs=["Pruned"]),
    ]
    ts = FakeToolSet(tools)
    client = FakeResponsesClient([
        Resp([FC("search_corpus", {"query": "q1"}, "1")]),   # turn 1
        Resp([FC("prune_chunks", {"chunk_ids": ["c1"]}, "2")]),  # turn 2 prune c1
        Resp([FC("search_corpus", {"query": "q3"}, "3")]),   # turn 3 (triggers re-render)
        Resp([], output_text="done"),                        # turn 4 conclude
    ])
    run_responses_search(
        toolset=ts, client=client, model="m", query="Q",
        max_turns=10, text_token_counter=counter,
        threshold_budget=10_000, token_budget=20_000,
    )
    # turn 3's create() input must NOT contain the pruned body
    turn3_input = client.calls[2]["input"]
    blob = json.dumps(turn3_input)
    assert "bodyone" not in blob  # real pruning happened


def test_responses_loop_threshold_restricts_to_prune_and_injects_message():
    tools = [
        FakeTool("search_corpus",
                 outputs=[f"# DOCUMENT ID: c1 \n{TOK} {TOK} {TOK} {TOK} {TOK}"],  # 5 TOK
                 returned_chunk_ids=["c1"]),
        FakeTool("prune_chunks", outputs=["Pruned"]),
    ]
    ts = FakeToolSet(tools)
    client = FakeResponsesClient([
        Resp([FC("search_corpus", {"query": "q1"}, "1")]),  # turn 1 -> 5 TOK in transcript
        Resp([FC("prune_chunks", {"chunk_ids": ["c1"]}, "2")]),  # turn 2 (restricted)
        Resp([], output_text="done"),
    ])
    run_responses_search(
        toolset=ts, client=client, model="m", query="Q",
        max_turns=10, text_token_counter=counter,
        threshold_budget=3, token_budget=100,  # 5 TOK > threshold 3
    )
    # turn 2's create(): tools restricted to prune only + budget message injected
    turn2 = client.calls[1]
    tool_names = {t["name"] for t in turn2["tools"]}
    assert tool_names == {"prune_chunks"}
    assert "OVER BUDGET" in json.dumps(turn2["input"])


def test_responses_loop_rejection_blocks_non_prune():
    """Past rejection budget, a non-prune tool call is not executed; model gets the error."""
    tools = [
        FakeTool("search_corpus",
                 outputs=[" ".join([TOK] * 60)],  # 60 TOK -> over rejection (51)
                 returned_chunk_ids=["c1"]),
        FakeTool("prune_chunks", outputs=["Pruned"]),
    ]
    ts = FakeToolSet(tools)
    client = FakeResponsesClient([
        Resp([FC("search_corpus", {"query": "q1"}, "1")]),   # turn 1 -> 60 TOK
        Resp([FC("search_corpus", {"query": "q2"}, "2")]),   # turn 2 non-prune -> rejected
        Resp([], output_text="done"),
    ])
    run_responses_search(
        toolset=ts, client=client, model="m", query="Q",
        max_turns=10, text_token_counter=counter,
        threshold_budget=3, token_budget=100,  # rejection = 3 + 0.5*97 = 51
    )
    search = ts.get_tool("search_corpus")
    assert len(search.calls) == 1  # 2nd search NOT executed (rejected)
    # rejection message surfaced to the model on turn 3
    assert "Token budget exceeded" in json.dumps(client.calls[2]["input"])


def test_responses_loop_tool_output_clamp():
    tools = [
        FakeTool("search_corpus", outputs=[f"# DOCUMENT ID: c1 \n{TOK} {TOK}"],
                 returned_chunk_ids=["c1"]),
    ]
    ts = FakeToolSet(tools)
    client = FakeResponsesClient([
        Resp([FC("search_corpus", {"query": "q1"}, "1")]),  # turn1 -> 2 TOK
        Resp([FC("search_corpus", {"query": "q2"}, "2")]),  # turn2 -> clamp (remaining tight)
        Resp([], output_text="done"),
    ])
    run_responses_search(
        toolset=ts, client=client, model="m", query="Q",
        max_turns=10, text_token_counter=counter,
        threshold_budget=1000, token_budget=4,  # remaining = 4-2 = 2 < 4096 -> clamp
    )
    search = ts.get_tool("search_corpus")
    _, ov2 = search.calls[1]
    assert ov2 is not None and "max_tokens" in ov2 and ov2["max_tokens"] >= 512


# ═════════════════════════ 4. chat loop integration ═════════════════════════

def test_chat_loop_dedup_and_prune():
    tools = [
        FakeTool("search_corpus",
                 outputs=[f"# DOCUMENT ID: c1 \n{TOK} bodyone"],
                 returned_chunk_ids=["c1"]),
        FakeTool("prune_chunks", outputs=["Pruned"]),
    ]
    ts = FakeToolSet(tools)
    client = FakeChatClient([
        _ChatResp(_Msg("", [_ChatTC("search_corpus", {"query": "q1"}, "t1")])),
        _ChatResp(_Msg("", [_ChatTC("prune_chunks", {"chunk_ids": ["c1"]}, "t2")])),
        _ChatResp(_Msg("", [_ChatTC("search_corpus", {"query": "q2"}, "t3")])),
        _ChatResp(_Msg("<Document id=c1></Document>", None)),
    ])
    run_chat_search(
        toolset=ts, client=client, model="m", query="Q",
        max_turns=10, text_token_counter=counter,
        threshold_budget=10_000, token_budget=20_000,
    )
    search = ts.get_tool("search_corpus")
    # dedup: 2nd search got ignore_ids from 1st
    assert set(search.calls[1][1]["ignore_ids"]) == {"c1"}
    # real prune: 3rd chat call's messages no longer contain the pruned body
    assert "bodyone" not in json.dumps(client.calls[2]["messages"])
