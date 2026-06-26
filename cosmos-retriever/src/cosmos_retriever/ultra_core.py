"""Ultra Core — Shared module for the Ultra retrieval agent pipeline.

Single source of truth for: WorkingMemory, context assembly, tool schemas,
system prompt, result summaries, reward computation.

Imported by: generate_sft_v3.py, train_sft_v3.py, train_rl_v3.py
"""

import copy
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import structlog

# Optional v8d dependencies — imported lazily so SFT paths that don't need them still work.
try:
    from rank_bm25 import BM25Okapi  # type: ignore
    _HAS_BM25 = True
except ImportError:
    _HAS_BM25 = False

try:
    from datasketch import MinHash, MinHashLSH  # type: ignore
    _HAS_MINHASH = True
except ImportError:
    _HAS_MINHASH = False
from openai_harmony import (
    Author,
    Conversation,
    DeveloperContent,
    HarmonyEncoding,
    HarmonyEncodingName,
    Message,
    ReasoningEffort,
    Role,
    SystemContent,
    ToolDescription,
    load_harmony_encoding,
)
from cosmos_retriever.tools import (
    ToolSchema,
    UserTextTool,
    SEARCH_CORPUS_SCHEMA,
    GREP_CORPUS_SCHEMA,
    READ_DOCUMENT_SCHEMA,
    MULTI_TOOL_USE_SCHEMA,
)
from cosmos_retriever.trajectory import Action, Observation

logger = structlog.get_logger()

# ═══════════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════════

RECENT_K = int(os.environ.get("RECENT_K", "5"))
FAN_OUT_MAX_QUERIES = 5
MAX_CURATED_DOCS = 30
DOC_SNIPPET_CHARS = int(os.environ.get("DOC_SNIPPET_CHARS", "120"))
CURATED_DOC_CHARS = int(os.environ.get("CURATED_DOC_CHARS", "0"))
MAX_REVIEW_DOCS = 5
SEARCH_DISPLAY_LIMIT = int(os.environ.get("SEARCH_DISPLAY_LIMIT", "10"))
MAX_TURNS = int(os.environ.get("MAX_TURNS", "35"))

MAX_OBS_CHARS = int(os.environ.get("MAX_OBS_CHARS", "15000"))
SEARCH_TOKEN_BUDGET = int(os.environ.get("SEARCH_TOKEN_BUDGET", "4096"))
MAX_ANALYSIS_CHARS_OLDER = int(os.environ.get("MAX_ANALYSIS_CHARS_OLDER", "300"))

# Token budget
MODEL_CTX_LIMIT = 32768
GENERATION_BUDGET = 2048
PROMPT_TOKEN_BUDGET = MODEL_CTX_LIMIT - GENERATION_BUDGET  # 30720

# Format retry
MAX_FORMAT_RETRIES = int(os.environ.get("MAX_FORMAT_RETRIES", "3"))
CURATE_NUDGE_INTERVAL = int(os.environ.get("CURATE_NUDGE_INTERVAL", "1"))

# Reward
REWARD_VERSION = os.environ.get("REWARD_VERSION", "v3")
RECALL_BETA = 2.0
OUTCOME_WEIGHT = float(os.environ.get("OUTCOME_WEIGHT", "0.7"))
TRAJECTORY_RECALL_WEIGHT = float(os.environ.get("TRAJECTORY_RECALL_WEIGHT", "0.3"))
FINAL_ANSWER_BONUS = float(os.environ.get("FINAL_ANSWER_BONUS", "1.0"))
FINAL_ANSWER_BINARY = os.environ.get("FINAL_ANSWER_BINARY", "1") == "1"
# Dense final-answer shaping:
# - FINAL_ANSWER_RECALL_WEIGHT rewards putting answer docs into curated set.
# - TRAJECTORY_FA_RECALL_WEIGHT rewards finding answer docs in pool.
# - FA_MISS_PENALTY_WEIGHT penalizes cases where answer docs are in pool
#   but are not curated (selection failure).
FINAL_ANSWER_RECALL_WEIGHT = float(
    os.environ.get("FINAL_ANSWER_RECALL_WEIGHT", "0.8")
)
TRAJECTORY_FA_RECALL_WEIGHT = float(
    os.environ.get("TRAJECTORY_FA_RECALL_WEIGHT", "0.4")
)
FA_MISS_PENALTY_WEIGHT = float(
    os.environ.get("FA_MISS_PENALTY_WEIGHT", "0.35")
)
MIN_FORMAT_REWARD = 0.001
FORMAT_ERROR_PENALTY = float(os.environ.get("FORMAT_ERROR_PENALTY", "-0.5"))
NO_CURATE_PENALTY = float(os.environ.get("NO_CURATE_PENALTY", "-0.2"))
GAP_PENALTY_WEIGHT = float(os.environ.get("GAP_PENALTY_WEIGHT", "0.0"))

# Turn penalty (linear ramp from 0 at TURN_PENALTY_MIN to TURN_PENALTY_MAX at MAX_TURNS)
TURN_PENALTY_MAX = float(os.environ.get("TURN_PENALTY_MAX", "0.15"))
TURN_PENALTY_MIN_TURNS = int(os.environ.get("TURN_PENALTY_MIN_TURNS", "24"))

# Reward shaping (legacy, kept for compat but defaults zeroed)
TARGET_CURATE_RATE = float(os.environ.get("TARGET_CURATE_RATE", "0.40"))
CURATE_RATE_BONUS_WEIGHT = float(os.environ.get("CURATE_RATE_BONUS_WEIGHT", "0.0"))
TOOL_DIVERSITY_BONUS_WEIGHT = float(os.environ.get("TOOL_DIVERSITY_BONUS", "0.0"))
TOOL_DIVERSITY_TARGET = int(os.environ.get("TOOL_DIVERSITY_TARGET", "3"))
TOOL_DIVERSITY_SHORTFALL_PENALTY = float(
    os.environ.get("TOOL_DIVERSITY_SHORTFALL_PENALTY", "0.0")
)
CONSEC_SEARCH_PENALTY = float(os.environ.get("CONSEC_SEARCH_PENALTY", "0.08"))
MAX_CONSEC_BEFORE_PENALTY = int(os.environ.get("MAX_CONSEC_BEFORE_PENALTY", "1"))
CONSEC_SEARCH_PENALTY_CAP = 0.4

# Windowing
WINDOW_SIZE = int(os.environ.get("WINDOW_SIZE", "5"))
WINDOW_STRIDE = int(os.environ.get("WINDOW_STRIDE", "5"))  # legacy, kept for compat
MAX_WINDOWS = int(os.environ.get("MAX_WINDOWS", "4"))

# ───────────────────────────────────────────────────────────────────────────────
# v8d feature flags (all default OFF — enabled explicitly via launch_v8d_rl.sh)
# ───────────────────────────────────────────────────────────────────────────────
V8D_SUBTRACTIVE_CURATION = os.environ.get("V8D_SUBTRACTIVE_CURATION", "0") == "1"
V8D_IMPORTANCE_TAGGING = os.environ.get("V8D_IMPORTANCE_TAGGING", "0") == "1"
V8D_AUTO_POPULATE_FIRST_SEARCH = os.environ.get("V8D_AUTO_POPULATE_FIRST_SEARCH", "0") == "1"
V8D_EVIDENCE_GRAPH = os.environ.get("V8D_EVIDENCE_GRAPH", "0") == "1"
V8D_SENTENCE_COMPRESS = os.environ.get("V8D_SENTENCE_COMPRESS", "0") == "1"
V8D_CHUNK_NEIGHBORS = os.environ.get("V8D_CHUNK_NEIGHBORS", "0") == "1"
V8D_CONTENT_DEDUP = os.environ.get("V8D_CONTENT_DEDUP", "0") == "1"
V8D_VERIFY_TOOL = os.environ.get("V8D_VERIFY_TOOL", "0") == "1"
V8D_TOKEN_BUDGET_MARKER = os.environ.get("V8D_TOKEN_BUDGET_MARKER", "0") == "1"
V8D_ADAPTIVE_RERANK_INSTRUCTION = os.environ.get("V8D_ADAPTIVE_RERANK_INSTRUCTION", "0") == "1"

# v8d tuning knobs
VALID_IMPORTANCE = ("very_high", "high", "fair", "low")
_IMPORTANCE_RANK = {"very_high": 0, "high": 1, "fair": 2, "low": 3}
SENTENCE_COMPRESS_K = int(os.environ.get("SENTENCE_COMPRESS_K", "4"))
MINHASH_DEDUP_THRESHOLD = float(os.environ.get("MINHASH_DEDUP_THRESHOLD", "0.85"))
MINHASH_NUM_PERM = int(os.environ.get("MINHASH_NUM_PERM", "64"))
EVIDENCE_GRAPH_MAX_ENTITIES = int(os.environ.get("EVIDENCE_GRAPH_MAX_ENTITIES", "8"))
AUTO_POPULATE_TOP_K = int(os.environ.get("AUTO_POPULATE_TOP_K", "8"))

# Prompts
CURATE_NUDGE_PROMPT = (
    "IMPORTANT: You just searched without curating. Follow the search → curate rhythm: "
    "review the results from your last search and call curate NOW to add ALL plausibly "
    "relevant documents. Do not search again until you've curated."
)
FORMAT_RETRY_PROMPT = (
    "Your previous response could not be parsed as a valid tool call. "
    "Please output a valid tool call using the commentary channel. "
    "Example format: start with analysis channel for reasoning, then "
    "use commentary channel with a function call like functions.fan_out_search({...})."
)


# ═══════════════════════════════════════════════════════════════════════════════
# Tool Schemas (Ultra-specific; base tools imported from tools.py)
# ═══════════════════════════════════════════════════════════════════════════════

