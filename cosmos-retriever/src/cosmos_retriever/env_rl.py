
# Allow direct execution from subdirectories while keeping imports package-relative.
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

"""Inference-only search environment.

Drives the trained Harness-1 policy over a corpus for a single query: it owns
the ``WorkingMemory`` / ``curate`` / ``fan_out_search`` machinery and renders
budget-bounded context each turn via ``ultra_core``. There is no gold data,
reward computation, or RL training here — recall is scored externally by the
caller against ``env.wm.curated_ids``.

Consumed by ``retriever.py`` and ``inference/vllm_policy.py``.
"""

import asyncio
import copy
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
)

import structlog
import tinker
from openai_harmony import (
    Conversation,
    HarmonyEncoding,
    HarmonyEncodingName,
    Message,
    Role,
    load_harmony_encoding,
)
from tinker_cookbook.rl.types import (
    Env,
    Observation as TinkerObservation,
    StopCondition,
    Action as TinkerAction,
    StepResult,
)

from cosmos_retriever.agent import TinkerAgentInferenceModel
from cosmos_retriever.trajectory import (
    Action,
    Observation,
    ActionBuilder,
    ObservationBuilder,
)
from cosmos_retriever.tools import (
    Tool,
    ToolSet,
    ToolSchema,
    ToolCallMetadata,
    SearchCorpusTool,
    SearchCorpusToolCallMetadata,
    GrepCorpusTool,
    GrepCorpusToolCallMetadata,
    ReadDocumentTool,
    PruneChunksTool,
    UserTextTool,
    SEARCH_CORPUS_SCHEMA,
    GREP_CORPUS_SCHEMA,
    READ_DOCUMENT_SCHEMA,
    MULTI_TOOL_USE_SCHEMA,
)

from cosmos_retriever.ultra_core import (
    WorkingMemory,
    WorkingMemorySnapshot,
    build_result_summary,
    get_system_prompt,
    render_context_within_budget,
    parse_doc_ids_from_observation,
    parse_doc_texts_from_observation,
    # Schemas
    FAN_OUT_SEARCH_SCHEMA,
    CURATE_SCHEMA,
    END_SEARCH_SCHEMA,
    REVIEW_DOCS_SCHEMA,
    VERIFY_SCHEMA,
    # v8d helpers
    append_token_marker,
    compress_search_observation,
    auto_populate_from_first_search,
    build_rerank_instruction,
    exec_verify_claim,
    AUTO_POPULATE_TOP_K,
    V8D_AUTO_POPULATE_FIRST_SEARCH,
    V8D_IMPORTANCE_TAGGING,
    V8D_SENTENCE_COMPRESS,
    V8D_TOKEN_BUDGET_MARKER,
    V8D_VERIFY_TOOL,
    V8D_ADAPTIVE_RERANK_INSTRUCTION,
    # Constants
    FAN_OUT_MAX_QUERIES,
    MAX_REVIEW_DOCS,
    MAX_FORMAT_RETRIES,
    CURATE_NUDGE_INTERVAL,
    CURATE_NUDGE_PROMPT,
    FORMAT_RETRY_PROMPT,
    FORMAT_ERROR_PENALTY,
    RECENT_K,
    PROMPT_TOKEN_BUDGET,
    SEARCH_DISPLAY_LIMIT,
    MAX_TURNS,
)

logger = structlog.get_logger("ultra_rl_v3")

# Save trajectory details for debugging
SAVE_TRAJECTORIES = os.environ.get("SAVE_TRAJECTORIES", "1") == "1"
TRAJECTORY_SAVE_PATH = os.environ.get("TRAJECTORY_SAVE_PATH", None)
ABLATE_VERIFY_UNAVAILABLE = os.environ.get("ABLATE_VERIFY_UNAVAILABLE", "0") == "1"
ABLATE_REVIEW_DOCS_UNAVAILABLE = os.environ.get("ABLATE_REVIEW_DOCS_UNAVAILABLE", "0") == "1"


# ═══════════════════════════════════════════════════════════════════════════════
# Tool Stubs (for toolset registration — dispatch handled by env)
# ═══════════════════════════════════════════════════════════════════════════════

class FanOutSearchToolCallMetadata(ToolCallMetadata):
    returned_chunk_ids: List[str]
    queries_executed: int


