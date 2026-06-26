"""Harmony token parsing helpers for the Tinker/gpt-oss agent path.

Only the static helpers used by ``env_rl`` to turn sampled Harmony
completion tokens into an :class:`Action` remain here. The live inference
models and agent loop live in the ``cosmos_retriever.inference`` package.
"""

import json
import json_repair
import re
import uuid
from typing import Any, Dict, List, Optional

from openai_harmony import HarmonyEncoding, Message
import structlog

from cosmos_retriever.tools import ToolSet, UserTextTool
from cosmos_retriever.trajectory import Action, ActionBuilder


logger = structlog.get_logger("search_agent.agent")


class TinkerAgentInferenceModel:
    """Static helpers for parsing Harmony completion tokens into actions."""

    @staticmethod
    def _extract_first_json_object(s: str) -> Optional[str]:
        """Return the substring for the first balanced top-level JSON object/array.

        Walks the string tracking brace/bracket depth and string quoting so
        that trailing garbage (extra text, duplicate objects, ``[END]``
        markers, etc.) is silently discarded.  Returns ``None`` when no
        balanced object is found.
        """
        # Find the opening delimiter
        start = -1
        open_ch = ""
        for i, ch in enumerate(s):
            if ch in ('{', '['):
                start = i
                open_ch = ch
                break
        if start < 0:
            return None

        close_ch = '}' if open_ch == '{' else ']'
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(s)):
            ch = s[i]
            if esc:
                esc = False
                continue
            if ch == '\\' and in_str:
                esc = True
                continue
            if ch == '"' and not esc:
                in_str = not in_str
                continue
            if not in_str:
                if ch == open_ch:
                    depth += 1
                elif ch == close_ch:
                    depth -= 1
                    if depth == 0:
                        return s[start: i + 1]
        return None

    @staticmethod
    def _repair_json_escapes(s: str) -> str:
        """Fix invalid backslash escapes that are illegal in JSON."""
        s = re.sub(r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})', r'\\\\', s)
        s = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', s)
        return s

    @staticmethod
    def _parse_json(json_string: str, strict_mode: bool = True) -> Any:
        """Parse JSON string with automatic fallback repairs.

        Repair pipeline (strict_mode=True):
        1. ``json.loads`` on the raw string.
        2. Extract the first balanced JSON object/array, discard trailing
           garbage, then ``json.loads`` again.
        3. Additionally fix invalid backslash escapes, then retry.
        Non-strict mode delegates to ``json_repair``.
        """
        if not strict_mode:
            return json_repair.loads(json_string)

        # 1. Fast path – raw string parses cleanly
        try:
            return json.loads(json_string)
        except json.JSONDecodeError:
            pass

        # 2. Extract first JSON object, ignore trailing garbage
        first_obj = TinkerAgentInferenceModel._extract_first_json_object(json_string)
        if first_obj is not None:
            try:
                return json.loads(first_obj)
            except json.JSONDecodeError:
                pass

            # 3. Also fix bad escapes on the extracted object
            repaired = TinkerAgentInferenceModel._repair_json_escapes(first_obj)
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                pass

        # Nothing worked – raise the original error for the caller to handle
        return json.loads(json_string)

    @staticmethod
    def handle_tool_message(
        message: Message,
        toolset: ToolSet,
        action_builder: ActionBuilder,
        strict_mode: bool = True,
    ) -> None:
        if message.recipient == "functions.multi_tool_use":
            args = TinkerAgentInferenceModel._parse_json(
                message.content[0].text, strict_mode
            )
            tool_calls: List[Dict[str, Any]] = []
            if isinstance(args, list):
                tool_calls = args
            elif isinstance(args, dict):
                tool_calls = args["tool_calls"]
            else:
                raise ValueError(f"Invalid tool calls: {args}")
            for tool_call in tool_calls:
                # Harmony formats tool names with a functions. prefix, remove it
                raw_name = tool_call.get("tool_name")
                if raw_name is None:
                    raise ValueError("Tool call missing 'tool_name'")
                parsed_tool_name = (raw_name or "").replace("functions.", "").replace("<|constrain|>", "").strip()
                if not parsed_tool_name:
                    raise ValueError("Tool name empty after parsing")
                tool = toolset.get_tool(parsed_tool_name)
                if tool is None:
                    raise ValueError(f"Tool not found: {parsed_tool_name}")
                tool_args = tool_call["parameters"]
                source = tool_call["tool_name"] + "_" + uuid.uuid4().hex
                action_builder.add_tool_call(tool=tool, params=tool_args, source=source)
        else:
            # Harmony formats tool names with a functions. prefix, remove it
            recipient = message.recipient
            if recipient is None:
                raise ValueError("Tool message has no recipient (malformed output)")
            parsed_tool_name = (recipient or "").replace("functions.", "").replace("<|constrain|>", "").strip()
            if not parsed_tool_name:
                raise ValueError("Tool name empty after parsing recipient")
            tool = toolset.get_tool(parsed_tool_name)
            if tool is None:
                raise ValueError(f"Tool not found: {parsed_tool_name}")
            tool_args = TinkerAgentInferenceModel._parse_json(
                message.content[0].text, strict_mode
            )
            source = (recipient or "") + "_" + uuid.uuid4().hex
            action_builder.add_tool_call(tool=tool, params=tool_args, source=source)

    @staticmethod
    def tinker_tokens_to_harmony_format(
        encoding: HarmonyEncoding, tokens: List[int]
    ) -> List[Message]:
        return encoding.parse_messages_from_completion_tokens(tokens)

    @staticmethod
    def harmony_tinker_tokens_to_action(
        encoding: HarmonyEncoding,
        tokens: List[int],
        toolset: ToolSet,
        strict_mode: bool = True,
    ) -> Action:
        action_builder = ActionBuilder()
        parsed = TinkerAgentInferenceModel.tinker_tokens_to_harmony_format(
            encoding, tokens
        )
        for i, message in enumerate[Message](parsed):
            if message.channel == "analysis":
                # NOTE: GPT oss 20b occasionally outputs a tool call on analysis, since built in tools are allowed to do so
                # we respect the call and redirect to commentary channel for now
                if message.recipient:
                    logger.warning(
                        "Output tool call on analysis channel, redirecting to commentary channel"
                    )
                    TinkerAgentInferenceModel.handle_tool_message(
                        message, toolset, action_builder, strict_mode
                    )
                else:
                    action_builder.add_reasoning(message.content[0].text)

            elif message.channel == "commentary":
                TinkerAgentInferenceModel.handle_tool_message(
                    message, toolset, action_builder, strict_mode
                )
            elif message.channel == "final":
                action_builder.add_tool_call(
                    tool=UserTextTool(),
                    params={"text": str(message.content[0].text)},
                    source="agent",
                )
            elif message.channel is None:
                # Handle messages with no channel - likely incomplete/malformed tokens
                # Try to extract any text content as reasoning if available
                if (
                    message.content
                    and hasattr(message.content[0], "text")
                    and message.content[0].text
                ):
                    logger.debug(
                        f"Message with None channel, treating as reasoning: {message.content[0].text[:100]}..."
                    )
                    action_builder.add_reasoning(message.content[0].text)
                else:
                    logger.debug(
                        f"Skipping message with None channel and no usable content"
                    )
            else:
                raise ValueError(f"Unknown channel: {message.channel}")
        return action_builder.build()