FAN_OUT_SEARCH_SCHEMA = ToolSchema(
    name="fan_out_search",
    description=(
        f"Run up to {FAN_OUT_MAX_QUERIES} diverse search queries in parallel. "
        "Returns combined results from all queries. Best for broad exploration."
    ),
    parameters={
        "queries": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                f"List of search queries (max {FAN_OUT_MAX_QUERIES}). "
                "Each should target a different aspect."
            ),
        }
    },
    required=["queries"],
)

_CURATE_PARAMS_CORE: Dict[str, Any] = {
    "add_ids": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Document IDs to add to your curated set.",
    },
    "remove_ids": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Document IDs to remove from your curated set.",
    },
}

_CURATE_PARAMS_WITH_IMPORTANCE: Dict[str, Any] = {
    **_CURATE_PARAMS_CORE,
    "importance": {
        "type": "object",
        "description": (
            "Optional per-doc importance tag: {doc_id: one of 'very_high'|'high'|'fair'|'low'}. "
            "'very_high' = confirmed to directly satisfy all query constraints; 'high' = "
            "strongly relevant; 'fair' = default if omitted; 'low' = marginal (eviction-first). "
            "When the set is full, lowest-importance docs are evicted first."
        ),
        "additionalProperties": {"type": "string"},
    },
}

_curate_desc_base = (
    f"Update your curated set of relevant documents (max {MAX_CURATED_DOCS}). "
    "The curated set is your final output."
)
_curate_desc_v8d = (
    f"Update your curated set of relevant documents (max {MAX_CURATED_DOCS}). The curated "
    "set is your final output. Under v8d subtractive curation, you SHOULD tag each added "
    "doc with an importance level; when the set is full, the lowest-importance docs are "
    "evicted first. Default tag is 'fair'. Use 'very_high' only for docs you have "
    "verified directly answer the query."
)

CURATE_SCHEMA = ToolSchema(
    name="curate",
    description=_curate_desc_v8d if V8D_IMPORTANCE_TAGGING else _curate_desc_base,
    parameters=(
        _CURATE_PARAMS_WITH_IMPORTANCE if V8D_IMPORTANCE_TAGGING else _CURATE_PARAMS_CORE
    ),
    required=["add_ids"],
)

VERIFY_SCHEMA = ToolSchema(
    name="verify",
    description=(
        "Check whether specific documents support a claim. Returns a yes/no judgment per doc "
        "and a short rationale. Use BEFORE tagging docs as 'very_high' importance on "
        "multi-constraint queries to confirm they actually satisfy all criteria. "
        "Does NOT cost corpus tokens — compute only."
    ),
    parameters={
        "doc_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Document IDs to check (max 5 per call).",
        },
        "claim": {
            "type": "string",
            "description": (
                "A concrete, checkable claim derived from the query. "
                "E.g. 'This doc was published after 2019 and mentions a GDPR fine above $10M.'"
            ),
        },
    },
    required=["doc_ids", "claim"],
)

END_SEARCH_SCHEMA = ToolSchema(
    name="end_search",
    description=(
        "End your search and submit your curated set as your final answer. "
        "Call this when you've found enough relevant documents."
    ),
    parameters={
        "reasoning": {
            "type": "string",
            "description": "Brief explanation of why you're concluding your search.",
        }
    },
    required=["reasoning"],
)

REVIEW_DOCS_SCHEMA = ToolSchema(
    name="review_docs",
    description=(
        "Re-read documents from your memory. Shows the full text of previously-found "
        "documents without re-searching the corpus. Use this to revisit promising docs."
    ),
    parameters={
        "doc_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": f"Document IDs to review from your pool (max {MAX_REVIEW_DOCS}).",
        }
    },
    required=["doc_ids"],
)

ALL_TOOL_SCHEMAS = [
    SEARCH_CORPUS_SCHEMA, GREP_CORPUS_SCHEMA, READ_DOCUMENT_SCHEMA,
    MULTI_TOOL_USE_SCHEMA,
    FAN_OUT_SEARCH_SCHEMA, CURATE_SCHEMA, END_SEARCH_SCHEMA,
    REVIEW_DOCS_SCHEMA,
]
if V8D_VERIFY_TOOL:
    ALL_TOOL_SCHEMAS.append(VERIFY_SCHEMA)


def get_tool_descriptions() -> List[ToolDescription]:
    """Build Harmony ToolDescription list for all 7 agent tools (+multi_tool_use)."""
    def _fmt(schema: ToolSchema) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": schema.parameters,
            "required": schema.required,
        }
    return [ToolDescription.new(s.name, s.description, _fmt(s)) for s in ALL_TOOL_SCHEMAS]


# ═══════════════════════════════════════════════════════════════════════════════
# System Prompt
# ═══════════════════════════════════════════════════════════════════════════════

def _v8d_prompt_addendum() -> str:
    """Extra guidance injected into the system prompt when v8d features are on."""
    blocks: List[str] = []
    if V8D_IMPORTANCE_TAGGING:
        blocks.append(
            "**Importance Tagging (v8d):** When you call `curate`, tag each added doc "
            "with an `importance` level in {very_high, high, fair, low}. Rules:\n"
            "  - very_high: you have VERIFIED the doc directly answers the query "
            "(ideally after a `verify` call).\n"
            "  - high: strongly relevant, hits most query constraints.\n"
            "  - fair: plausible but not confirmed (default tag if omitted).\n"
            "  - low: marginal; will be evicted first when the set is full.\n"
            "The curated set is capped at "
            f"{MAX_CURATED_DOCS} — when full, the lowest-importance docs are "
            "evicted first to make room for higher-tagged ones."
        )
    if V8D_AUTO_POPULATE_FIRST_SEARCH:
        blocks.append(
            "**Auto-populate (v8d):** After your first successful search, the top-ranked "
            f"{AUTO_POPULATE_TOP_K} docs are AUTOMATICALLY added to your curated set at "
            "`fair` importance. Your job is NOT to re-add them — instead, promote the good "
            "ones to `high`/`very_high` and REMOVE the bad ones. This is subtractive curation."
        )
    if V8D_EVIDENCE_GRAPH:
        blocks.append(
            "**Evidence Graph (v8d):** The Working Memory shows `[Evidence Graph]` — entities "
            "(names, dates, years) and which docs they appear in. Bridge entities (in multiple "
            "docs) are high-value signals. Singleton entities (in only 1 doc) often indicate "
            "gaps — consider follow-up searches for related entities."
        )
    if V8D_VERIFY_TOOL:
        blocks.append(
            "**Verify tool (v8d):** Use `verify(doc_ids, claim)` BEFORE tagging docs as "
            "`very_high` on multi-constraint queries. It returns yes/no for each doc, "
            "letting you confirm a doc actually satisfies ALL criteria rather than just one."
        )
    if V8D_TOKEN_BUDGET_MARKER:
        blocks.append(
            "**Context budget (v8d):** Each observation ends with `[Context: X/Y]`. When X/Y "
            "is above 75%, wrap up your search within 2-3 more turns. When above 90%, call "
            "`end_search` NOW."
        )
    if not blocks:
        return ""
    return "\n\n".join(blocks) + "\n"


def get_system_prompt(query: str) -> str:
    v8d_addendum = _v8d_prompt_addendum()
    v8d_tool_line = (
        "- **verify**(doc_ids, claim): Check if docs support a specific claim. "
        "Use before tagging as very_high.\n" if V8D_VERIFY_TOOL else ""
    )
    return f"""You are a retrieval subagent. Find and retrieve the most relevant documents from a corpus to help answer a question. You do NOT answer questions yourself — you only find relevant documents.

<query>
{query}
</query>

**Available Tools:**
- **fan_out_search**(queries): Run up to {FAN_OUT_MAX_QUERIES} diverse queries in parallel.
- **search_corpus**(query): Single semantic + keyword search.
- **grep_corpus**(pattern): Exact regex pattern matching on the corpus. Use for specific names, dates, numbers, or exact phrases.
- **read_document**(doc_id): Read a document's full content. Use liberally — seeing full text reveals connections that snippets miss.
- **review_docs**(doc_ids): Re-read previously-found documents from memory (free, no corpus call).
- **curate**(add_ids, remove_ids{', importance' if V8D_IMPORTANCE_TAGGING else ''}): Update your curated set (max {MAX_CURATED_DOCS} docs). These are your final output.
{v8d_tool_line}- **end_search**(reasoning): Submit your curated set and conclude.

**Context:**
Your context has two parts:
1. **Working Memory** — curated set with {"full content" if CURATED_DOC_CHARS > 0 else "snippets"}, document pool with snippets, and search history.
2. **Recent Turns** — full detail of your last {RECENT_K} actions and results.

**Two-Tier Memory:**
- Your Working Memory shows {"full content for curated docs and brief snippets for uncurated pool docs" if CURATED_DOC_CHARS > 0 else "doc IDs + brief snippets for ALL previously found docs"}.
- Use **review_docs** to re-read the full text of any document from memory without re-searching.
- This is useful when you want to revisit a doc you found earlier.

**Step 1 — Decompose the Query:**
Before your first search, identify the key constraints in the query (entities, dates, relationships, distinctive facts). Use the most specific/unique constraint for your first search.

**Step 2 — Core Loop (ALWAYS follow this rhythm):**
1. **Search** — use fan_out_search, search_corpus, or grep_corpus.
2. **Curate immediately** — after EVERY search, call curate to add ALL plausibly relevant docs from the results. Do NOT do two searches in a row without curating in between.
3. **Repeat** — search a different angle, then curate again.
4. **Refine** — use review_docs or read_document to revisit docs, then curate to adjust.
5. **End** — call end_search when you've thoroughly covered the query.

You have up to **{MAX_TURNS} turns**. Use them — thorough coverage matters more than speed. Don't end early if there are unexplored angles.

The search → curate rhythm is critical. Results are freshest right after a search. If you delay curation, those results scroll out of your recent context and you lose the detail needed to decide relevance.

**Search Strategy:**
- Keep queries SHORT (5-12 words). Vary angles — don't repeat similar queries.
- **NEVER repeat queries** from your search history. Use completely different wording.
- **Decompose complex queries** into distinct searchable facets. Search each facet separately.
- **Use grep_corpus** for specific names, dates, numbers, codes, or exact phrases from the query. grep often finds what semantic search misses.
- **Use read_document liberally** — full text reveals connections that snippets hide. If a doc partially matches, read it fully. High-recall agents read more documents.

**Curation Strategy:**
- **Curate aggressively** — add ALL plausibly relevant docs. Include borderline docs. It's ALWAYS better to over-curate than under-curate. Aim for 3-8 adds per curate call.
- **Never remove** docs unless you are certain they are completely irrelevant after reading their full text.
- Keep analysis concise (2-3 paragraphs max). Focus on what to do next.

**Backtracking — Critical Reasoning Skill:**
When you notice signs of being stuck, you MUST backtrack in your reasoning:
- **Stale pool**: If your last 2-3 searches added few or no new docs, STOP. In your reasoning, explicitly state: "My current search angle is exhausted. Let me rethink." Then try a completely different query decomposition.
- **Re-reading loop**: If you find yourself reading/reviewing the same docs repeatedly, STOP. Reason about what specific information you're missing and search for it directly.
- **Wrong entity**: If results consistently don't match, question your assumptions. The query may require interpreting an entity differently (e.g., a person's maiden name, an alternate spelling, a related entity).
- **Missed facet**: Re-read the query carefully. Identify any constraint you haven't explicitly searched for yet.

Backtracking is a REASONING step: in your analysis, explain (1) what isn't working, (2) why, and (3) your new strategy. Then act on it.

{v8d_addendum}"""


