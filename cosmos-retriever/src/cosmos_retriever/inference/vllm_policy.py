"""Runtime policy for the ``harmony_vllm`` backend.

Provides the token-level vLLM policy (:class:`VllmTokenCompleter`) and the
single-episode driver (:func:`run_single_episode`) used by ``retriever.py`` to
serve searches against a local vLLM OpenAI-compatible endpoint. These were
extracted from the former evaluation harness so the live serving path no longer
depends on any benchmarking/eval code.
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.request
from typing import Dict

from tinker_cookbook.completers import StopCondition, TokensWithLogprobs

from cosmos_retriever.env_rl import SlidingWindowSearchEnv


class VllmTokenCompleter:
    """Token-level policy backed by vLLM raw completions."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        max_tokens: int,
        temperature: float,
        top_p: float,
        timeout: int,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.timeout = timeout

    @property
    def completions_url(self) -> str:
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/completions"
        return f"{self.base_url}/v1/completions"

    async def __call__(self, model_input, stop: StopCondition) -> TokensWithLogprobs:
        prompt_tokens = model_input.to_ints()
        payload = {
            "model": self.model,
            "prompt": prompt_tokens,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "stream": False,
            "return_token_ids": True,
        }
        if stop and all(isinstance(s, int) for s in stop):
            payload["stop_token_ids"] = list(stop)
        elif stop:
            payload["stop"] = list(stop)

        data = await asyncio.to_thread(self._post_json, payload)
        choice = data["choices"][0]
        tokens = (
            choice.get("token_ids")
            or choice.get("tokens")
            or choice.get("text_token_ids")
            or []
        )
        if not tokens:
            raise RuntimeError(f"vLLM response did not include token IDs: {str(data)[:500]}")
        return TokensWithLogprobs(tokens=[int(t) for t in tokens], maybe_logprobs=None)

    def _post_json(self, payload: Dict) -> Dict:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.completions_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"vLLM HTTP {exc.code}: {detail[:1000]}") from exc


async def run_single_episode(
    env: SlidingWindowSearchEnv,
    policy: VllmTokenCompleter,
) -> Dict:
    ob, stop_condition = await env.initial_observation()
    turns = 0
    start = time.time()

    while True:
        ac_with_logprobs = await policy(ob, stop_condition)
        step_result = await env.step(ac_with_logprobs.tokens)
        turns += 1
        if step_result.episode_done:
            break
        ob = step_result.next_observation
        stop_condition = step_result.next_stop_condition

    elapsed = time.time() - start
    result = {
        "turns": turns,
        "n_curated": len(env.wm.curated_ids),
        "n_pool": len(env.wm.pool_ids),
        "elapsed_s": round(elapsed, 1),
        "tool_types_used": list(env._tool_types_used),
        "total_curate_calls": env._total_curate_calls,
        "pool_ids": list(env.wm.pool_ids),
    }
    return result