class FanOutSearchTool(Tool):
    tool_schema: ToolSchema
    def __init__(self):
        super().__init__(tool_schema=FAN_OUT_SEARCH_SCHEMA)
    def __call__(self, params, overrides=None):
        raise NotImplementedError("Handled by env")


class CurateTool(Tool):
    tool_schema: ToolSchema
    def __init__(self):
        super().__init__(tool_schema=CURATE_SCHEMA)
    def __call__(self, params, overrides=None):
        raise NotImplementedError("Handled by env")


class EndSearchTool(Tool):
    tool_schema: ToolSchema
    def __init__(self):
        super().__init__(tool_schema=END_SEARCH_SCHEMA)
    def __call__(self, params, overrides=None):
        return "Search concluded.", None


class ReviewDocsTool(Tool):
    tool_schema: ToolSchema
    def __init__(self):
        super().__init__(tool_schema=REVIEW_DOCS_SCHEMA)
    def __call__(self, params, overrides=None):
        raise NotImplementedError("Handled by env")


class VerifyTool(Tool):
    """v8d: stub for the verify(doc_ids, claim) tool. Dispatched by env."""
    tool_schema: ToolSchema
    def __init__(self):
        super().__init__(tool_schema=VERIFY_SCHEMA)
    def __call__(self, params, overrides=None):
        raise NotImplementedError("Handled by env")