# ═══════════════════════════════════════════════════════════════════════════════
# v8d Contribution 1: BM25 Sentence-Level Compression (local, free)
# ═══════════════════════════════════════════════════════════════════════════════

_SENTENCE_SPLITTER = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


def compress_chunk(query: str, chunk_text: str, k: int = SENTENCE_COMPRESS_K) -> str:
    """Return the top-k query-relevant sentences from chunk_text, preserving order.

    Uses BM25 scores of query tokens against sentence tokens. If BM25 is
    unavailable or the chunk has <= k sentences, returns the chunk unchanged.
    Cost is purely local (microseconds per chunk).
    """
    if not _HAS_BM25 or not chunk_text or not query:
        return chunk_text
    text = chunk_text.strip()
    if not text:
        return chunk_text
    sentences = [s.strip() for s in _SENTENCE_SPLITTER.split(text) if s.strip()]
    if len(sentences) <= k:
        return chunk_text
    try:
        tokenized = [s.lower().split() for s in sentences]
        bm25 = BM25Okapi(tokenized)
        scores = bm25.get_scores(query.lower().split())
        top_idx = sorted(
            sorted(range(len(sentences)), key=lambda i: -scores[i])[:k]
        )
        return " ".join(sentences[i] for i in top_idx)
    except Exception:
        return chunk_text


# ═══════════════════════════════════════════════════════════════════════════════
# v8d Contribution 5: Semantic Content-Hash Deduplication (MinHash LSH)
# ═══════════════════════════════════════════════════════════════════════════════


class ContentDedupTracker:
    """Near-duplicate detection over chunk text using MinHash LSH.

    Used to prevent the pool from filling with near-identical chunks (common in
    SEC filings where the same boilerplate appears across 10-Ks). No-op if the
    `datasketch` package is missing, so SFT generation without it still works.
    """

    _TOKEN_RE = re.compile(r"[a-z0-9]+")

    def __init__(
        self,
        threshold: float = MINHASH_DEDUP_THRESHOLD,
        num_perm: int = MINHASH_NUM_PERM,
    ):
        self.enabled = _HAS_MINHASH and V8D_CONTENT_DEDUP
        self.num_perm = num_perm
        self._fingerprints: Set[str] = set()  # fallback for when LSH unavailable
        if self.enabled:
            try:
                self.lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
            except Exception:
                self.enabled = False
                self.lsh = None
        else:
            self.lsh = None
        self._inserted: Set[str] = set()

    def _make_minhash(self, text: str):
        mh = MinHash(num_perm=self.num_perm)
        tokens = self._TOKEN_RE.findall(text.lower())
        # use 5-grams of tokens for robust fuzzy match
        for i in range(len(tokens) - 4):
            shingle = " ".join(tokens[i:i + 5])
            mh.update(shingle.encode("utf-8"))
        # fallback: also add raw tokens if too short for shingles
        if len(tokens) < 5:
            for t in tokens:
                mh.update(t.encode("utf-8"))
        return mh

    def _fallback_fingerprint(self, text: str) -> str:
        # 256-bit truncated shingled hash, reasonable near-dup detector when MinHash is absent.
        norm = " ".join(self._TOKEN_RE.findall(text.lower()))[:4000]
        return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]

    def is_duplicate(self, chunk_id: str, text: str) -> bool:
        """Return True if this text is near-duplicate of something already tracked.

        Always inserts on first call (returns False). Subsequent near-duplicates
        return True without re-inserting.
        """
        if not text or len(text.strip()) < 40:
            return False
        if chunk_id in self._inserted:
            return False
        if self.enabled and self.lsh is not None:
            try:
                mh = self._make_minhash(text)
                matches = self.lsh.query(mh)
                if matches:
                    return True
                self.lsh.insert(chunk_id, mh)
                self._inserted.add(chunk_id)
                return False
            except Exception:
                pass
        # Fallback path: exact normalized fingerprint only
        fp = self._fallback_fingerprint(text)
        if fp in self._fingerprints:
            return True
        self._fingerprints.add(fp)
        self._inserted.add(chunk_id)
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# v8d Contribution 2: Evidence Graph (entity ↔ doc co-occurrence)
# ═══════════════════════════════════════════════════════════════════════════════


class EvidenceGraph:
    """Lightweight entity-document co-occurrence graph.

    Surfaces in the observation a compact summary of which entities (proper nouns,
    years, dates) appear across multiple docs ("bridge" docs) vs only one
    ("singletons"). Helps the model plan multi-hop searches and identify which
    docs are likely relevant for the answer.

    Extraction is intentionally conservative (proper nouns, years, dates).
    """

    _ENTITY_RE = re.compile(
        r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}|\d{4}(?:s)?|\d{1,2}/\d{1,2}/\d{2,4})\b"
    )
    _STOPWORDS = frozenset({
        "The", "This", "That", "A", "An", "It", "He", "She", "In", "On", "At",
        "For", "By", "With", "To", "From", "I", "We", "You", "They", "But",
        "However", "Moreover", "Therefore", "Furthermore", "Additionally",
        "Page", "Section", "Chapter", "Figure", "Table", "Document",
    })

    def __init__(self):
        self.entity_to_docs: Dict[str, Set[str]] = {}
        self.doc_to_entities: Dict[str, Set[str]] = {}

    def _extract_entities(self, text: str) -> Set[str]:
        ents: Set[str] = set()
        for m in self._ENTITY_RE.finditer(text[:8000]):  # cap for speed
            ent = m.group(0).strip()
            if len(ent) < 2:
                continue
            if ent in self._STOPWORDS:
                continue
            # drop single-word stopwords and pure 1-char tokens
            ents.add(ent)
        return ents

    def update_from_doc(self, doc_id: str, text: str) -> None:
        if not text or doc_id in self.doc_to_entities:
            return
        ents = self._extract_entities(text)
        if not ents:
            return
        self.doc_to_entities[doc_id] = ents
        for e in ents:
            self.entity_to_docs.setdefault(e, set()).add(doc_id)

    def render_summary(self, max_entities: int = EVIDENCE_GRAPH_MAX_ENTITIES) -> str:
        """Render a compact human-readable summary for injection into observations."""
        if not self.entity_to_docs:
            return ""
        # Rank entities by number of docs they appear in (bridging = higher value)
        ranked = sorted(
            self.entity_to_docs.items(),
            key=lambda kv: (-len(kv[1]), kv[0]),
        )
        bridge = [(e, docs) for e, docs in ranked if len(docs) >= 2][:max_entities]
        singleton_count = sum(1 for _, docs in ranked if len(docs) == 1)
        if not bridge:
            if singleton_count == 0:
                return ""
            return f"[Evidence Graph] 0 bridge entities, {singleton_count} singleton entities."
        lines = ["[Evidence Graph] Entities appearing in multiple docs (bridges):"]
        for ent, docs in bridge:
            doc_list = sorted(docs)[:5]
            extra = f" (+{len(docs) - 5} more)" if len(docs) > 5 else ""
            lines.append(f"  {ent}: {', '.join(doc_list)}{extra}")
        if singleton_count > 0:
            lines.append(f"  ({singleton_count} entities in only 1 doc — potential hops)")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Working Memory
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class WorkingMemorySnapshot:
    """Immutable snapshot of working memory at a point in time."""
    turn_number: int
    curated_ids: List[str]
    curated_notes: Dict[str, str]
    pool_ids: List[str]
    search_history: List[str]
    text: str


