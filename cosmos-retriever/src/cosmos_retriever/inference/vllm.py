"""vLLM inference adapter for the Harness-1 model.

Talks to an OpenAI-compatible vLLM ``/v1/completions`` endpoint, exchanging
**raw token-IDs** in/out so the model's Harmony format is preserved end-to-end.
That is the only inference path the trained Harness-1 checkpoint ships with;
JSON Chat-Completions would lose the channel structure.

The token-stream lifecycle:

1. :py:meth:`~cosmos_retriever.trajectory.Trajectory.to_openai_harmony_format`
   produces an ``openai_harmony.Conversation``.
2. :py:meth:`HarmonyEncoding.render_conversation` turns it into ``list[int]``.
3. We POST those ints as ``"prompt": [...]``, with ``"return_token_ids": True``.
4. vLLM responds with ``token_ids``; we feed them through
   :py:meth:`HarmonyEncoding.parse_messages_from_completion_tokens` and
   replay the ``analysis`` / ``commentary`` / ``final`` channels into an
   :class:`~cosmos_retriever.trajectory.Action`.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

import httpx
import json_repair
import structlog
import tenacity
from openai_harmony import (
    HarmonyEncoding,
    HarmonyEncodingName,
    Message,
    RenderConversationConfig,
    load_harmony_encoding,
)

from cosmos_retriever.inference.base import AgentInferenceModel, InferenceContext
from cosmos_retriever.tools import ToolSet, UserTextTool
from cosmos_retriever.trajectory import Action, ActionBuilder
from cosmos_retriever.utils import ProviderFormat

logger = structlog.get_logger("cosmos_retriever.inference.vllm")


class VLLMHarmonyInferenceModel(AgentInferenceModel):
    """Inference against vLLM serving the Harness-1 model with Harmony tokens.

    Args:
        base_url: Base URL of the vLLM server (e.g. ``http://127.0.0.1:8000``).
        model_name: ``--served-model-name`` advertised by vLLM
            (defaults to ``"harness-1"``).
        max_completion_tokens: Default sampling budget per call.
        temperature: Sampling temperature.
        top_p: Top-p / nucleus sampling.
        timeout_s: HTTP timeout in seconds.
        strict_mode: When True, JSON tool arguments must parse cleanly with
            :py:func:`json.loads` (with light recovery); when False fall back
            to :pypi:`json-repair`. Train-time uses ``True``; production
            usually wants ``False`` since the model occasionally emits
            slightly-malformed JSON.
        context_window: Hard token cap of the served checkpoint
            (gpt-oss-20b is 32768 without YARN scaling).
    """

    def __init__(
        self,
        base_url: str,
        *,
        model_name: str = "harness-1",
        max_completion_tokens: int = 4096,
        temperature: float = 1.0,
        top_p: float = 0.9,
        timeout_s: float = 900.0,
        strict_mode: bool = False,
        context_window: int = 32768,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.max_completion_tokens = max_completion_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.timeout_s = timeout_s
        self.strict_mode = strict_mode
        self.context_window = context_window

        self.enc: HarmonyEncoding = load_harmony_encoding(HarmonyEncodingName.HARMONY_GPT_OSS)
        self.stop_token_ids = list(self.enc.stop_tokens_for_assistant_actions())
        self._client = httpx.Client(
            timeout=timeout_s,
            headers={"Content-Type": "application/json"},
        )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def __call__(self, context: InferenceContext) -> Action | None:
        trajectory = context.trajectory
        toolset = context.toolset

        request_messages = trajectory.to_provider_format(ProviderFormat.OPENAI_HARMONY)
        input_tokens = self.enc.render_conversation(
            request_messages,
            config=RenderConversationConfig(auto_drop_analysis=False),
        )
        prompt_length = len(input_tokens)

        requested_max = context.max_tokens or self.max_completion_tokens
        available = self.context_window - prompt_length - 100
        if available < requested_max:
            logger.warning(
                "capping_max_tokens",
                prompt_length=prompt_length,
                requested=requested_max,
                available=available,
                context_window=self.context_window,
            )
            effective_max = max(256, available)
        else:
            effective_max = requested_max

        resp_tokens = self._sample(list(input_tokens), effective_max)
        return self._decode_harmony_action(resp_tokens, toolset)

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------
    @tenacity.retry(
        stop=tenacity.stop_after_attempt(5),
        wait=tenacity.wait_exponential(multiplier=1, min=4, max=15),
        before_sleep=lambda _: logger.warning("retry_vllm_sample"),
    )
    def _sample(self, input_tokens: list[int], max_tokens: int) -> list[int]:
        payload = {
            "model": self.model_name,
            "prompt": input_tokens,
            "max_tokens": max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "stream": False,
            "stop_token_ids": self.stop_token_ids,
            "return_token_ids": True,
        }
        resp = self._client.post(f"{self.base_url}/v1/completions", json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"vLLM error {resp.status_code}: {resp.text}")
        data = resp.json()
        return data["choices"][0].get("token_ids", [])

    # ------------------------------------------------------------------
    # Harmony token decoding → Action
    # ------------------------------------------------------------------
    def _decode_harmony_action(self, tokens: list[int], toolset: ToolSet) -> Action:
        action_builder = ActionBuilder()
        messages = self.enc.parse_messages_from_completion_tokens(tokens)
        for message in messages:
            channel = message.channel
            if channel == "analysis":
                # Some checkpoints occasionally emit a tool call on the
                # analysis channel; treat it as a commentary call so the
                # downstream tool dispatch still runs.
                if message.recipient:
                    logger.warning("tool_call_on_analysis_channel_redirected")
                    self._handle_tool_message(message, toolset, action_builder)
                else:
                    action_builder.add_reasoning(message.content[0].text)
            elif channel == "commentary":
                self._handle_tool_message(message, toolset, action_builder)
            elif channel == "final":
                action_builder.add_tool_call(
                    tool=UserTextTool(),
                    params={"text": str(message.content[0].text)},
                    source="agent",
                )
            elif channel is None:
                if message.content and getattr(message.content[0], "text", None):
                    logger.debug("none_channel_treated_as_reasoning")
                    action_builder.add_reasoning(message.content[0].text)
                else:
                    logger.debug("none_channel_skipped")
            else:
                raise ValueError(f"Unknown channel: {channel}")
        return action_builder.build()

    def _handle_tool_message(
        self,
        message: Message,
        toolset: ToolSet,
        action_builder: ActionBuilder,
    ) -> None:
        if message.recipient == "functions.multi_tool_use":
            args = self._parse_json(message.content[0].text)
            if isinstance(args, list):
                tool_calls = args
            elif isinstance(args, dict):
                tool_calls = args.get("tool_calls", [])
            else:
                raise ValueError(f"Invalid multi_tool_use payload: {args!r}")
            for tool_call in tool_calls:
                raw_name = tool_call.get("tool_name")
                if not raw_name:
                    raise ValueError("Tool call missing 'tool_name'")
                parsed_name = self._strip_function_prefix(raw_name)
                tool = toolset.get_tool(parsed_name)
                if tool is None:
                    raise ValueError(f"Tool not found: {parsed_name}")
                source = f"{tool_call['tool_name']}_{uuid.uuid4().hex}"
                action_builder.add_tool_call(
                    tool=tool, params=tool_call.get("parameters", {}), source=source
                )
        else:
            recipient = message.recipient
            if recipient is None:
                raise ValueError("Tool message has no recipient (malformed output)")
            parsed_name = self._strip_function_prefix(recipient)
            tool = toolset.get_tool(parsed_name)
            if tool is None:
                raise ValueError(f"Tool not found: {parsed_name}")
            params = self._parse_json(message.content[0].text)
            if not isinstance(params, dict):
                raise ValueError(f"Tool call params must be a JSON object, got {type(params)}")
            source = f"{recipient}_{uuid.uuid4().hex}"
            action_builder.add_tool_call(tool=tool, params=params, source=source)

    @staticmethod
    def _strip_function_prefix(raw: str) -> str:
        cleaned = (raw or "").replace("functions.", "").replace("<|constrain|>", "").strip()
        if not cleaned:
            raise ValueError("Tool name empty after parsing")
        return cleaned

    # ------------------------------------------------------------------
    # JSON parsing with progressive recovery
    # ------------------------------------------------------------------
    def _parse_json(self, json_string: str) -> Any:
        if not self.strict_mode:
            return json_repair.loads(json_string)
        try:
            return json.loads(json_string)
        except json.JSONDecodeError:
            pass
        first_obj = self._extract_first_json_object(json_string)
        if first_obj is not None:
            try:
                return json.loads(first_obj)
            except json.JSONDecodeError:
                pass
            try:
                return json.loads(self._repair_json_escapes(first_obj))
            except json.JSONDecodeError:
                pass
        # Re-raise the original error so callers see the underlying problem.
        return json.loads(json_string)

    @staticmethod
    def _extract_first_json_object(s: str) -> str | None:
        """Return the substring for the first balanced top-level JSON object/array.

        Walks the string tracking brace/bracket depth and string quoting so
        that trailing garbage (extra text, duplicate objects, ``[END]``
        markers, etc.) is silently discarded. Returns ``None`` when no
        balanced object is found.
        """

        start = -1
        open_ch = ""
        for i, ch in enumerate(s):
            if ch in ("{", "["):
                start = i
                open_ch = ch
                break
        if start < 0:
            return None

        close_ch = "}" if open_ch == "{" else "]"
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(s)):
            ch = s[i]
            if esc:
                esc = False
                continue
            if ch == "\\" and in_str:
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
                        return s[start : i + 1]
        return None

    @staticmethod
    def _repair_json_escapes(s: str) -> str:
        """Fix invalid backslash escapes / control chars that are illegal in JSON."""

        s = re.sub(r'\\(?!["\\/bfnrt]|u[0-9a-fA-F]{4})', r"\\\\", s)
        s = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", s)
        return s


__all__ = ["VLLMHarmonyInferenceModel"]
