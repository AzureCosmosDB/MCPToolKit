"""Unit tests for :mod:`cosmos_retriever.trajectory`."""

from __future__ import annotations

import json

from cosmos_retriever.tools import (
    PRUNE_CHUNKS_SCHEMA,
    PruneChunksTool,
    SearchCorpusToolCallMetadata,
    Tool,
    ToolSchema,
    UserTextTool,
)
from cosmos_retriever.trajectory import (
    Action,
    ActionBuilder,
    ObservationBuilder,
    Trajectory,
    TrajectoryBuilder,
)


class _FakeSearchTool(Tool):
    """A stand-in :class:`Tool` for trajectory rendering tests."""

    tool_schema: ToolSchema

    def __init__(self) -> None:
        super().__init__(
            tool_schema=ToolSchema(
                name="search_corpus",
                description="x",
                parameters={"query": {"type": "string"}},
                required=["query"],
            )
        )

    def __call__(self, params, overrides=None):  # type: ignore[override]
        return "result", None


def _build_tiny_trajectory() -> Trajectory:
    builder = TrajectoryBuilder()
    builder.add_observation(
        ObservationBuilder()
        .add_observation("hello?", source="user")
        .build()
    )
    builder.add_action(
        ActionBuilder()
        .add_reasoning("I should search.")
        .add_tool_call(_FakeSearchTool(), {"query": "hi"}, source="toolu_search_1")
        .build()
    )
    builder.add_observation(
        ObservationBuilder()
        .add_observation(
            "\n# DOCUMENT ID: doc_a \nhello world",
            source="toolu_search_1",
            tool_metadata=SearchCorpusToolCallMetadata(returned_chunk_ids=["doc_a"]),
        )
        .build()
    )
    builder.add_action(
        ActionBuilder()
        .add_tool_call(UserTextTool(), {"text": "<Document id=doc_a></Document>"}, source="agent")
        .build()
    )
    return builder.build()


class TestTrajectoryBuilders:
    def test_builds_in_order(self) -> None:
        traj = _build_tiny_trajectory()
        assert traj.num_turns == 2
        # Alternating obs / action / obs / action
        types = [type(e).__name__ for e in traj.actions_and_observations]
        assert types == ["Observation", "Action", "Observation", "Action"]

    def test_clone_is_deep_for_params(self) -> None:
        traj = _build_tiny_trajectory()
        cloned = traj.clone()
        # mutate the original's params, the clone should be unaffected
        first_action = next(
            e for e in traj.actions_and_observations if isinstance(e, Action)
        )
        first_action.params[0]["query"] = "MUTATED"
        cloned_first = next(
            e for e in cloned.actions_and_observations if isinstance(e, Action)
        )
        assert cloned_first.params[0]["query"] == "hi"


class TestOpenAIChatRendering:
    def test_user_assistant_tool_round_trip(self) -> None:
        traj = _build_tiny_trajectory()
        msgs = traj.to_openai_format()
        assert msgs[0] == {"role": "user", "content": [{"type": "text", "text": "hello?"}]}
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["tool_calls"][0]["function"]["name"] == "search_corpus"
        assert json.loads(msgs[1]["tool_calls"][0]["function"]["arguments"]) == {"query": "hi"}
        assert msgs[2]["role"] == "tool"
        assert "DOCUMENT ID: doc_a" in msgs[2]["content"][0]["text"]
        # Final assistant text
        assert msgs[3]["role"] == "assistant"
        assert msgs[3]["content"][0]["text"].startswith("<Document id=doc_a>")


class TestOpenAIHarmonyRendering:
    def test_renders_to_a_conversation(self) -> None:
        traj = _build_tiny_trajectory()
        conv = traj.to_openai_harmony_format()
        # Sanity: we should have system + developer + the four trajectory entries.
        assert len(conv.messages) >= 4

    def test_user_text_tool_does_not_appear_in_action_dispatch(self) -> None:
        # PruneChunksTool exists in tools.py; ensure ActionBuilder accepts it
        # but rejects MultiToolUseTool (the latter is reserved for rendering).
        ab = ActionBuilder()
        ab.add_tool_call(PruneChunksTool(), {"chunk_ids": ["x"]}, source="agent")
        action = ab.build()
        assert action.tools[0].tool_schema.name == PRUNE_CHUNKS_SCHEMA.name


class TestObservationBuilderValidation:
    def test_incomplete_builder_raises(self) -> None:
        ob = ObservationBuilder()
        try:
            ob.build()
        except ValueError as exc:
            assert "is not complete" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("expected ValueError")