class WorkingMemory:
    """Two-tier memory: inner (compact WM in context) + outer (doc_store with full text).

    The WM text (~800-1500 tokens) shows doc IDs + snippets so the model can decide
    what to review/curate without re-searching. Full text is in doc_store, accessible
    via review_docs() at zero corpus cost.
    """

    def __init__(self, query: str, normalize_ids: bool = True):
        self.query = query
        self.turn_number = 0
        self.curated_ids: List[str] = []
        self.curated_notes: Dict[str, str] = {}
        self.pool_ids: List[str] = []
        self.pool_id_set: Set[str] = set()
        self.search_history: List[str] = []
        self.doc_store: Dict[str, Dict[str, str]] = {}
        self.normalize_ids = normalize_ids

        # ── v8d additions (all no-op unless respective flags are set) ───────
        self.curated_importance: Dict[str, str] = {}  # doc_id -> importance level
        self.rerank_instruction: Optional[str] = None  # per-episode, set by env
        self.auto_populated: bool = False  # tracks first-search auto-populate
        self.content_dedup = ContentDedupTracker() if V8D_CONTENT_DEDUP else None
        self.evidence_graph = EvidenceGraph() if V8D_EVIDENCE_GRAPH else None
        # Counter for dup hits (diagnostic / metric)
        self.dup_skipped: int = 0

    def _normalize_id(self, chunk_id: str) -> str:
        """Normalize chunk ID to base doc ID (strip trailing _N suffix).

        Handles both single-underscore (web_doc_123_5 -> web_doc_123) and
        double-underscore (12486__0 -> 12486) chunk-id formats.

        If the ID is already in the pool (i.e. already normalized), returns as-is
        to avoid double-stripping during curate calls.
        """
        if not self.normalize_ids or "_" not in chunk_id:
            return chunk_id
        if chunk_id in self.pool_id_set:
            return chunk_id
        from cosmos_retriever.tasks import CHUNK_ID_SUFFIX_PATTERN
        m = CHUNK_ID_SUFFIX_PATTERN.match(chunk_id)
        if m and "/" not in chunk_id:
            return m.group("base")
        return chunk_id.rsplit("_", 1)[0]

    def get_pool_size(self) -> int:
        return len(self.pool_ids)

    def add_to_pool(self, chunk_ids: List[str],
                    doc_texts: Optional[Dict[str, str]] = None) -> int:
        """Add docs to pool and doc_store. Returns count of *newly added* docs.

        v8d: consults ContentDedupTracker before adding (content-level near-dup
        suppression) and updates the EvidenceGraph with entity info. Both are
        no-ops unless the respective v8d feature flags are set.
        """
        added = 0
        for cid in chunk_ids:
            doc_id = self._normalize_id(cid)

            # Resolve text for this doc (if any)
            text = ""
            if doc_texts:
                text = doc_texts.get(cid, doc_texts.get(doc_id, "")) or ""

            # v8d: dedup on content, *before* adding to pool. We check against the
            # normalized doc_id so that multiple chunks of the same SEC filing
            # with slight boilerplate variation don't all make it in.
            if (
                self.content_dedup is not None
                and text
                and doc_id not in self.pool_id_set  # never dedup an already-known doc
                and self.content_dedup.is_duplicate(doc_id, text)
            ):
                self.dup_skipped += 1
                continue

            if doc_id not in self.pool_id_set:
                self.pool_ids.append(doc_id)
                self.pool_id_set.add(doc_id)
                added += 1
            if text and doc_id not in self.doc_store:
                self.doc_store[doc_id] = {
                    "full_text": text,
                    "snippet": text[:DOC_SNIPPET_CHARS].replace("\n", " ").strip(),
                }
                # v8d: update evidence graph from the newly-seen doc text
                if self.evidence_graph is not None:
                    self.evidence_graph.update_from_doc(doc_id, text)
        return added

    def review_docs(self, doc_ids: List[str]) -> str:
        """Retrieve full text from outer memory. Free — no corpus call."""
        parts = []
        for did in doc_ids[:MAX_REVIEW_DOCS]:
            if did in self.doc_store:
                parts.append(
                    f"# DOCUMENT ID: {did}\n{self.doc_store[did].get('full_text', '')}"
                )
            else:
                parts.append(f"# DOCUMENT ID: {did}\n(not found in memory)")
        return "\n\n".join(parts) if parts else "No matching docs in memory."

    def curate(
        self,
        add_ids: List[str],
        remove_ids: List[str],
        notes: Optional[Dict[str, str]] = None,
        importance: Optional[Dict[str, str]] = None,
    ) -> str:
        """Update the curated set. Returns a status string with capacity feedback.

        v8d subtractive behavior (enabled via V8D_SUBTRACTIVE_CURATION):
        - Each added doc gets an importance tag ('very_high'|'high'|'fair'|'low');
          missing tags default to 'fair'.
        - When the set is full and we try to add a doc that outranks an existing
          low-importance one, we evict the lowest-importance doc first.
        - When removing a doc, its importance entry is also cleared.
        """
        # ── Remove phase ───────────────────────────────────────────────────
        remove_set = set(str(x) for x in remove_ids if x)
        # Normalize remove_ids too so the model can pass either chunk or doc ids
        remove_set_norm = {self._normalize_id(x) for x in remove_set}
        remove_set_all = remove_set | remove_set_norm
        self.curated_ids = [x for x in self.curated_ids if x not in remove_set_all]
        for rid in remove_set_all:
            self.curated_notes.pop(rid, None)
            self.curated_importance.pop(rid, None)

        # Normalize importance dict keys so model can pass chunk_ids too
        imp_norm: Dict[str, str] = {}
        if importance and V8D_IMPORTANCE_TAGGING:
            for k, v in importance.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    continue
                v = v.strip().lower()
                if v not in VALID_IMPORTANCE:
                    v = "fair"
                imp_norm[self._normalize_id(k.strip())] = v

        # ── Add phase ──────────────────────────────────────────────────────
        existing = set(self.curated_ids)
        dropped: List[str] = []
        evicted: List[str] = []

        for doc_id in add_ids:
            doc_id = str(doc_id).strip()
            doc_id = self._normalize_id(doc_id)
            if not doc_id or doc_id in existing:
                # Allow importance re-tagging of an already-curated doc
                if doc_id in existing and doc_id in imp_norm:
                    self.curated_importance[doc_id] = imp_norm[doc_id]
                continue

            incoming_tag = imp_norm.get(doc_id, "fair")

            if len(self.curated_ids) < MAX_CURATED_DOCS:
                self.curated_ids.append(doc_id)
                existing.add(doc_id)
                if V8D_IMPORTANCE_TAGGING:
                    self.curated_importance[doc_id] = incoming_tag
                if notes and doc_id in notes:
                    self.curated_notes[doc_id] = notes[doc_id]
                continue

            # At capacity: try to evict a lower-importance doc if enabled
            if V8D_SUBTRACTIVE_CURATION:
                incoming_rank = _IMPORTANCE_RANK.get(incoming_tag, 2)
                # find lowest-importance doc in current curated set
                worst_id = None
                worst_rank = -1
                for cid in self.curated_ids:
                    tag = self.curated_importance.get(cid, "fair")
                    rank = _IMPORTANCE_RANK.get(tag, 2)
                    if rank > worst_rank:
                        worst_rank = rank
                        worst_id = cid
                if worst_id is not None and worst_rank > incoming_rank:
                    # evict
                    self.curated_ids = [c for c in self.curated_ids if c != worst_id]
                    self.curated_importance.pop(worst_id, None)
                    self.curated_notes.pop(worst_id, None)
                    existing.discard(worst_id)
                    evicted.append(worst_id)
                    # now add
                    self.curated_ids.append(doc_id)
                    existing.add(doc_id)
                    self.curated_importance[doc_id] = incoming_tag
                    continue

            dropped.append(doc_id)

        n = len(self.curated_ids)
        if V8D_IMPORTANCE_TAGGING and self.curated_importance:
            # Render curated list sorted by importance for visibility
            def _srt(i):
                return (_IMPORTANCE_RANK.get(self.curated_importance.get(i, "fair"), 2), i)
            rendered = [
                f"{i}[{self.curated_importance.get(i, 'fair')}]"
                for i in sorted(self.curated_ids, key=_srt)
            ]
        else:
            rendered = self.curated_ids
        ids_str = ", ".join(rendered) if rendered else "(empty)"
        result = f"Curated set updated ({n}/{MAX_CURATED_DOCS}): {ids_str}"
        if evicted:
            result += (
                f"\n[EVICTED low-importance] {len(evicted)} doc(s): "
                f"{', '.join(evicted[:5])}"
            )
        if dropped:
            result += (
                f"\n[CAPACITY] Set is FULL and no evictable lower-importance docs — "
                f"{len(dropped)} doc(s) NOT added: {', '.join(dropped[:5])}"
            )
        return result

    def add_search_record(self, tool_name: str, params_summary: str,
                          num_results: int, num_new: int = -1,
                          num_new_curated: int = 0) -> None:
        """Record a search action with yield info.

        num_new: number of *novel* docs added to pool (-1 = unknown/not tracked).
        """
        entry = f"T{self.turn_number}: {tool_name}({params_summary}) → {num_results} docs"
        if num_new >= 0:
            entry += f", {num_new} new"
        if num_new_curated > 0:
            entry += f", +{num_new_curated} curated"
        self.search_history.append(entry)

    def advance_turn(self) -> None:
        self.turn_number += 1

    def snapshot(self) -> WorkingMemorySnapshot:
        return WorkingMemorySnapshot(
            turn_number=self.turn_number,
            curated_ids=list(self.curated_ids),
            curated_notes=dict(self.curated_notes),
            pool_ids=list(self.pool_ids),
            search_history=list(self.search_history),
            text=self.to_text(),
        )

    _POOL_DISPLAY_FULL = 50
    _POOL_DISPLAY_COMPACT = 30

    def to_text(self) -> str:
        """Render compact WM text for inclusion in model context."""
        lines = [
            f"== Working Memory (summarizing turns 0-{self.turn_number}) ==",
            f'Query: "{self.query}"',
            "",
        ]

        # Curated set — show full content when CURATED_DOC_CHARS > 0
        n_curated = len(self.curated_ids)
        lines.append(f"Curated Set ({n_curated}/{MAX_CURATED_DOCS}):")
        if self.curated_ids:
            # v8d: render grouped by importance (very_high → high → fair → low)
            if V8D_IMPORTANCE_TAGGING and self.curated_importance:
                def _rank(i: str) -> Tuple[int, int]:
                    return (
                        _IMPORTANCE_RANK.get(self.curated_importance.get(i, "fair"), 2),
                        self.curated_ids.index(i) if i in self.curated_ids else 0,
                    )
                ordered = sorted(self.curated_ids, key=_rank)
                last_tag: Optional[str] = None
                for doc_id in ordered:
                    tag = self.curated_importance.get(doc_id, "fair")
                    if tag != last_tag:
                        lines.append(f"  -- {tag} --")
                        last_tag = tag
                    store = self.doc_store.get(doc_id, {})
                    note = self.curated_notes.get(doc_id, "")
                    note_str = f" -- {note}" if note else ""
                    if CURATED_DOC_CHARS > 0:
                        full = store.get("full_text", store.get("snippet", ""))
                        content = full[:CURATED_DOC_CHARS].strip()
                        lines.append(f"  [*] {doc_id}{note_str}:")
                        lines.append(f"      {content}")
                    else:
                        snippet = store.get("snippet", "")
                        lines.append(f"  [*] {doc_id}: {snippet}{note_str}")
            else:
                for doc_id in self.curated_ids:
                    store = self.doc_store.get(doc_id, {})
                    note = self.curated_notes.get(doc_id, "")
                    note_str = f" -- {note}" if note else ""
                    if CURATED_DOC_CHARS > 0:
                        full = store.get("full_text", store.get("snippet", ""))
                        content = full[:CURATED_DOC_CHARS].strip()
                        lines.append(f"  [*] {doc_id}{note_str}:")
                        lines.append(f"      {content}")
                    else:
                        snippet = store.get("snippet", "")
                        lines.append(f"  [*] {doc_id}: {snippet}{note_str}")
        else:
            lines.append("  (empty -- use curate tool to add relevant docs)")
        lines.append("")

        # Pool: most-recent uncurated docs first (recent finds are most actionable)
        curated_set = set(self.curated_ids)
        uncurated = [pid for pid in self.pool_ids if pid not in curated_set]
        lines.append(
            f"Document Pool: {len(self.pool_ids)} docs total, {len(uncurated)} uncurated"
        )
        if uncurated:
            recent = list(reversed(uncurated[-self._POOL_DISPLAY_FULL:]))
            for did in recent:
                snippet = self.doc_store.get(did, {}).get("snippet", "")
                lines.append(f"  [ ] {did}: {snippet}")
            hidden = len(uncurated) - len(recent)
            if hidden > 0:
                older = uncurated[:hidden]
                id_str = ", ".join(older[:self._POOL_DISPLAY_COMPACT])
                if hidden > self._POOL_DISPLAY_COMPACT:
                    id_str += f" (+{hidden - self._POOL_DISPLAY_COMPACT} more)"
                lines.append(f"  Earlier uncurated ({hidden}): {id_str}")
        lines.append("")

        # Search history (last 12 entries)
        if self.search_history:
            lines.append("Search History:")
            history = self.search_history[-12:]
            if len(self.search_history) > 12:
                lines.append(
                    f"  ... ({len(self.search_history) - 12} earlier searches)"
                )
            for entry in history:
                lines.append(f"  {entry}")
        else:
            lines.append("Search History: (no searches yet)")

        lines.append("")
        lines.append("Use review_docs(doc_ids) to re-read any document from your pool.")

        # v8d: evidence graph summary
        if self.evidence_graph is not None:
            eg_text = self.evidence_graph.render_summary()
            if eg_text:
                lines.append("")
                lines.append(eg_text)

        # v8d: dedup signal (helps the model realize SEC corpora have dups)
        if self.content_dedup is not None and self.dup_skipped > 0:
            lines.append(
                f"[Dedup] {self.dup_skipped} near-duplicate chunk(s) auto-suppressed."
            )

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Harmony Message Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def action_observation_to_messages(
    action: Action,
    observation: Observation,
    compress: bool = False,
    max_analysis_chars: int = MAX_ANALYSIS_CHARS_OLDER,
) -> List[Message]:
    """Convert one (action, observation) pair to Harmony messages.

    If compress=True, truncates the analysis/reasoning to max_analysis_chars.
    Used for older turns in the recent window to prevent stale context pollution.

    Produces: [assistant analysis?] [assistant tool_call] [tool result]
    """
    if compress and action.reasoning and len(action.reasoning) > max_analysis_chars:
        action = copy.copy(action)
        action.reasoning = (
            action.reasoning[:max_analysis_chars] + "...(truncated)"
        )

    messages: List[Message] = []
    tool_use_source_to_name: Dict[str, str] = {}

    # --- Action: reasoning (analysis channel) ---
    if action.reasoning:
        messages.append(
            Message.from_role_and_content(Role.ASSISTANT, action.reasoning)
            .with_channel("analysis")
        )

    # --- Action: tool call(s) (commentary channel) ---
    if len(action.tools) > 1:
        tool_calls = []
        for tool, params, source in action.as_iter():
            if isinstance(tool, UserTextTool):
                messages.append(
                    Message.from_role_and_content(Role.ASSISTANT, params["text"])
                    .with_channel("final")
                )
            else:
                tool_calls.append({
                    "tool_name": tool.tool_schema.name,
                    "parameters": params,
                })
                tool_use_source_to_name[source] = tool.tool_schema.name
        if tool_calls:
            messages.append(
                Message.from_role_and_content(
                    Role.ASSISTANT, json.dumps(tool_calls)
                )
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
                Message.from_role_and_content(Role.ASSISTANT, params["text"])
                .with_channel("final")
            )
        else:
            messages.append(
                Message.from_role_and_content(Role.ASSISTANT, json.dumps(params))
                .with_channel("commentary")
                .with_recipient("functions." + tool.tool_schema.name)
                .with_content_type("<|constrain|>json")
            )
            tool_use_source_to_name[source] = "functions." + tool.tool_schema.name

    # --- Observation: tool result(s) ---
    if len(observation.observations) > 1:
        tool_results = []
        for obs_text, obs_source in zip(
            observation.observations, observation.sources
        ):
            tool_name = tool_use_source_to_name.get(obs_source, "unknown")
            if len(obs_text) > MAX_OBS_CHARS:
                obs_text = (
                    obs_text[:MAX_OBS_CHARS]
                    + f"\n... (truncated, {len(obs_text)} chars total)"
                )
            tool_results.append({
                "type": "tool_result",
                "name": tool_name,
                "content": [obs_text],
            })
        messages.append(
            Message.from_author_and_content(
                Author(role=Role.TOOL, name="functions.multi_tool_use"),
                json.dumps(tool_results),
            )
            .with_channel("commentary")
            .with_recipient("assistant")
        )
    elif len(observation.observations) == 1:
        obs_source = observation.sources[0]
        obs_text = observation.observations[0]
        if len(obs_text) > MAX_OBS_CHARS:
            obs_text = (
                obs_text[:MAX_OBS_CHARS]
                + f"\n... (truncated, {len(obs_text)} chars total)"
            )
        if obs_source == "user":
            messages.append(
                Message.from_role_and_content(Role.USER, obs_text)
            )
        else:
            tool_name = tool_use_source_to_name.get(obs_source, "unknown")
            messages.append(
                Message.from_author_and_content(
                    Author(role=Role.TOOL, name=tool_name), obs_text,
                )
                .with_channel("commentary")
                .with_recipient("assistant")
            )

    return messages