class SlidingWindowSearchEnv(Env):
    """Two-tier-memory search environment with budget-enforced context rendering.

    Inference-only: drives the trained policy and exposes the curated documents
    via :pyattr:`wm`. There is no gold data or reward computation here; recall is
    scored by the caller against :pyattr:`wm.curated_ids`.
    """

    def __init__(
        self,
        toolset: ToolSet,
        search_tool: SearchCorpusTool,
        query_id: str,
        query_text: str,
        dataset_name: str,
        text_token_counter: Optional[Callable[[str], int]] = None,
        max_turns: int = MAX_TURNS,
        normalize_ids: bool = True,
    ):
        self.toolset = toolset
        self.search_tool = search_tool
        self.query_id = query_id
        self.query_text = query_text
        self.text_token_counter = text_token_counter
        self.max_turns = max_turns

        self.enc = load_harmony_encoding(HarmonyEncodingName.HARMONY_GPT_OSS)
        self.stop_condition: StopCondition = [200002, 200012]

        self._normalize_ids = normalize_ids

        self.wm = WorkingMemory(query_text, normalize_ids=self._normalize_ids)
        self.system_prompt = get_system_prompt(query_text)

        self._all_actions: List[Action] = []
        self._all_observations: List[Observation] = []
        self._wm_snapshots: List[WorkingMemorySnapshot] = []
        self._result_summaries: List[str] = []

        self._ids_seen: Set[str] = set()
        self._doc_id_to_query: Dict[str, str] = {}

        self._episode_ended: bool = False
        self._current_turn: int = 0
        self._format_retries: int = 0
        self._turns_since_curate: int = 0
        self._total_curate_calls: int = 0
        self._tool_types_used: Set[str] = set()

        self._approx_prompt_tokens: int = 0
        self._first_search_done: bool = False
        self._dataset_name: str = dataset_name
        self._openai_client = None  # lazily acquired when needed
        # Build rerank instruction once per episode (cheap if LLM path disabled)
        self.wm.rerank_instruction = build_rerank_instruction(
            query=query_text,
            dataset_name=self._dataset_name,
            openai_client=None,
            use_llm=False,
        )

    # ── Environment Interface ──────────────────────────────────────────────

    async def initial_observation(self) -> Tuple[TinkerObservation, StopCondition]:
        self.wm = WorkingMemory(self.query_text, normalize_ids=self._normalize_ids)
        self._wm_snapshots.append(self.wm.snapshot())

        tokens = render_context_within_budget(
            system_prompt=self.system_prompt,
            wm_text=None,
            recent_actions=[],
            recent_observations=[],
            result_summaries=None,
            enc=self.enc,
        )
        return tinker.ModelInput.from_ints(tokens), self.stop_condition

    async def step(self, action_tokens: TinkerAction) -> StepResult:
        full_toolset = self._build_full_toolset()

        # Parse action tokens
        try:
            action = TinkerAgentInferenceModel.harmony_tinker_tokens_to_action(
                self.enc, action_tokens, full_toolset,
            )
        except Exception as e:
            return self._handle_format_error(str(e))

        if len(action.tools) == 0:
            return self._handle_format_error("Reasoning-only action with no tool calls")

        # Check for episode end
        has_end_search = any(
            t.tool_schema.name == "end_search" for t in action.tools
        )
        has_user_text = any(isinstance(t, UserTextTool) for t in action.tools)

        if has_end_search or has_user_text:
            self._episode_ended = True
            self._save_trajectory()
            logger.info(
                "episode_done",
                n_curated=len(self.wm.curated_ids),
                turns=self._current_turn,
                query_id=self.query_id,
            )
            return StepResult(
                reward=0.0,
                episode_done=True,
                next_observation=tinker.ModelInput.empty(),
                next_stop_condition=self.stop_condition,
            )

        # Capture pool size BEFORE tool execution
        pool_size_before = self.wm.get_pool_size()

        # Execute tools
        try:
            observation = await asyncio.to_thread(self._execute_tools, action)
        except Exception as e:
            logger.error("tool_exec_error", error=str(e)[:300], qid=self.query_id)
            return StepResult(
                reward=0.0,
                episode_done=True,
                next_observation=tinker.ModelInput.empty(),
                next_stop_condition=self.stop_condition,
                metrics={"no_error": 0.0, "tool_error": 1.0, "max_turns_reached": 0.0},
            )

        self._format_retries = 0

        # Track curate state
        has_curate = any(t.tool_schema.name == "curate" for t in action.tools)
        if has_curate:
            self._turns_since_curate = 0
            self._total_curate_calls += 1
        else:
            self._turns_since_curate += 1

        for t in action.tools:
            self._tool_types_used.add(t.tool_schema.name)

        self._all_actions.append(action)
        self._all_observations.append(observation)
        self.wm.advance_turn()
        self._current_turn += 1
        self._wm_snapshots.append(self.wm.snapshot())

        # Build result summary
        tool_names = [
            t.tool_schema.name for t in action.tools
            if not isinstance(t, UserTextTool)
        ]
        obs_text = "\n".join(observation.observations) if observation.observations else ""
        summary = build_result_summary(
            obs_text=obs_text,
            tool_names=tool_names,
            wm=self.wm,
            turns_since_curate=self._turns_since_curate,
            tool_types_used=self._tool_types_used,
            current_turn=self._current_turn,
            pool_size_before=pool_size_before,
        )
        self._result_summaries.append(summary)

        # Max turns check
        if self._current_turn >= self.max_turns:
            self._episode_ended = True
            self._save_trajectory()
            return StepResult(
                reward=0.0,
                episode_done=True,
                next_observation=tinker.ModelInput.empty(),
                next_stop_condition=self.stop_condition,
                metrics={"max_turns_reached": 1.0},
            )

        # Render context for next turn (budget-enforced)
        try:
            tokens = self._render_next_context()
        except Exception as e:
            logger.error("render_error", error=str(e)[:300], qid=self.query_id)
            return StepResult(
                reward=0.0,
                episode_done=True,
                next_observation=tinker.ModelInput.empty(),
                next_stop_condition=self.stop_condition,
                metrics={"no_error": 0.0, "max_turns_reached": 0.0},
            )

        return StepResult(
            reward=0.0,
            episode_done=False,
            next_observation=tinker.ModelInput.from_ints(tokens),
            next_stop_condition=self.stop_condition,
        )

    # ── Context Rendering (single pathway via ultra_core) ──────────────────

    def _render_next_context(self) -> List[int]:
        """Render context for the next turn using render_context_within_budget."""
        n_turns = len(self._all_actions)

        if n_turns <= RECENT_K:
            wm_text = None
            recent_actions = self._all_actions
            recent_obs = self._all_observations
            recent_summaries = self._result_summaries
        else:
            wm_boundary = n_turns - RECENT_K
            wm_text = self._wm_snapshots[wm_boundary].text
            recent_actions = self._all_actions[-RECENT_K:]
            recent_obs = self._all_observations[-RECENT_K:]
            recent_summaries = self._result_summaries[-RECENT_K:]

        nudge = None
        if (self._turns_since_curate >= CURATE_NUDGE_INTERVAL
                and self.wm.get_pool_size() > 0):
            nudge = CURATE_NUDGE_PROMPT

        tokens = render_context_within_budget(
            system_prompt=self.system_prompt,
            wm_text=wm_text,
            recent_actions=recent_actions,
            recent_observations=recent_obs,
            result_summaries=recent_summaries,
            enc=self.enc,
            nudge_prompt=nudge,
        )
        # v8d: stash size so the next tool output can append an accurate marker.
        self._approx_prompt_tokens = len(tokens)
        return tokens

    def _render_retry_context(self) -> List[int]:
        """Re-render current context with retry prompt appended."""
        n_turns = len(self._all_actions)

        if n_turns <= RECENT_K:
            wm_text = None
            recent_actions = self._all_actions
            recent_obs = self._all_observations
            recent_summaries = self._result_summaries
        else:
            wm_boundary = n_turns - RECENT_K
            wm_text = self._wm_snapshots[wm_boundary].text
            recent_actions = self._all_actions[-RECENT_K:]
            recent_obs = self._all_observations[-RECENT_K:]
            recent_summaries = self._result_summaries[-RECENT_K:]

        return render_context_within_budget(
            system_prompt=self.system_prompt,
            wm_text=wm_text,
            recent_actions=recent_actions,
            recent_observations=recent_obs,
            result_summaries=recent_summaries,
            enc=self.enc,
            retry_prompt=FORMAT_RETRY_PROMPT,
        )

    # ── Format Error Handling ──────────────────────────────────────────────

    def _handle_format_error(self, error_msg: str) -> StepResult:
        self._format_retries += 1
        if self._format_retries <= MAX_FORMAT_RETRIES:
            logger.warning(
                "format_retry",
                error=error_msg[:200],
                retry=self._format_retries,
                qid=self.query_id,
            )
            try:
                tokens = self._render_retry_context()
            except Exception:
                tokens = render_context_within_budget(
                    self.system_prompt, None, [], [], None,
                    self.enc, retry_prompt=FORMAT_RETRY_PROMPT,
                )
            return StepResult(
                reward=0.0,
                episode_done=False,
                next_observation=tinker.ModelInput.from_ints(tokens),
                next_stop_condition=self.stop_condition,
                metrics={"format_retry": float(self._format_retries)},
            )
        else:
            logger.error(
                "format_error_final",
                error=error_msg[:300],
                retries=self._format_retries,
                qid=self.query_id,
            )
            return StepResult(
                reward=0.0,
                episode_done=True,
                next_observation=tinker.ModelInput.empty(),
                next_stop_condition=self.stop_condition,
                metrics={
                    "no_error": 0.0,
                    "format_error": 1.0,
                    "max_turns_reached": 0.0,
                },
            )

    # ── Tool Dispatch ──────────────────────────────────────────────────────

    def _build_full_toolset(self) -> ToolSet:
        ts = ToolSet(name="ultra_v3_toolset")
        for name, tool in self.toolset.tools.items():
            ts.tools[name] = tool
        ts.tools["fan_out_search"] = FanOutSearchTool()
        ts.tools["curate"] = CurateTool()
        ts.tools["end_search"] = EndSearchTool()
        ts.tools["review_docs"] = ReviewDocsTool()
        if V8D_VERIFY_TOOL:
            ts.tools["verify"] = VerifyTool()
        return ts

    def _execute_tools(self, action: Action) -> Observation:
        obs_builder = ObservationBuilder()

        for tool, params, source in zip(action.tools, action.params, action.sources):
            if isinstance(tool, UserTextTool):
                obs_builder.add_observation("", source=source, tool_metadata=None)
                continue

            name = tool.tool_schema.name
            logger.info("tool_call", tool=name, qid=self.query_id, turn=self._current_turn)
            try:
                if name == "fan_out_search":
                    output, meta = self._exec_fan_out_search(params)
                    obs_builder.add_observation(output, source=source, tool_metadata=meta)
                elif name == "search_corpus":
                    output, meta = self._exec_search(params)
                    obs_builder.add_observation(output, source=source, tool_metadata=meta)
                elif name == "grep_corpus":
                    output, meta = self._exec_grep(params)
                    obs_builder.add_observation(output, source=source, tool_metadata=meta)
                elif name == "read_document":
                    output, meta = self._exec_read_doc(params)
                    obs_builder.add_observation(output, source=source, tool_metadata=meta)
                elif name == "curate":
                    output = self._exec_curate(params)
                    obs_builder.add_observation(output, source=source, tool_metadata=None)
                elif name == "review_docs":
                    output = self._exec_review_docs(params)
                    obs_builder.add_observation(output, source=source, tool_metadata=None)
                elif name == "verify" and V8D_VERIFY_TOOL:
                    output = self._exec_verify(params)
                    obs_builder.add_observation(output, source=source, tool_metadata=None)
                elif name == "end_search":
                    obs_builder.add_observation("Search concluded.", source=source, tool_metadata=None)
                elif name == "prune_chunks":
                    obs_builder.add_observation(
                        "Context is managed via working memory. No pruning needed.",
                        source=source, tool_metadata=None,
                    )
                else:
                    obs_builder.add_observation(
                        f"Unknown tool: {name}", source=source, tool_metadata=None,
                    )
            except Exception as e:
                logger.warning("tool_error", tool=name, error=str(e)[:200], qid=self.query_id)
                obs_builder.add_observation(
                    f"Error executing {name}: {str(e)[:200]}",
                    source=source, tool_metadata=None,
                )

        return obs_builder.build()

    def _maybe_wrap_search_output(
        self,
        output: str,
        query_for_compress: str,
        first_search_ranked_ids: Optional[List[str]] = None,
    ) -> str:
        """v8d wrapper: BM25 compress + auto-populate + token marker."""
        # 1. Sentence-level compression (no-op unless flag on)
        if V8D_SENTENCE_COMPRESS and query_for_compress:
            output = compress_search_observation(query_for_compress, output)

        # 2. Auto-populate the curated set from the first search's top hits
        if (
            V8D_AUTO_POPULATE_FIRST_SEARCH
            and not self._first_search_done
            and first_search_ranked_ids
        ):
            added = auto_populate_from_first_search(
                self.wm, first_search_ranked_ids, top_k=AUTO_POPULATE_TOP_K,
            )
            self._first_search_done = True
            if added > 0:
                output = (
                    output
                    + f"\n\n[AUTO-POPULATED] Top {added} docs from this search have been "
                    "added to your curated set at 'fair' importance. Use `curate` with "
                    "`importance` to promote/demote and `remove_ids` to drop irrelevant ones."
                )

        # 3. Token budget marker (no-op unless flag on)
        if V8D_TOKEN_BUDGET_MARKER and self.text_token_counter is not None:
            try:
                used = self._approx_prompt_tokens + self.text_token_counter(output)
                output = append_token_marker(output, used)
            except Exception:
                pass

        return output

    def _exec_search(self, params: Dict) -> Tuple[str, Optional[ToolCallMetadata]]:
        query = params.get("query") or params.get("q", "")
        pool_before = self.wm.get_pool_size()
        # v8d: pipe per-episode rerank instruction through to the search tool.
        overrides: Dict[str, Any] = {"ignore_ids": list(self._ids_seen)}
        if V8D_ADAPTIVE_RERANK_INSTRUCTION and self.wm.rerank_instruction:
            overrides["rerank_instruction"] = self.wm.rerank_instruction
        output, meta = self.search_tool(params, overrides)
        ranked_ids: List[str] = []
        if meta and isinstance(meta, SearchCorpusToolCallMetadata):
            ranked_ids = list(meta.returned_chunk_ids)
            self._ids_seen.update(meta.returned_chunk_ids)
            doc_texts = parse_doc_texts_from_observation(output)
            self.wm.add_to_pool(meta.returned_chunk_ids, doc_texts)
            for cid in meta.returned_chunk_ids:
                doc_id = cid.split("_")[0] if "_" in cid else cid
                self._doc_id_to_query.setdefault(doc_id, str(query))
            num_new = self.wm.get_pool_size() - pool_before
            self.wm.add_search_record(
                "search", str(query)[:60], len(meta.returned_chunk_ids),
                num_new=num_new,
            )
        output = self._maybe_wrap_search_output(
            output, query_for_compress=str(query),
            first_search_ranked_ids=ranked_ids,
        )
        return output, meta

    def _exec_fan_out_search(self, params: Dict) -> Tuple[str, Optional[FanOutSearchToolCallMetadata]]:
        queries = params.get("queries", [])
        if not isinstance(queries, list) or not queries:
            return "No queries provided.", FanOutSearchToolCallMetadata(
                returned_chunk_ids=[], queries_executed=0,
            )

        queries = queries[:FAN_OUT_MAX_QUERIES]
        all_results: List[str] = []
        all_chunk_ids: List[str] = []
        pool_before = self.wm.get_pool_size()

        for q in queries:
            if not isinstance(q, str) or not q.strip():
                continue
            try:
                overrides: Dict[str, Any] = {"ignore_ids": list(self._ids_seen)}
                if V8D_ADAPTIVE_RERANK_INSTRUCTION and self.wm.rerank_instruction:
                    overrides["rerank_instruction"] = self.wm.rerank_instruction
                output, meta = self.search_tool({"query": q}, overrides)
                all_results.append(output)
                if meta and isinstance(meta, SearchCorpusToolCallMetadata):
                    self._ids_seen.update(meta.returned_chunk_ids)
                    doc_texts = parse_doc_texts_from_observation(output)
                    self.wm.add_to_pool(meta.returned_chunk_ids, doc_texts)
                    all_chunk_ids.extend(meta.returned_chunk_ids)
                    for cid in meta.returned_chunk_ids:
                        doc_id = cid.split("_")[0] if "_" in cid else cid
                        self._doc_id_to_query.setdefault(doc_id, str(q))
            except Exception as e:
                logger.warning("fan_out_error", query=str(q)[:100], error=str(e)[:200])
                all_results.append("No results.")

        q_summary = "; ".join(str(q)[:30] for q in queries[:3])
        num_new = self.wm.get_pool_size() - pool_before
        self.wm.add_search_record(
            "fan_out", q_summary, len(all_chunk_ids), num_new=num_new,
        )
        combined = "\n".join(all_results) if all_results else "No results found."
        # v8d: compress (using concatenated query string), auto-populate, token marker
        concat_query = " ".join(str(q) for q in queries if isinstance(q, str))
        combined = self._maybe_wrap_search_output(
            combined,
            query_for_compress=concat_query,
            first_search_ranked_ids=all_chunk_ids,
        )
        return combined, FanOutSearchToolCallMetadata(
            returned_chunk_ids=all_chunk_ids, queries_executed=len(queries),
        )

    def _exec_grep(self, params: Dict) -> Tuple[str, Optional[ToolCallMetadata]]:
        grep_tool = self.toolset.get_tool("grep_corpus")
        if grep_tool is None:
            return "grep_corpus not available.", None
        pool_before = self.wm.get_pool_size()
        output, meta = grep_tool(params)
        if meta and isinstance(meta, GrepCorpusToolCallMetadata):
            doc_texts = parse_doc_texts_from_observation(output)
            self.wm.add_to_pool(meta.returned_chunk_ids, doc_texts)
            num_new = self.wm.get_pool_size() - pool_before
            self.wm.add_search_record(
                "grep", str(params.get("pattern", ""))[:60],
                len(meta.returned_chunk_ids), num_new=num_new,
            )
        # v8d: grep results can still benefit from sentence-level compression and token marker
        output = self._maybe_wrap_search_output(
            output, query_for_compress=str(params.get("pattern", "")),
            first_search_ranked_ids=None,
        )
        return output, meta

    def _exec_read_doc(self, params: Dict) -> Tuple[str, Optional[ToolCallMetadata]]:
        read_tool = self.toolset.get_tool("read_document")
        if read_tool is None:
            return "read_document not available.", None
        doc_id = params.get("doc_id") or params.get("id", "")
        if self._normalize_ids and "_" in doc_id:
            doc_id = doc_id.split("_")[0]
        overrides = {}
        if doc_id in self._doc_id_to_query:
            overrides["query"] = self._doc_id_to_query[doc_id]
        pool_before = self.wm.get_pool_size()
        output, meta = read_tool(params, overrides or None)
        doc_texts = parse_doc_texts_from_observation(output)
        if doc_texts:
            self.wm.add_to_pool(list(doc_texts.keys()), doc_texts)
        num_new = self.wm.get_pool_size() - pool_before
        self.wm.add_search_record(
            "read", str(doc_id)[:30],
            len(doc_texts) if doc_texts else 1, num_new=num_new,
        )
        # v8d: read_document returns full text — compression is too aggressive here,
        # but still append token marker.
        if V8D_TOKEN_BUDGET_MARKER and self.text_token_counter is not None:
            try:
                used = self._approx_prompt_tokens + self.text_token_counter(output)
                output = append_token_marker(output, used)
            except Exception:
                pass
        return output, meta

    def _exec_curate(self, params: Dict) -> str:
        add_ids = params.get("add_ids", [])
        remove_ids = params.get("remove_ids", [])
        if not isinstance(add_ids, list):
            add_ids = [str(add_ids)] if add_ids else []
        if not isinstance(remove_ids, list):
            remove_ids = [str(remove_ids)] if remove_ids else []

        importance: Optional[Dict[str, str]] = None
        if V8D_IMPORTANCE_TAGGING:
            raw = params.get("importance")
            if isinstance(raw, dict):
                importance = {str(k): str(v) for k, v in raw.items()}

        return self.wm.curate(add_ids, remove_ids, importance=importance)

    def _exec_verify(self, params: Dict) -> str:
        """v8d: verify claim against specific docs via LLM. No corpus call."""
        if ABLATE_VERIFY_UNAVAILABLE:
            self.wm.add_search_record("verify", "unavailable", 0, num_new=0)
            return "verify: unavailable in this ablation."

        doc_ids = params.get("doc_ids", [])
        claim = str(params.get("claim", "")).strip()
        if not isinstance(doc_ids, list):
            doc_ids = [str(doc_ids)] if doc_ids else []
        doc_ids = [str(d).strip() for d in doc_ids if d][:5]
        if not doc_ids or not claim:
            return "verify: doc_ids or claim missing."

        # Resolve full text from WM's doc_store (verify does NOT re-query the corpus).
        doc_texts: Dict[str, str] = {}
        for did in doc_ids:
            norm = self.wm._normalize_id(did)
            store = self.wm.doc_store.get(norm, {})
            txt = store.get("full_text") or store.get("snippet") or ""
            if txt:
                doc_texts[norm] = txt

        if self._openai_client is None:
            try:
                from cosmos_retriever.config import get_config
                self._openai_client = get_config().get_openai_client()
            except Exception as e:
                return f"verify: openai client unavailable ({str(e)[:80]})"

        self.wm.add_search_record(
            "verify", claim[:50], len(doc_ids), num_new=0,
        )
        return exec_verify_claim(self._openai_client, doc_texts, claim)

    def _exec_review_docs(self, params: Dict) -> str:
        if ABLATE_REVIEW_DOCS_UNAVAILABLE:
            self.wm.add_search_record("review", "unavailable", 0)
            return "review_docs: unavailable in this ablation."

        doc_ids = params.get("doc_ids", [])
        if not isinstance(doc_ids, list):
            doc_ids = [str(doc_ids)] if doc_ids else []
        doc_ids = [str(x).strip() for x in doc_ids if x][:MAX_REVIEW_DOCS]
        if not doc_ids:
            return "No doc_ids provided."
        result = self.wm.review_docs(doc_ids)
        self.wm.add_search_record("review", ", ".join(doc_ids[:3]), len(doc_ids))
        return result

    # ── Trajectory Saving ──────────────────────────────────────

    def _save_trajectory(self) -> None:
        if not SAVE_TRAJECTORIES:
            return
        try:
            save_dir = TRAJECTORY_SAVE_PATH or os.environ.get("LOG_PATH", "./tmp/rl_ultra_v3")
            save_dir = os.path.join(save_dir, "trajectories")
            os.makedirs(save_dir, exist_ok=True)

            record = {
                "query_id": self.query_id,
                "dataset": self._dataset_name,
                "normalize_ids": self._normalize_ids,
                "turns": self._current_turn,
                "curated_ids": self.wm.curated_ids,
                # Persist v8d per-doc tags so downstream analysis can filter
                # to high-confidence subsets (e.g., very_high/high only).
                "curated_importance": dict(self.wm.curated_importance),
                "pool_ids": self.wm.pool_ids[:50],
                "pool_size": len(self.wm.pool_ids),
                "search_history": self.wm.search_history,
            }
            save_file = os.path.join(save_dir, "episodes.jsonl")
            with open(save_file, "a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            logger.warning("save_error", error=str(e)[:200])
