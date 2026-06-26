"""Trajectory data structures + provider-format rendering.

Carried over from upstream Harness-1 with everything that isn't required at
inference time stripped out:

* Anthropic / Moonshot / OpenAI-Responses provider formats — gone.
* :pymeth:`Trajectory.deserialize` (loads saved-to-disk trajectories) — gone;
  the retriever never re-hydrates a trajectory from JSON.

What remains is enough to feed the trained Harness-1 model on vLLM
(:py:meth:`Trajectory.to_openai_harmony_format`) and to dump trajectories
for debugging (:py:meth:`Trajectory.to_openai_format`).
"""

from __future__ import annotations

import copy
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from openai_harmony import (
    Author,
    Conversation,
    DeveloperContent,
    Message,
    ReasoningEffort,
    Role,
    SystemContent,
    ToolDescription,
)
from pydantic import BaseModel, SerializeAsAny, model_validator

from cosmos_retriever.tools import (
    GREP_CORPUS_SCHEMA,
    MULTI_TOOL_USE_SCHEMA,
    PRUNE_CHUNKS_SCHEMA,
    READ_DOCUMENT_SCHEMA,
    SEARCH_CORPUS_SCHEMA,
    MultiToolUseTool,
    SerializedTool,
    Tool,
    ToolCallMetadata,
    UserTextTool,
)
from cosmos_retriever.utils import ProviderFormat

logger = structlog.get_logger("cosmos_retriever.trajectory")

Source = str | Literal["user"] | Literal["agent"]
"""Identifier for who produced an entry: a tool-call id, ``"user"``, or ``"agent"``."""


# ============================================================================
# Action
# ============================================================================


class Action(BaseModel):
    """One step the agent took: zero or more tool calls plus optional reasoning."""

    tools: list[Tool]
    params: list[dict]
    sources: list[Source]
    reasoning: str | None = None

    def as_iter(self) -> Iterator[tuple[Tool, dict, Source]]:
        return iter(zip(self.tools, self.params, self.sources, strict=True))

    @model_validator(mode="before")
    @classmethod
    def _deserialize_tools(cls, data: Any) -> Any:
        """Resolve serialised tool stubs to runtime Tool subclasses."""

        if not isinstance(data, dict):
            return data
        tools = data.get("tools")
        if not tools:
            return data

        resolved: list[Tool] = []
        for tool_entry in tools:
            if isinstance(tool_entry, Tool):
                resolved.append(tool_entry)
                continue
            if isinstance(tool_entry, dict):
                schema = tool_entry.get("tool_schema")
                if schema is None:
                    raise ValueError("Serialized tool entry missing 'tool_schema'")
                if schema.get("name") == "user_text":
                    resolved.append(UserTextTool())
                else:
                    resolved.append(SerializedTool(tool_schema=schema))
                continue
            resolved.append(tool_entry)
        data = data.copy()
        data["tools"] = resolved
        return data


class ActionBuilder:
    """Builder for an :class:`Action`."""

    def __init__(self) -> None:
        self.action = Action(tools=[], params=[], sources=[], reasoning=None)

    def add_tool_call(self, tool: Tool, params: dict, source: Source) -> ActionBuilder:
        if isinstance(tool, MultiToolUseTool):
            raise ValueError("MultiToolUseTool should not be added to an action builder")
        self.action.tools.append(tool)
        self.action.params.append(params)
        self.action.sources.append(source)
        return self

    def add_reasoning(self, reasoning: str) -> ActionBuilder:
        if self.action.reasoning is not None:
            raise ValueError("Reasoning already added for this action")
        self.action.reasoning = reasoning
        return self

    def is_complete(self) -> bool:
        has_tools = (
            len(self.action.tools) > 0
            and len(self.action.tools)
            == len(self.action.params)
            == len(self.action.sources)
        )
        return has_tools or self.action.reasoning is not None

    def build(self) -> Action:
        if not self.is_complete():
            raise ValueError(
                "ActionBuilder is not complete: missing tools/params/sources or reasoning"
            )
        return self.action