# ═══════════════════════════════════════════════════════════════════════════════
# Context Assembly — THE single function for building model input
# ═══════════════════════════════════════════════════════════════════════════════

def build_context(
    system_prompt: str,
    wm_text: Optional[str],
    recent_actions: List[Action],
    recent_observations: List[Observation],
    result_summaries: Optional[List[str]] = None,
) -> Conversation:
    """Build the hybrid context: [system + tools + query + WM? + recent turns + summaries].

    This is the ONLY context assembly function in the codebase. SFT generation,
    SFT training, and RL training all use it, guaranteeing identical formats.

    Args:
        system_prompt: The system prompt including the query.
        wm_text: Working Memory text for turns older than RECENT_K. None for early turns.
        recent_actions: The most recent K (or fewer) Action objects.
        recent_observations: Matching Observation objects.
        result_summaries: One per recent turn. Injected as user messages between turns
            (except after the latest turn). None to skip injection.
    """
    system_message = (
        SystemContent.new()
        .with_reasoning_effort(ReasoningEffort.HIGH)
        .with_conversation_start_date("2026-04-01")
    )
    messages = [Message.from_role_and_content(Role.SYSTEM, system_message)]

    developer_message = DeveloperContent.new().with_function_tools(get_tool_descriptions())
    messages.append(Message.from_role_and_content(Role.DEVELOPER, developer_message))

    messages.append(Message.from_role_and_content(Role.USER, system_prompt))

    if wm_text:
        messages.append(Message.from_role_and_content(Role.USER, wm_text))

    assert len(recent_actions) == len(recent_observations), (
        f"Mismatch: {len(recent_actions)} actions vs {len(recent_observations)} obs"
    )
    n_recent = len(recent_actions)
    for i, (action, observation) in enumerate(
        zip(recent_actions, recent_observations)
    ):
        is_last = (i == n_recent - 1)
        turn_msgs = action_observation_to_messages(
            action, observation, compress=(not is_last),
        )
        messages.extend(turn_msgs)

        # Inject result summary after each turn except the latest (the model
        # hasn't acted on its latest results yet, so no summary needed).
        if result_summaries and i < len(result_summaries) and not is_last:
            summary = result_summaries[i]
            if summary:
                messages.append(
                    Message.from_role_and_content(Role.USER, summary)
                )

    return Conversation(messages=messages)


