"""Evaluate Harness-1 against a local vLLM OpenAI-compatible endpoint.

This mirrors inference/evaluate_harness1.py, but replaces the Tinker sampling
client with raw token-id calls to vLLM /v1/completions. It is intended for
parity checks of the released Hugging Face checkpoint served by vLLM.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List

import structlog
import tiktoken

# Allow direct execution while keeping imports package-relative.
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cosmos_retriever.datagen.search_dataset import SearchDataset, get_dataset
from cosmos_retriever.config import get_config
from cosmos_retriever.tools import (
    GrepCorpusTool,
    PruneChunksTool,
    ReadDocumentTool,
    SearchCorpusTool,
    ToolSet,
    UserTextTool,
)
from tinker_cookbook.completers import StopCondition, TokensWithLogprobs
from cosmos_retriever.env_rl import MAX_TURNS, SEARCH_DISPLAY_LIMIT, SlidingWindowSearchEnv

logger = structlog.get_logger("evaluate_harness1_vllm")

SAVE_FULL_TRAJECTORIES = os.environ.get("SAVE_FULL_TRAJECTORIES", "0") == "1"


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


def save_full_trajectory(env: SlidingWindowSearchEnv) -> None:
    traj_root = os.environ.get("TRAJECTORY_SAVE_PATH") or os.environ.get(
        "LOG_PATH", "./tmp/rl_ultra_v3"
    )
    full_dir = os.path.join(traj_root, "full")
    os.makedirs(full_dir, exist_ok=True)

    turns = []
    for i, (action, obs) in enumerate(zip(env._all_actions, env._all_observations)):
        turn_record = {"turn": i}
        if action.reasoning:
            turn_record["reasoning"] = action.reasoning

        tool_calls = []
        for tool, params in zip(action.tools, action.params):
            name = "user_text" if isinstance(tool, UserTextTool) else tool.tool_schema.name
            tool_calls.append({"tool": name, "params": params})
        turn_record["tool_calls"] = tool_calls

        tool_returns = []
        for j, obs_text in enumerate(obs.observations):
            tr = {"text": obs_text}
            if j < len(obs.tool_metadata) and obs.tool_metadata[j] is not None:
                try:
                    tr["metadata"] = obs.tool_metadata[j].model_dump()
                except Exception:
                    tr["metadata"] = str(obs.tool_metadata[j])
            tool_returns.append(tr)
        turn_record["tool_returns"] = tool_returns
        turns.append(turn_record)

    record = {
        "query_id": env.query_id,
        "query_text": env.wm.query,
        "dataset": env.dataset.name,
        "system_prompt": env.system_prompt,
        "turns": turns,
        "curated_ids": env.wm.curated_ids,
        "curated_importance": dict(env.wm.curated_importance),
        "reward": env._terminal_reward,
        "metrics": {
            k: v
            for k, v in env._terminal_metrics.items()
            if isinstance(v, (int, float, str, bool))
        },
    }
    qid_safe = str(env.query_id).replace("/", "_")
    with open(os.path.join(full_dir, f"{qid_safe}.json"), "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, default=str)


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


async def eval_single_query(
    qid: str,
    dataset: SearchDataset,
    toolset: ToolSet,
    search_tool: SearchCorpusTool,
    text_token_counter,
    policy: VllmTokenCompleter,
    max_turns: int,
) -> Dict:
    _, query_text = dataset.get_query_by_id(qid)
    env = SlidingWindowSearchEnv(
        toolset=toolset,
        search_tool=search_tool,
        query_id=qid,
        query_text=query_text,
        dataset=dataset,
        text_token_counter=text_token_counter,
        max_turns=max_turns,
    )
    try:
        result = await run_single_episode(env=env, policy=policy)
        result["query_id"] = qid
        result["query"] = query_text[:80]
        if SAVE_FULL_TRAJECTORIES:
            save_full_trajectory(env)
        logger.info(
            "episode_result",
            qid=qid,
            recall=round(result.get("recall", 0), 3),
            trajectory_recall=round(result.get("trajectory_recall", 0), 3),
            final_answer_recall=round(result.get("final_answer_recall", 0), 3),
            reward=round(result.get("reward", 0), 3),
            curated=result["n_curated"],
            pool=result["n_pool"],
            turns=result["turns"],
            error=result["error"],
            time=result["elapsed_s"],
        )
        return result
    except Exception as exc:
        logger.error("episode_failed", qid=qid, error=str(exc)[:500])
        return {
            "query_id": qid,
            "query": query_text[:80],
            "error": True,
            "reward": 0,
            "recall": 0,
            "trajectory_recall": 0,
            "final_answer_recall": 0,
            "precision": 0,
            "n_curated": 0,
            "n_pool": 0,
            "turns": 0,
        }


async def eval_queries(
    query_ids: List[str],
    dataset: SearchDataset,
    toolset: ToolSet,
    search_tool: SearchCorpusTool,
    text_token_counter,
    policy: VllmTokenCompleter,
    max_turns: int,
    parallel: int,
    partial_output: Path | None = None,
) -> List[Dict]:
    sem = asyncio.Semaphore(parallel)
    write_lock = asyncio.Lock()
    completed = 0

    async def bounded(qid: str) -> Dict:
        nonlocal completed
        async with sem:
            result = await eval_single_query(
                qid,
                dataset,
                toolset,
                search_tool,
                text_token_counter,
                policy,
                max_turns,
            )
        if partial_output is not None:
            async with write_lock:
                completed += 1
                partial_output.parent.mkdir(parents=True, exist_ok=True)
                with partial_output.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(result, default=str) + "\n")
                logger.info(
                    "partial_result_saved",
                    path=str(partial_output),
                    completed=completed,
                    total=len(query_ids),
                    qid=qid,
                )
        return result

    return list(await asyncio.gather(*(bounded(qid) for qid in query_ids)))


def summarize_results(results: List[Dict]) -> Dict:
    n = len(results)

    def mean(key: str) -> float:
        return sum(float(r.get(key, 0.0)) for r in results) / max(n, 1)

    return {
        "n": n,
        "errors": sum(1 for r in results if r.get("error")),
        "recall": mean("recall"),
        "trajectory_recall": mean("trajectory_recall"),
        "final_answer_recall": mean("final_answer_recall"),
        "precision": mean("precision"),
        "reward": mean("reward"),
        "turns": mean("turns"),
        "n_curated": mean("n_curated"),
        "n_pool": mean("n_pool"),
    }


def print_results_table(name: str, results: List[Dict]) -> None:
    summary = summarize_results(results)
    print(f"\n{'=' * 80}")
    print(f"  {name}")
    print(f"{'=' * 80}")
    print(f"  n: {summary['n']}  errors: {summary['errors']}")
    print(f"  Recall:              {summary['recall']:.4f}")
    print(f"  Trajectory Recall:   {summary['trajectory_recall']:.4f}")
    print(f"  Final-Answer Recall: {summary['final_answer_recall']:.4f}")
    print(f"  Precision:           {summary['precision']:.4f}")
    print(f"  Reward:              {summary['reward']:.4f}")
    print(f"  Turns:               {summary['turns']:.2f}")
    print(f"{'=' * 80}\n")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="browsecompplus")
    parser.add_argument("--split", default="test", choices=["all", "test", "train", "rl"])
    parser.add_argument("--collection-split", default="test", choices=["test", "train", "rl"])
    parser.add_argument("--n-queries", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--query-ids", nargs="*", default=None)
    parser.add_argument("--max-turns", type=int, default=MAX_TURNS)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--parallel", type=int, default=1)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model", default="harness-1")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--output", default=None)
    parser.add_argument(
        "--partial-output",
        default=None,
        help="Append one JSON line per completed query so interrupted runs keep progress.",
    )
    parser.add_argument(
        "--reranker",
        type=str,
        default="baseten",
        choices=["baseten", "vllm", "none"],
        help="Reranker backend: baseten (original), vllm (local Qwen3-Reranker-8B drop-in), or none.",
    )
    args = parser.parse_args()

    config = get_config()
    tiktoken_enc = tiktoken.get_encoding("o200k_harmony")
    text_token_counter = lambda text: len(tiktoken_enc.encode(text))

    dataset = get_dataset(args.dataset)
    collection_names = dataset.get_cosmos_containers(split=args.collection_split)
    cosmos_database = config.get_cosmos_database()
    import os as _os
    _EMBED_BASE_URL = _os.environ.get("EMBED_BASE_URL")
    if _EMBED_BASE_URL:
        from openai import OpenAI as _OpenAI
        openai_client = _OpenAI(
            base_url=_EMBED_BASE_URL,
            api_key=_os.environ.get("EMBED_API_KEY", "EMPTY"),
        )
        _embed_model = _os.environ.get("EMBED_MODEL", "qwen3-embed")
    else:
        openai_client = config.get_openai_client()
        _embed_model = "text-embedding-3-small"

    try:
        _reranker_backend = getattr(args, "reranker", "baseten")
        if _reranker_backend == "none":
            reranker = None
        elif _reranker_backend == "vllm":
            from harness.rerank import VLLMQwen3Reranker

            reranker = VLLMQwen3Reranker(token_counter=text_token_counter, max_tokens=4096)
        else:
            from harness.rerank import BasetenReranker

            reranker = BasetenReranker(token_counter=text_token_counter, max_tokens=4096)
    except Exception:
        reranker = None

    search_tool = SearchCorpusTool(
        cosmos_database=cosmos_database,
        openai_client=openai_client,
        cosmos_container_name=collection_names[0],
        openai_ef_name=_embed_model,
        reranker=reranker,
        snippet_max_chars=2048,
        display_limit=SEARCH_DISPLAY_LIMIT,
    )
    toolset = ToolSet(name=f"{args.dataset}_toolset")
    toolset.add_tool(search_tool)
    toolset.add_tool(
        GrepCorpusTool(
            cosmos_database=cosmos_database,
            cosmos_container_name=collection_names[0],
            token_counter=text_token_counter,
        )
    )
    toolset.add_tool(
        ReadDocumentTool(
            cosmos_database=cosmos_database,
            cosmos_container_name=collection_names[0],
            reranker=reranker,
            token_counter=text_token_counter,
            max_tokens=4096,
        )
    )
    toolset.add_tool(PruneChunksTool())

    if args.split == "all":
        all_qids = dataset.get_all_query_ids()
    elif args.split == "test":
        all_qids = dataset.get_test_query_ids()
    elif args.split == "rl":
        all_qids = dataset.get_rl_query_ids()
    else:
        all_qids = dataset.get_all_query_ids(split="train")

    if args.query_ids:
        known_qids = set(all_qids)
        query_ids = [qid for qid in args.query_ids if qid in known_qids]
        if not query_ids:
            raise ValueError("No valid query IDs remained after filtering")
    else:
        rng = random.Random(args.seed)
        query_ids = rng.sample(all_qids, min(args.n_queries, len(all_qids)))

    policy = VllmTokenCompleter(
        base_url=args.base_url,
        model=args.model,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
        top_p=args.top_p,
        timeout=args.timeout,
    )

    logger.info(
        "evaluating_vllm",
        model=args.model,
        base_url=args.base_url,
        n=len(query_ids),
        parallel=args.parallel,
    )
    results = await eval_queries(
        query_ids=query_ids,
        dataset=dataset,
        toolset=toolset,
        search_tool=search_tool,
        text_token_counter=text_token_counter,
        policy=policy,
        max_turns=args.max_turns,
        parallel=args.parallel,
        partial_output=Path(args.partial_output) if args.partial_output else None,
    )
    print_results_table(args.model, results)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            args.model: [
                {
                    k: v
                    for k, v in r.items()
                    if isinstance(v, (int, float, str, bool, list))
                }
                for r in results
            ],
            "_summary": summarize_results(results),
        }
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("results_saved", path=str(output_path))


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    asyncio.run(main())