# ============================================================================
# Observation
# ============================================================================


class Observation(BaseModel):
    """Tool outputs (or user/system messages) for a single step."""

    observations: list[str]
    sources: list[Source]
    tool_metadata: list[SerializeAsAny[ToolCallMetadata] | None]


class ObservationBuilder:
    """Builder for an :class:`Observation`."""

    def __init__(self) -> None:
        self.observations: list[str] = []
        self.sources: list[Source] = []
        self.tool_metadata: list[ToolCallMetadata | None] = []

    def add_observation(
        self,
        observation: str,
        source: Source,
        tool_metadata: ToolCallMetadata | None = None,
    ) -> ObservationBuilder:
        self.observations.append(observation)
        self.sources.append(source)
        self.tool_metadata.append(tool_metadata)
        return self

    def is_complete(self) -> bool:
        return (
            len(self.observations) > 0
            and len(self.tool_metadata) == len(self.observations)
            and len(self.sources) == len(self.observations)
        )

    def build(self) -> Observation:
        if not self.is_complete():
            raise ValueError("ObservationBuilder is not complete")
        return Observation(
            observations=self.observations,
            sources=self.sources,
            tool_metadata=self.tool_metadata,
        )


# ============================================================================
# Trajectory
# ============================================================================


class Trajectory(BaseModel):
    """A sequence of alternating :class:`Action` and :class:`Observation` entries."""

    actions_and_observations: list[Action | Observation]
    id: uuid.UUID

    @property
    def num_turns(self) -> int:
        return sum(1 for entry in self.actions_and_observations if isinstance(entry, Action))

    def clone(self) -> Trajectory:
        """Deep-copy the trajectory while keeping Tool references shared.

        Tool instances may hold unpicklable HTTP clients, so we cannot use
        :py:meth:`pydantic.BaseModel.model_copy(deep=True)`. We use
        :py:meth:`pydantic.BaseModel.model_construct` to skip validation since
        the data is already validated.
        """

        cloned: list[Action | Observation] = []
        for entry in self.actions_and_observations:
            if isinstance(entry, Action):
                cloned.append(
                    Action.model_construct(
                        tools=list(entry.tools),
                        params=copy.deepcopy(entry.params),
                        sources=list(entry.sources),
                        reasoning=entry.reasoning,
                    )
                )
            else:
                cloned.append(
                    Observation.model_construct(
                        observations=list(entry.observations),
                        sources=list(entry.sources),
                        tool_metadata=list(entry.tool_metadata),
                    )
                )
        return Trajectory.model_construct(actions_and_observations=cloned, id=self.id)

    def __repr__(self) -> str:
        out = "Trajectory:\n"
        for i, item in enumerate(self.actions_and_observations):
            if isinstance(item, Action):
                out += f"[Step {i}] [Action] {item.tools!r} with params {item.params}\n"
            else:
                snippet = [obs[:100] for obs in item.observations]
                out += f"[Step {i}] [Observation] {snippet}...\n"
            out += "\n"
        return out

    def to_provider_format(self, provider: ProviderFormat) -> Any:
        if provider is ProviderFormat.OPENAI_HARMONY:
            return self.to_openai_harmony_format()
        if provider is ProviderFormat.OPENAI:
            return self.to_openai_format()
        raise ValueError(f"Unsupported provider format: {provider}")

    # ------------------------------------------------------------------
    # OpenAI Chat Completions (debug / serialisation only)
    # ------------------------------------------------------------------
    def to_openai_format(self) -> list[dict[str, Any]]:
        """Convert the trajectory into OpenAI Chat Completions message format."""

        def _make_text_content(text: str) -> dict[str, str]:
            if text.strip() == "":
                logger.warning("empty_text_content_maybe_pruned")
                return {"type": "text", "text": "Maybe pruned?"}
            return {"type": "text", "text": text}

        messages: list[dict[str, Any]] = []
        for entry in self.actions_and_observations:
            if isinstance(entry, Action):
                content_items: list[dict[str, Any]] = []
                tool_calls: list[dict[str, Any]] = []
                for tool, params, source in entry.as_iter():
                    if isinstance(tool, UserTextTool):
                        content_items.append(_make_text_content(params.get("text", "")))
                    else:
                        tool_calls.append(
                            {
                                "id": str(source),
                                "type": "function",
                                "function": {
                                    "name": tool.tool_schema.name,
                                    "arguments": json.dumps(params),
                                },
                            }
                        )
                msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": content_items if content_items else "",
                }
                if tool_calls:
                    msg["tool_calls"] = tool_calls
                messages.append(msg)
            else:
                for text, source in zip(entry.observations, entry.sources, strict=True):
                    if source == "user":
                        messages.append(
                            {"role": "user", "content": [_make_text_content(text)]}
                        )
                    else:
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": str(source),
                                "content": [_make_text_content(text)],
                            }
                        )
        return messages

    # ------------------------------------------------------------------
    # OpenAI Harmony — the format the trained Harness-1 model expects
    # ------------------------------------------------------------------
    def to_openai_harmony_format(self) -> Conversation:
        system_message = (
            SystemContent.new()
            .with_reasoning_effort(ReasoningEffort.HIGH)
            .with_conversation_start_date(datetime.now(UTC).strftime("%Y-%m-%d"))
        )
        messages: list[Message] = [Message.from_role_and_content(Role.SYSTEM, system_message)]

        def fmt_params(parameters: dict[str, Any], required: list[str]) -> dict[str, Any]:
            return {"type": "object", "properties": parameters, "required": required}

        developer_message = DeveloperContent.new().with_function_tools(
            [
                ToolDescription.new(
                    SEARCH_CORPUS_SCHEMA.name,
                    SEARCH_CORPUS_SCHEMA.description,
                    fmt_params(SEARCH_CORPUS_SCHEMA.parameters, SEARCH_CORPUS_SCHEMA.required),
                ),
                ToolDescription.new(
                    GREP_CORPUS_SCHEMA.name,
                    GREP_CORPUS_SCHEMA.description,
                    fmt_params(GREP_CORPUS_SCHEMA.parameters, GREP_CORPUS_SCHEMA.required),
                ),
                ToolDescription.new(
                    READ_DOCUMENT_SCHEMA.name,
                    READ_DOCUMENT_SCHEMA.description,
                    fmt_params(READ_DOCUMENT_SCHEMA.parameters, READ_DOCUMENT_SCHEMA.required),
                ),
                ToolDescription.new(
                    MULTI_TOOL_USE_SCHEMA.name,
                    MULTI_TOOL_USE_SCHEMA.description,
                    fmt_params(MULTI_TOOL_USE_SCHEMA.parameters, MULTI_TOOL_USE_SCHEMA.required),
                ),
                ToolDescription.new(
                    PRUNE_CHUNKS_SCHEMA.name,
                    PRUNE_CHUNKS_SCHEMA.description,
                    fmt_params(PRUNE_CHUNKS_SCHEMA.parameters, PRUNE_CHUNKS_SCHEMA.required),
                ),
            ]
        )
        messages.append(Message.from_role_and_content(Role.DEVELOPER, developer_message))

        tool_use_source_to_tool_name: dict[str, str] = {}
        for entry in self.actions_and_observations:
            if isinstance(entry, Action):
                self._render_action_to_harmony(entry, messages, tool_use_source_to_tool_name)
            else:
                self._render_observation_to_harmony(entry, messages, tool_use_source_to_tool_name)
        return Conversation(messages=messages)

    @staticmethod
    def _render_action_to_harmony(
        action: Action,
        messages: list[Message],
        tool_use_source_to_tool_name: dict[str, str],
    ) -> None:
        if action.reasoning:
            messages.append(
                Message.from_role_and_content(Role.ASSISTANT, action.reasoning).with_channel(
                    "analysis"
                )
            )
        if len(action.tools) > 1:
            # GPT-OSS 20B was not trained with native parallel tool calls; pack
            # the bundle into a single multi_tool_use call on the commentary
            # channel.
            tool_calls: list[dict[str, Any]] = []
            for tool, params, source in action.as_iter():
                if isinstance(tool, UserTextTool):
                    messages.append(
                        Message.from_role_and_content(
                            Role.ASSISTANT, params["text"]
                        ).with_channel("final")
                    )
                else:
                    tool_calls.append(
                        {"tool_name": tool.tool_schema.name, "parameters": params}
                    )
                    tool_use_source_to_tool_name[str(source)] = tool.tool_schema.name
            messages.append(
                Message.from_role_and_content(Role.ASSISTANT, json.dumps(tool_calls))
                .with_channel("commentary")
                .with_recipient("functions.multi_tool_use")
                .with_content_type("<|constrain|>json")
            )
        elif len(action.tools) == 1:
            tool = action.tools[0]
            params = action.params[0]
            source = action.sources[0]
            if isinstance(tool, UserTextTool):
                messages.append(
                    Message.from_role_and_content(
                        Role.ASSISTANT, params["text"]
                    ).with_channel("final")
                )
            else:
                messages.append(
                    Message.from_role_and_content(Role.ASSISTANT, json.dumps(params))
                    .with_channel("commentary")
                    .with_recipient("functions." + tool.tool_schema.name)
                    .with_content_type("<|constrain|>json")
                )
                tool_use_source_to_tool_name[str(source)] = "functions." + tool.tool_schema.name

    @staticmethod
    def _render_observation_to_harmony(
        observation: Observation,
        messages: list[Message],
        tool_use_source_to_tool_name: dict[str, str],
    ) -> None:
        if len(observation.observations) > 1:
            tool_results: list[dict[str, Any]] = []
            for text, source in zip(observation.observations, observation.sources, strict=True):
                if source == "user":
                    raise ValueError("User text inside a multi-tool result observation")
                tool_name = tool_use_source_to_tool_name[str(source)]
                tool_results.append(
                    {"type": "tool_result", "name": tool_name, "content": [text]}
                )
            messages.append(
                Message.from_author_and_content(
                    Author(role=Role.TOOL, name="functions.multi_tool_use"),
                    json.dumps(tool_results),
                )
                .with_channel("commentary")
                .with_recipient("assistant")
            )
        else:
            text = observation.observations[0]
            source = observation.sources[0]
            if source == "user":
                messages.append(Message.from_role_and_content(Role.USER, text))
            else:
                source_str = str(source)
                if source_str in tool_use_source_to_tool_name:
                    tool_name = tool_use_source_to_tool_name[source_str]
                else:
                    parts = source_str.split("_")
                    if len(parts) >= 2 and parts[0] == "toolu":
                        tool_name = parts[1]
                    else:
                        raise ValueError(f"Unknown observation source: {source_str}")
                messages.append(
                    Message.from_author_and_content(
                        Author(role=Role.TOOL, name="functions." + tool_name),
                        json.dumps(text),
                    )
                    .with_channel("commentary")
                    .with_recipient("assistant")
                )


class TrajectoryBuilder:
    """Mutable builder for a :class:`Trajectory`."""

    def __init__(self) -> None:
        self.trajectory = Trajectory(actions_and_observations=[], id=uuid.uuid4())

    def add_action(self, action: Action) -> TrajectoryBuilder:
        self.trajectory.actions_and_observations.append(action)
        return self

    def add_observation(self, observation: Observation) -> TrajectoryBuilder:
        self.trajectory.actions_and_observations.append(observation)
        return self

    def __len__(self) -> int:
        return len(self.trajectory.actions_and_observations)

    def build(self) -> Trajectory:
        return self.trajectory


__all__ = [
    "Action",
    "ActionBuilder",
    "Observation",
    "ObservationBuilder",
    "Source",
    "Trajectory",
    "TrajectoryBuilder",
]