def render_context_within_budget(
    system_prompt: str,
    wm_text: Optional[str],
    recent_actions: List[Action],
    recent_observations: List[Observation],
    result_summaries: Optional[List[str]],
    enc: HarmonyEncoding,
    budget: int = PROMPT_TOKEN_BUDGET,
    nudge_prompt: Optional[str] = None,
    retry_prompt: Optional[str] = None,
) -> List[int]:
    """Render context tokens guaranteed to be within token budget.

    This is the ONLY token rendering function. ALL code paths (normal step,
    format retry, initial observation) go through here. No unprotected path.

    Progressive truncation strategy:
    1. Normal render (300-char analysis for older turns)
    2. Truncate WM pool section
    3. Aggressive: 100-char analysis + 2000-char WM
    4. Drop oldest recent turns one at a time
    5. Minimal context (system + query only)
    """
    def _append_tail(conv: Conversation) -> Conversation:
        msgs = list(conv.messages)
        if nudge_prompt:
            msgs.append(Message.from_role_and_content(Role.USER, nudge_prompt))
        if retry_prompt:
            msgs.append(Message.from_role_and_content(Role.USER, retry_prompt))
        return Conversation(messages=msgs)

    # --- Pass 1: normal render ---
    conv = build_context(
        system_prompt, wm_text, recent_actions, recent_observations,
        result_summaries,
    )
    conv = _append_tail(conv)
    tokens = enc.render_conversation(conv)
    if len(tokens) <= budget:
        return tokens

    # --- Pass 2: truncate WM pool section ---
    truncated_wm = wm_text
    if truncated_wm and len(truncated_wm) > 1500:
        pool_start = truncated_wm.find("Document Pool:")
        hist_start = truncated_wm.find("Search History:")
        if pool_start > 0 and hist_start > pool_start:
            pool_section = truncated_wm[pool_start:hist_start]
            overshoot = len(tokens) - budget
            chars_to_cut = min(len(pool_section) - 100, overshoot * 3)
            if chars_to_cut > 0:
                new_pool = (
                    pool_section[:len(pool_section) - chars_to_cut]
                    + "\n  ... (truncated for context)\n\n"
                )
                truncated_wm = (
                    truncated_wm[:pool_start] + new_pool
                    + truncated_wm[hist_start:]
                )

        conv = build_context(
            system_prompt, truncated_wm, recent_actions, recent_observations,
            result_summaries,
        )
        conv = _append_tail(conv)
        tokens = enc.render_conversation(conv)
        if len(tokens) <= budget:
            return tokens

    # --- Pass 3: aggressive — 100-char analysis, 2000-char WM ---
    aggressive_wm = truncated_wm
    if aggressive_wm and len(aggressive_wm) > 2000:
        aggressive_wm = aggressive_wm[:2000] + "\n...(WM truncated)"

    compressed_actions = []
    for action in recent_actions:
        a = copy.copy(action)
        if a.reasoning and len(a.reasoning) > 100:
            a.reasoning = a.reasoning[:100] + "...(truncated)"
        compressed_actions.append(a)

    conv = build_context(
        system_prompt, aggressive_wm, compressed_actions, recent_observations,
        result_summaries,
    )
    conv = _append_tail(conv)
    tokens = enc.render_conversation(conv)
    if len(tokens) <= budget:
        return tokens

    # --- Pass 4: drop oldest recent turns one at a time ---
    drop_actions = list(compressed_actions)
    drop_obs = list(recent_observations)
    drop_summaries = list(result_summaries) if result_summaries else []

    while len(drop_actions) > 1:
        drop_actions = drop_actions[1:]
        drop_obs = drop_obs[1:]
        if drop_summaries:
            drop_summaries = drop_summaries[1:]

        conv = build_context(
            system_prompt, aggressive_wm, drop_actions, drop_obs,
            drop_summaries or None,
        )
        conv = _append_tail(conv)
        tokens = enc.render_conversation(conv)
        if len(tokens) <= budget:
            return tokens

    # --- Pass 5: minimal context (system + query only) ---
    conv = build_context(system_prompt, None, [], [], None)
    if retry_prompt:
        msgs = list(conv.messages)
        msgs.append(Message.from_role_and_content(Role.USER, retry_prompt))
        conv = Conversation(messages=msgs)
    tokens = enc.render_conversation(conv)
    assert len(tokens) <= budget, (
        f"Even minimal context exceeds budget: {len(tokens)} > {budget}"
    )
    return tokens


# ═══════════════════════════════════════════════════════════════════════════════
# Result Summary Builder
# ═══════════════════════════════════════════════════════════════════════════════

_SEARCH_TOOLS = frozenset({"fan_out_search", "search_corpus", "grep_corpus", "read_document"})


HARNESS_PRESCRIPTIVE = os.environ.get("HARNESS_PRESCRIPTIVE", "1") == "1"


def build_result_summary(
    obs_text: str,
    tool_names: List[str],
    wm: WorkingMemory,
    turns_since_curate: int,
    tool_types_used: Set[str],
    current_turn: int,
    pool_size_before: int,
) -> str:
    """Build a concise, factual result summary (~100-150 tokens).

    Injected as a user message between turns to force the model to acknowledge
    what happened and adapt its strategy. Entirely programmatic — no LLM call.

    When HARNESS_PRESCRIPTIVE=0 (e.g. during later RL training), the
    prescriptive [ACTION REQUIRED]/[WARN]/[NEXT] messages are omitted to allow
    the model more exploration freedom. Factual status and tips are always kept.

    Args:
        pool_size_before: Pool size BEFORE this turn's add_to_pool(). This lets
            us accurately report novel vs repeat docs (fixes the bug where
            novel_count was always 0 because add_to_pool ran first).
    """
    lines: List[str] = []
    tool_str = ", ".join(tool_names) if tool_names else "unknown"
    is_search_turn = any(t in _SEARCH_TOOLS for t in tool_names)

    # ── 1. Tool result + doc count ──────────────────────────────────────────
    new_doc_ids = re.findall(r'# DOCUMENT ID:\s*(\S+)', obs_text)
    pool_size_after = len(wm.pool_ids)
    novel_count = pool_size_after - pool_size_before

    if new_doc_ids:
        lines.append(
            f"[STATUS] {tool_str}: {len(new_doc_ids)} docs returned, "
            f"{novel_count} new. Pool: {pool_size_after} total."
        )
    elif is_search_turn:
        lines.append(f"[STATUS] {tool_str}: no new documents found.")
    elif "curate" in tool_names:
        lines.append("[STATUS] curate: curated set updated.")
    elif "review_docs" in tool_names:
        lines.append("[STATUS] review_docs: documents re-read from memory.")
    else:
        lines.append(f"[STATUS] {tool_str} completed.")

    # ── 2. Curated set status ───────────────────────────────────────────────
    n_curated = len(wm.curated_ids)
    n_pool = len(wm.pool_ids)
    uncurated = n_pool - n_curated
    if n_curated == 0:
        lines.append(
            f"[WARN] Curated set is EMPTY (0/{MAX_CURATED_DOCS}). "
            f"You have {n_pool} docs in your pool — curate ALL promising ones now."
        )
    else:
        curated_preview = ", ".join(wm.curated_ids[:5])
        if n_curated > 5:
            curated_preview += f" (+{n_curated - 5} more)"
        lines.append(f"Curated: {n_curated}/{MAX_CURATED_DOCS} [{curated_preview}].")
        if uncurated > 10 and n_curated < 8:
            lines.append(
                f"[TIP] {uncurated} uncurated docs in pool. "
                "Add ALL relevant ones — don't under-curate."
            )

    # ── 3. Curate-after-search reminder ─────────────────────────────────────
    if is_search_turn and HARNESS_PRESCRIPTIVE:
        if turns_since_curate >= 1:
            lines.append(
                "[ACTION REQUIRED] You just searched — now curate. Review these results "
                "and call curate to add ALL plausibly relevant docs before your next search."
            )
        if turns_since_curate >= 2:
            lines.append(
                "[WARN] Multiple consecutive searches without curating. "
                "Curate NOW before searching again."
            )

    # ── 4. Truncation detection → suggest read_document ─────────────────────
    if "[... truncated]" in obs_text or "truncated," in obs_text:
        truncated_docs = re.findall(
            r'# DOCUMENT ID:\s*(\S+).*?(?:\[\.\.\.\ truncated\]|truncated,)',
            obs_text, re.DOTALL,
        )
        if truncated_docs:
            lines.append(
                f"[TIP] Docs [{', '.join(truncated_docs[:3])}] were truncated. "
                "Use read_document(doc_id) to see full content."
            )
        else:
            lines.append(
                "[TIP] Some results were truncated. "
                "Use read_document(doc_id) to see full content."
            )

    # ── 5. Tool diversity / strategy suggestions ────────────────────────────
    if len(tool_types_used) == 1 and current_turn >= 3:
        only_tool = list(tool_types_used)[0]
        alternatives = [
            t for t in ["grep_corpus", "read_document", "review_docs", "curate"]
            if t != only_tool
        ]
        lines.append(
            f"[TIP] Only used {only_tool} so far. "
            f"Consider: {', '.join(alternatives[:2])}."
        )

    if ("grep_corpus" not in tool_types_used
            and current_turn >= 4
            and not is_search_turn):
        lines.append(
            "[TIP] You haven't used grep_corpus yet. "
            "Use it for specific names, dates, numbers, or exact phrases from the query."
        )

    if ("read_document" not in tool_types_used
            and current_turn >= 6
            and n_pool >= 5
            and not is_search_turn):
        lines.append(
            "[TIP] You haven't used read_document yet. "
            "Reading full text of partially-matching docs often reveals connections that snippets miss."
        )

    # ── 6. Consecutive search penalty warning ───────────────────────────────
    if turns_since_curate >= 2 and n_pool > 0 and HARNESS_PRESCRIPTIVE:
        lines.append(
            f"[WARN] {turns_since_curate} consecutive non-curate turns. "
            "You MUST curate before your next search."
        )

    # ── 7. Next action suggestions ──────────────────────────────────────────
    if HARNESS_PRESCRIPTIVE:
        suggestions = []
        if is_search_turn and turns_since_curate >= 1:
            suggestions.append("curate ALL relevant docs from these results NOW")
        elif n_curated == 0 and n_pool >= 3:
            suggestions.append("curate promising docs from your pool")

        if suggestions:
            lines.append("[NEXT] " + "; ".join(suggestions) + ".")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Reward Computation
# ═══════════════════════════════════════════════════════════════════════════════

def compute_reward(
    recall: float,
    precision: float,
    final_answer_recall: float,
    trajectory_recall: float,
    n_curated: int,
    turn: int,
    total_curate_calls: int,
    n_unique_tools: int,
    is_terminal: bool,
    trajectory_fa_recall: float = 0.0,
) -> Tuple[float, Dict[str, float]]:
    """Compute reward from pre-evaluated metrics. Pure function, no dataset dependency.

    The caller evaluates recall/precision using the appropriate dataset method
    and passes the results here. This keeps the reward function testable and
    decoupled from dataset specifics.

    Returns (reward, metrics_dict).

    Reward hierarchy:
      -0.5  = format error (caller handles this case separately)
      -0.2  = never curated (terminal only)
       0.001 = curated but found nothing
       0.1+  = productive episode
       ~2.0  = theoretical max (recall=1, precision=1, fa_found=1)

    Key components (v3 defaults):
      0.7 × F_beta(recall, precision, β=2)         outcome quality
      0.3 × trajectory_recall                      pool discovery signal
      1.0 × binary final-answer bonus              sparse success signal
      0.8 × final_answer_recall                    dense answer-curation signal
      0.4 × trajectory_fa_recall                   dense answer-discovery signal
     -0.35 × max(trajectory_fa_recall - final_answer_recall, 0)
                                                  penalize "answer in pool but not curated"
     -turn_penalty                                 efficiency pressure
    """
    # ── v4: pure recall reward (4-term) ────────────────────────────────────
    # trajectory_recall        : relevant docs found in pool (broad discovery)
    # recall                   : relevant docs in curated list (selection skill)
    # trajectory_fa_recall     : answer docs found in pool (targeted discovery)
    # final_answer_recall      : answer docs in curated list (highest value)
    if REWARD_VERSION == "v4":
        reward = 0.5 * (
            trajectory_recall
            + recall
            + trajectory_fa_recall
            + final_answer_recall
        )
        final_answer_found = final_answer_recall > 0
        pool_curated_gap = max(0.0, trajectory_recall - recall)
        curate_rate = total_curate_calls / max(turn, 1)
        metrics = {
            "recall": recall, "precision": precision,
            "f_beta": 0.0, "trajectory_recall": trajectory_recall,
            "trajectory_fa_recall": trajectory_fa_recall,
            "final_answer_recall": final_answer_recall,
            "final_answer_found": 1.0 if final_answer_found else 0.0,
            "pool_curated_gap": pool_curated_gap,
            "num_curated_docs": float(n_curated),
            "used_curate": 1.0 if n_curated > 0 else 0.0,
            "total_curate_calls": float(total_curate_calls),
            "curate_rate": curate_rate,
            "tool_diversity": float(n_unique_tools),
            "num_turns": turn,
            "final_reward": reward,
            "no_error": 1.0,
            "max_turns_reached": 0.0,
            "no_curate_penalty": 1.0 if (n_curated == 0 and is_terminal) else 0.0,
        }
        return reward, metrics

    # ── v3: original multi-component reward ──────────────────────────────
    if n_curated == 0:
        if is_terminal:
            return NO_CURATE_PENALTY, {
                "no_error": 1.0, "recall": 0.0, "precision": 0.0,
                "f_beta": 0.0, "trajectory_recall": trajectory_recall,
                "final_answer_found": 0.0, "num_curated_docs": 0,
                "used_curate": 0.0, "no_curate_penalty": 1.0,
                "final_reward": NO_CURATE_PENALTY,
                "max_turns_reached": 0.0,
            }
        fallback = max(TRAJECTORY_RECALL_WEIGHT * trajectory_recall, MIN_FORMAT_REWARD)
        return fallback, {
            "no_error": 1.0, "recall": 0.0, "precision": 0.0,
            "f_beta": 0.0, "trajectory_recall": trajectory_recall,
            "final_answer_found": 0.0, "num_curated_docs": 0,
            "used_curate": 0.0, "final_reward": fallback,
            "max_turns_reached": 0.0,
        }

    # F-beta (beta=2: recall weighted 4x over precision)
    beta_sq = RECALL_BETA * RECALL_BETA
    if precision + recall > 0:
        f_beta = (
            (1 + beta_sq) * precision * recall
        ) / (beta_sq * precision + recall)
    else:
        f_beta = 0.0

    final_answer_found = final_answer_recall > 0
    if FINAL_ANSWER_BINARY:
        final_answer_bonus = FINAL_ANSWER_BONUS if final_answer_found else 0.0
    else:
        final_answer_bonus = FINAL_ANSWER_BONUS * final_answer_recall

    fa_dense_reward = (
        FINAL_ANSWER_RECALL_WEIGHT * final_answer_recall
        + TRAJECTORY_FA_RECALL_WEIGHT * trajectory_fa_recall
    )
    fa_miss_gap = max(0.0, trajectory_fa_recall - final_answer_recall)
    fa_miss_penalty = FA_MISS_PENALTY_WEIGHT * fa_miss_gap

    combined = (
        OUTCOME_WEIGHT * f_beta
        + TRAJECTORY_RECALL_WEIGHT * trajectory_recall
        + final_answer_bonus
        + fa_dense_reward
    )
    combined -= fa_miss_penalty

    # Gap penalty (default 0 — kept for backward compat)
    pool_curated_gap = max(0.0, trajectory_recall - recall)
    gap_penalty = GAP_PENALTY_WEIGHT * pool_curated_gap
    combined -= gap_penalty

    # Turn penalty: linear ramp from 0 at TURN_PENALTY_MIN_TURNS to TURN_PENALTY_MAX at MAX_TURNS
    if turn > TURN_PENALTY_MIN_TURNS and TURN_PENALTY_MAX > 0:
        turn_range = max(MAX_TURNS - TURN_PENALTY_MIN_TURNS, 1)
        turn_frac = min((turn - TURN_PENALTY_MIN_TURNS) / turn_range, 1.0)
        turn_penalty = TURN_PENALTY_MAX * turn_frac
    else:
        turn_penalty = 0.0
    combined -= turn_penalty

    # Legacy shaping bonuses (defaults zeroed in v2)
    curate_rate = total_curate_calls / max(turn, 1)
    curate_rate_bonus = CURATE_RATE_BONUS_WEIGHT * min(
        curate_rate / TARGET_CURATE_RATE, 1.0
    )
    combined += curate_rate_bonus

    tool_diversity_bonus = TOOL_DIVERSITY_BONUS_WEIGHT * min(
        n_unique_tools / TOOL_DIVERSITY_TARGET, 1.0
    )
    combined += tool_diversity_bonus
    tool_diversity_shortfall = max(0, TOOL_DIVERSITY_TARGET - n_unique_tools)
    tool_diversity_penalty = (
        TOOL_DIVERSITY_SHORTFALL_PENALTY * tool_diversity_shortfall
    )
    combined -= tool_diversity_penalty

    final_reward = max(MIN_FORMAT_REWARD, combined)

    metrics = {
        "recall": recall,
        "precision": precision,
        "f_beta": f_beta,
        "final_answer_recall": final_answer_recall,
        "final_answer_found": 1.0 if final_answer_found else 0.0,
        "trajectory_recall": trajectory_recall,
        "trajectory_fa_recall": trajectory_fa_recall,
        "final_answer_bonus": final_answer_bonus,
        "fa_dense_reward": fa_dense_reward,
        "fa_miss_gap": fa_miss_gap,
        "fa_miss_penalty": fa_miss_penalty,
        "pool_curated_gap": pool_curated_gap,
        "gap_penalty": gap_penalty,
        "turn_penalty": turn_penalty,
        "pre_penalty_reward": combined + gap_penalty + turn_penalty,
        "num_curated_docs": float(n_curated),
        "used_curate": 1.0,
        "total_curate_calls": float(total_curate_calls),
        "curate_rate": curate_rate,
        "curate_rate_bonus": curate_rate_bonus,
        "tool_diversity": float(n_unique_tools),
        "tool_diversity_bonus": tool_diversity_bonus,
        "tool_diversity_shortfall": float(tool_diversity_shortfall),
        "tool_diversity_penalty": tool_diversity_penalty,
        "num_turns": turn,
        "final_reward": final_reward,
        "no_error": 1.0,
        "max_turns_reached": 0.0,
    }
    return final_reward, metrics


# ═══════════════════════════════════════════════════════════════════════════════
# Utility: parse doc IDs/texts from search observation
# ═══════════════════════════════════════════════════════════════════════════════

def parse_doc_ids_from_observation(obs_text: str) -> List[str]:
    """Extract document IDs from a search/grep observation string."""
    return re.findall(r'# DOCUMENT ID:\s*(\S+)', obs_text)


def parse_doc_texts_from_observation(obs_text: str) -> Dict[str, str]:
    """Extract ``{doc_id: full_text}`` from observation text.

    The search/grep tool emits headers like ``# DOCUMENT ID: 16871__0 (502 tokens)``
    where ``16871__0`` is the chunk id, ``16871`` the document id, and the
    ``(N tokens)`` suffix is informational. Callers (``WorkingMemory.add_to_pool``)
    look up by the *normalized* doc id (``16871``), so we key the result both
    ways: by the raw header token AND by the normalized doc id.
    """
    docs: Dict[str, str] = {}
    parts = re.split(r'# DOCUMENT ID:\s*', obs_text)
    for part in parts[1:]:
        lines = part.split("\n", 1)
        if not lines:
            continue
        header = lines[0].strip()
        text = (lines[1] if len(lines) > 1 else "").strip()
        # Drop the trailing "(N tokens)" annotation if present.
        chunk_id = header.split()[0] if header else ""
        if not chunk_id:
            continue
        docs[chunk_id] = text
        # Also key by the document id (chunk_id without the trailing __N suffix).
        doc_id = chunk_id.split("__")[0] if "__" in chunk_id else chunk_id
        docs.setdefault(doc_id, text)
    return docs


# ═══════════════════════════════════════════════════════════════════════════════
# v8d helpers: token budget marker, rerank instruction, compressed observation
# ═══════════════════════════════════════════════════════════════════════════════


def format_token_budget_marker(
    used_tokens: int,
    budget: int = PROMPT_TOKEN_BUDGET,
) -> str:
    """Format the `[Context: X/Y]` marker injected at the end of observations.

    Makes the model budget-aware without it having to estimate context size.
    """
    used_tokens = max(0, int(used_tokens))
    pct = int(100.0 * used_tokens / max(budget, 1))
    flag = ""
    if pct >= 90:
        flag = " CRITICAL — end_search NOW"
    elif pct >= 75:
        flag = " warning: finish up soon"
    elif pct >= 60:
        flag = " over halfway"
    return f"[Context: {used_tokens}/{budget}{flag}]"


def append_token_marker(obs_text: str, used_tokens: int) -> str:
    """Append the token-budget marker to an observation. No-op unless enabled."""
    if not V8D_TOKEN_BUDGET_MARKER:
        return obs_text
    marker = format_token_budget_marker(used_tokens)
    if obs_text.endswith("\n"):
        return obs_text + marker
    return obs_text + "\n" + marker


def compress_search_observation(query: str, obs_text: str) -> str:
    """Compress per-doc search result text with BM25 sentence selection.

    Applies to each `# DOCUMENT ID: ...` block. Preserves doc IDs and structure.
    No-op if V8D_SENTENCE_COMPRESS is disabled or BM25 is unavailable.
    """
    if not V8D_SENTENCE_COMPRESS or not _HAS_BM25:
        return obs_text
    if "# DOCUMENT ID:" not in obs_text:
        return obs_text
    # Split on doc delimiters, keep header and body separately
    parts = re.split(r"(# DOCUMENT ID:\s*\S+\n)", obs_text)
    # parts will alternate: [prefix, header1, body1, header2, body2, ...]
    out_parts: List[str] = []
    for i, chunk in enumerate(parts):
        if i == 0 or not chunk.startswith("# DOCUMENT ID:"):
            out_parts.append(chunk)
            continue
        out_parts.append(chunk)
        # next part is the body for this header
        if i + 1 < len(parts):
            body = parts[i + 1]
            compressed = compress_chunk(query, body, k=SENTENCE_COMPRESS_K)
            parts[i + 1] = compressed
    # reconstruct
    result: List[str] = []
    for i, chunk in enumerate(parts):
        result.append(chunk)
    return "".join(parts)


# Per-domain rerank instruction presets (used when V8D_ADAPTIVE_RERANK_INSTRUCTION=0
# or when the LLM-based builder is unavailable). These are much cheaper than an
# extra LLM call per episode.
_DOMAIN_RERANK_INSTRUCTIONS = {
    "sec": (
        "Given a query about SEC filings (10-K, 10-Q, 8-K, proxy statements), retrieve "
        "passages that directly answer the query's specific financial, regulatory, or "
        "governance criteria. Prefer passages with numeric facts, dates, or explicit "
        "statements that match the query."
    ),
    "patents": (
        "Given a query about patents, retrieve passages that describe the specific "
        "invention, claims, inventors, assignees, or prior art referenced in the query. "
        "Prefer passages with technical detail matching the query's constraints."
    ),
    "browsecompplus": (
        "Given a hard multi-hop web query, retrieve passages that contain the specific "
        "entities, dates, quantities, or relationships asked about. Prefer passages "
        "that directly match multiple constraints simultaneously."
    ),
    "web": (
        "Given a web search query, retrieve passages that directly answer the query. "
        "Prefer passages with specific entities, dates, or facts that match the query."
    ),
}


def build_rerank_instruction(
    query: str,
    dataset_name: Optional[str] = None,
    openai_client: Any = None,
    use_llm: bool = False,
) -> str:
    """Build a rerank instruction tailored to the current query.

    Default behavior (use_llm=False): returns a domain-specific static template.
    Cheap, deterministic, no API cost.

    Advanced behavior (use_llm=True): calls GPT-5.4 to generate a query-specific
    instruction. ~1 extra LLM call per episode (fixed cost, not per-turn).
    """
    if dataset_name and not use_llm:
        return _DOMAIN_RERANK_INSTRUCTIONS.get(
            dataset_name, _DOMAIN_RERANK_INSTRUCTIONS["web"]
        )

    if not use_llm or openai_client is None:
        return _DOMAIN_RERANK_INSTRUCTIONS.get(
            dataset_name or "web", _DOMAIN_RERANK_INSTRUCTIONS["web"]
        )

    try:
        system = (
            "You write concise (≤30 word) reranker instructions. Given a search query, "
            "produce one sentence describing what makes a passage 'relevant enough to "
            "return'. Focus on query-specific constraints (entities, dates, numbers, "
            "relationships). Output ONLY the instruction, no preamble."
        )
        resp = openai_client.chat.completions.create(
            model=os.environ.get("RERANK_INSTR_MODEL", "gpt-5.4-mini"),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"Query: {query}"},
            ],
            temperature=0.2,
            max_tokens=80,
            timeout=10,
        )
        instr = resp.choices[0].message.content.strip()
        if len(instr) < 20 or len(instr) > 400:
            raise ValueError("rerank instruction out of range")
        return instr
    except Exception as e:
        logger.warning("rerank_instr_builder_failed", error=str(e)[:200])
        return _DOMAIN_RERANK_INSTRUCTIONS.get(
            dataset_name or "web", _DOMAIN_RERANK_INSTRUCTIONS["web"]
        )


# ═══════════════════════════════════════════════════════════════════════════════
# v8d: Verify tool exec (cheap LLM claim-check against doc text)
# ═══════════════════════════════════════════════════════════════════════════════


_VERIFY_SYSTEM = (
    "You are a strict document verifier. Given a CLAIM and one DOCUMENT's full text, "
    "answer only 'yes' or 'no' followed by a very short (≤20 word) rationale. "
    "Answer 'yes' ONLY if the document directly supports ALL parts of the claim. "
    "Answer 'no' if any constraint is missing or contradicted. Be conservative."
)


def exec_verify_claim(
    openai_client: Any,
    doc_texts: Dict[str, str],
    claim: str,
    model: Optional[str] = None,
) -> str:
    """Run verify tool: for each doc, ask if it supports the claim.

    Returns a single string formatted as:
        # DOCUMENT ID: <id>
        verdict: yes|no
        rationale: <short>
    """
    if not doc_texts:
        return "verify: no matching docs found in memory."
    if not claim or len(claim.strip()) < 6:
        return "verify: claim is too short or empty."

    model = model or os.environ.get("VERIFY_MODEL", "gpt-5.4-mini")
    out_parts: List[str] = []
    for doc_id, text in list(doc_texts.items())[:5]:  # cap per call
        snippet = text[:6000] if text else ""
        if not snippet:
            out_parts.append(
                f"# DOCUMENT ID: {doc_id}\nverdict: no\nrationale: document text unavailable."
            )
            continue
        try:
            resp = openai_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _VERIFY_SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            f"CLAIM: {claim}\n\nDOCUMENT:\n{snippet}\n\n"
                            "Answer strictly as: '<yes|no>. <rationale>'"
                        ),
                    },
                ],
                temperature=0.0,
                max_tokens=80,
                timeout=20,
            )
            reply = resp.choices[0].message.content.strip()
            # Normalize output
            lower = reply.lower().lstrip()
            verdict = "yes" if lower.startswith("yes") else "no"
            # pull rationale after the first sentence break
            rat = reply.split(".", 1)[-1].strip() if "." in reply else reply
            out_parts.append(
                f"# DOCUMENT ID: {doc_id}\nverdict: {verdict}\nrationale: {rat[:200]}"
            )
        except Exception as e:
            out_parts.append(
                f"# DOCUMENT ID: {doc_id}\nverdict: unknown\nrationale: verify failed ({str(e)[:80]})."
            )
    return "\n\n".join(out_parts)


# ═══════════════════════════════════════════════════════════════════════════════
# v8d: Small helper used by auto-populate hook in env
# ═══════════════════════════════════════════════════════════════════════════════


def auto_populate_from_first_search(
    wm: WorkingMemory,
    ranked_doc_ids: List[str],
    top_k: int = AUTO_POPULATE_TOP_K,
) -> int:
    """Populate the curated set from the first successful search's top-K hits.

    Idempotent: only runs if wm.auto_populated is False AND wm.curated_ids is empty.
    All auto-populated docs get importance='fair'; the model is expected to demote
    or remove poor ones on subsequent curate calls.

    Returns the number of docs added.
    """
    if not V8D_AUTO_POPULATE_FIRST_SEARCH:
        return 0
    if wm.auto_populated or wm.curated_ids:
        return 0

    added = 0
    seen: Set[str] = set()
    for cid in ranked_doc_ids:
        did = wm._normalize_id(cid)
        if did in seen or not did:
            continue
        seen.add(did)
        if did not in wm.pool_id_set:
            continue
        if len(wm.curated_ids) >= min(top_k, MAX_CURATED_DOCS):
            break
        wm.curated_ids.append(did)
        if V8D_IMPORTANCE_TAGGING:
            wm.curated_importance[did] = "fair"
        added += 1

    wm.auto_populated = True
    return added
