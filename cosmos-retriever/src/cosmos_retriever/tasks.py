import json
import re
from typing import Any, Dict, List, Literal, Optional, Set, TYPE_CHECKING, Union
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field, model_validator
from cosmos_retriever.tools import (
    GrepCorpusToolCallMetadata,
    PruneChunksTool,
    SearchCorpusToolCallMetadata,
    SerializedTool,
    ToolSet,
    UserTextTool,
)
from cosmos_retriever.trajectory import Action, Observation, Trajectory
import structlog

if TYPE_CHECKING:
    from harness.config import Config

logger = structlog.get_logger("search_agent.agent")


def get_message_for_question(question: str) -> Dict[str, Any]:
    """Build the initial conversation state for a question."""

    return {"role": "user", "content": question}


# HACK way to extract doc ids from tool output
DOC_ID_PATTERN = re.compile(r"#\s*DOCUMENT ID:\s*(?P<chunk_id>[^\s]+)", re.IGNORECASE)
# HACK way to extract doc ids from final output
# Supports both <Document id=123> and <Document id="123"> in single or double quotes
FINAL_OUTPUT_DOCUMENT_PATTERN = re.compile(
    r"<Document id=[\"']?(?P<chunk_id>[^\"'\s>]+)[\"']?>"
)
CHUNK_ID_SUFFIX_PATTERN = re.compile(r"^(?P<base>.+?)_+(?P<chunk_idx>\d+)$")


def extract_chunk_ids_from_tool_output(text: str) -> Set[str]:
    """Extract chunk ids from tool output."""
    return {match.group("chunk_id") for match in DOC_ID_PATTERN.finditer(text)}


def extract_chunk_ids_from_final_output(text: str) -> Set[str]:
    """Extract chunk ids from final output."""
    matches = {
        match.group("chunk_id")
        for match in FINAL_OUTPUT_DOCUMENT_PATTERN.finditer(text)
    }
    return matches


def chunk_ids_to_doc_ids(chunks_ids: Set[str]) -> Set[str]:
    """Convert a set of chunk ids into a set of unique document ids."""
    document_ids: Set[str] = set()

    for raw_chunk_id in chunks_ids:
        chunk_id = str(raw_chunk_id)

        # URLs are document IDs already. Keep path/query and strip fragments.
        if "://" in chunk_id:
            parsed = urlsplit(chunk_id)
            document_ids.add(
                urlunsplit(
                    (parsed.scheme, parsed.netloc, parsed.path, parsed.query, "")
                )
            )
            continue

        # For chunk IDs like "12345_7", strip the numeric chunk suffix.
        # Avoid applying this to path-like IDs that legitimately contain "/".
        chunk_suffix_match = CHUNK_ID_SUFFIX_PATTERN.match(chunk_id)
        if chunk_suffix_match and "/" not in chunk_id:
            document_ids.add(chunk_suffix_match.group("base"))
            continue

        document_ids.add(chunk_id)

    return document_ids


class SearchTaskOutput(BaseModel):

    trajectory: Trajectory
    query_id: str  # The query id in the dataset
    dataset_name: str
    nondeduplicated_traversed_chunk_ids: List[str] = Field(default_factory=list)
    output_chunk_ids: List[str] = Field(default_factory=list)
    # True if output_chunk_ids were extracted from reasoning text as a fallback
    # (model terminated on reasoning without final text). Useful for filtering
    # malformed data points during SFT data generation.
    extracted_from_reasoning_fallback: bool = False

    @classmethod
    def deserialize(
        cls,
        data: Union[str, Dict[str, Any]],
        *,
        config: "Config",
        cosmos_container_name: str,
        toolset: Optional[ToolSet] = None,
    ) -> "SearchTaskOutput":
        """Deserialize serialized output and hydrate its trajectory."""

        if isinstance(data, cls):
            return data

        if isinstance(data, str):
            payload = json.loads(data)
        else:
            payload = data

        if not isinstance(payload, dict):
            raise TypeError(
                "SearchTaskOutput.deserialize expected a JSON string or dictionary."
            )

        trajectory_data = payload.get("trajectory")
        if trajectory_data is None:
            raise ValueError("Serialized SearchTaskOutput missing 'trajectory'.")

        hydrated_trajectory = Trajectory.deserialize(
            trajectory_data,
            config=config,
            cosmos_container_name=cosmos_container_name,
            toolset=toolset,
        )

        payload = payload.copy()
        payload["trajectory"] = hydrated_trajectory
        return cls.model_validate(payload)

    @model_validator(mode="after")
    def populate_derived_fields(self) -> "SearchTaskOutput":
        # Skip re-computation if nondeduplicated_traversed_chunk_ids is already populated
        # (e.g., when deserializing from JSON where it was already saved).
        # This avoids issues with tool_metadata not being properly deserialized into
        # the correct subclass types (GrepCorpusToolCallMetadata, SearchCorpusToolCallMetadata).
        if not self.nondeduplicated_traversed_chunk_ids:
            all_chunk_ids: List[str] = []
            for action in self.trajectory.actions_and_observations:
                if isinstance(action, Observation):
                    for tool_metadata in action.tool_metadata:
                        if tool_metadata is not None and (
                            isinstance(tool_metadata, GrepCorpusToolCallMetadata)
                            or isinstance(tool_metadata, SearchCorpusToolCallMetadata)
                        ):
                            all_chunk_ids.extend(tool_metadata.returned_chunk_ids)
            self.nondeduplicated_traversed_chunk_ids = all_chunk_ids

        # Skip output_document_ids computation if already populated from JSON
        if not self.output_chunk_ids:
            if not self.trajectory.actions_and_observations:
                raise RuntimeError("Trajectory has no actions or observations")

            retrieval_subagent_output = self.trajectory.actions_and_observations[-1]
            if (
                len(retrieval_subagent_output.sources) > 0
                and retrieval_subagent_output.sources[0] != "agent"
            ):
                raise RuntimeError("Early termination")

            if isinstance(retrieval_subagent_output, Action):
                if len(retrieval_subagent_output.sources) == 0:
                    if retrieval_subagent_output.reasoning is None:
                        raise RuntimeError("Early termination")
                    else:
                        logger.warning(
                            "Early termination, trying to extract doc ids from reasoning as sometimes the model terminates on reasoning without final text"
                        )
                        # Try to extract doc ids from the reasoning
                        self.output_chunk_ids = list(
                            extract_chunk_ids_from_final_output(
                                retrieval_subagent_output.reasoning
                            )
                        )
                        self.extracted_from_reasoning_fallback = True
                else:
                    text_fragments = [
                        params["text"]
                        for tool, params in zip(
                            retrieval_subagent_output.tools,
                            retrieval_subagent_output.params,
                        )
                        if isinstance(tool, UserTextTool) and isinstance(params.get("text"), str)
                    ]
                    if text_fragments:
                        self.output_chunk_ids = list(
                            extract_chunk_ids_from_final_output("\n".join(text_fragments))
                        )
                    else:
                        raise RuntimeError("Early termination")
            elif isinstance(retrieval_subagent_output, Observation):
                raise RuntimeError("Early termination")

        return self

    def get_unique_traversed_document_ids(self) -> Set[str]:
        return chunk_ids_to_doc_ids(set(self.nondeduplicated_traversed_chunk_ids))

    def get_unique_traversed_chunk_ids(self) -> Set[str]:
        return set(self.nondeduplicated_traversed_chunk_ids)

    def get_all_traversed_chunk_ids(self) -> List[str]:
        return self.nondeduplicated_traversed_chunk_ids

    def get_all_output_chunk_ids(self) -> List[str]:
        return self.output_chunk_ids

    def get_unique_output_chunk_ids(self) -> Set[str]:
        return set(self.output_chunk_ids)

    def get_unique_output_document_ids(self) -> Set[str]:
        return chunk_ids_to_doc_ids(set(self.output_chunk_ids))

    def get_all_pruned_chunk_ids(self) -> List[str]:
        """Extract all chunk IDs that were pruned during the trajectory."""
        pruned_chunk_ids: List[str] = []
        for action in self.trajectory.actions_and_observations:
            if isinstance(action, Action):
                for tool, params, source in zip(
                    action.tools, action.params, action.sources
                ):
                    # Check for PruneChunksTool or SerializedTool with prune_chunks schema
                    is_prune_tool = isinstance(tool, PruneChunksTool) or (
                        isinstance(tool, SerializedTool)
                        and tool.tool_schema.name == "prune_chunks"
                    )
                    if is_prune_tool:
                        chunk_ids = params.get("chunk_ids", [])
                        pruned_chunk_ids.extend(chunk_ids)
        return pruned_chunk_ids

    def get_unique_pruned_chunk_ids(self) -> Set[str]:
        """Get unique chunk IDs that were pruned during the trajectory."""
        return set(self.get_all_pruned_chunk_ids())

    def get_unique_pruned_document_ids(self) -> Set[str]:
        """Get unique document IDs that were pruned during the trajectory."""
        return chunk_ids_to_doc_ids(self.get_unique_pruned_chunk_ids())

    def get_all_pre_rerank_chunk_ids(self) -> List[str]:
        """Extract all pre-rerank chunk IDs from search corpus tool calls."""
        pre_rerank_ids: List[str] = []
        for item in self.trajectory.actions_and_observations:
            if isinstance(item, Observation):
                for tool_metadata in item.tool_metadata:
                    if (
                        tool_metadata is not None
                        and isinstance(tool_metadata, SearchCorpusToolCallMetadata)
                        and tool_metadata.pre_rerank_chunk_ids is not None
                    ):
                        pre_rerank_ids.extend(tool_metadata.pre_rerank_chunk_ids)
        return pre_rerank_ids

    def get_unique_pre_rerank_chunk_ids(self) -> Set[str]:
        """Get unique pre-rerank chunk IDs from search corpus tool calls."""
        return set(self.get_all_pre_rerank_chunk_ids())

    def log_trajectory_stats(self) -> None:
        logger.info(
            "trajectory_chunk_stats",
            total_chunk_ids=len(self.get_all_traversed_chunk_ids()),
            unique_chunk_ids=len(self.get_unique_traversed_chunk_ids()),
            duplicate_chunk_ids=len(self.get_all_traversed_chunk_ids())
            - len(self.get_unique_traversed_chunk_ids()),
        )


class SearchTaskEvaluationOutput(BaseModel):
    """Per-query evaluation metrics produced when running the retrieval agent."""

    query_id: str
    recall: Optional[float] = None
    precision: Optional[float] = None
    f1: Optional[float] = None
    trajectory_recall: Optional[float] = None
    final_answer_recall: Optional[float] = None
    retrieved_document_ids: List[str] = Field(default_factory=list)
    num_turns: Optional[int] = None
    prune_accuracy: Optional[float] = None
    # Reranker metrics - only populated when a reranker was used
    rerank_recall: Optional[float] = (
        None  # Fraction of relevant pre-rerank chunks kept after reranking
    )
    rerank_dropped_relevant_count: Optional[int] = (
        None  # Number of relevant chunks dropped by reranker
    )
    error: Optional[str] = None

    def succeeded(self) -> bool:
        return self.error is None

    @classmethod
    def from_search_task_output(
        cls,
        output: SearchTaskOutput,
        dataset: "Any",
    ) -> "SearchTaskEvaluationOutput":
        """Create an evaluation output from a SearchTaskOutput and dataset.

        Calculates all evaluation metrics (recall, precision, f1, trajectory_recall,
        final_answer_recall, prune_accuracy) based on the trajectory and ground truth
        from the dataset.
        """
        query_id = output.query_id
        retrieved_chunk_ids = sorted(output.get_unique_output_chunk_ids())
        trajectory_chunk_ids = sorted(output.get_unique_traversed_chunk_ids())

        recall = dataset.evaluate_results_recall(query_id, retrieved_chunk_ids)
        precision = dataset.evaluate_results_precision(query_id, retrieved_chunk_ids)
        f1 = dataset.evaluate_results_f1_score(query_id, retrieved_chunk_ids)
        trajectory_recall = dataset.evaluate_results_recall(
            query_id, trajectory_chunk_ids
        )
        final_answer_recall = dataset.evaluate_results_final_answer_recall(
            query_id, retrieved_chunk_ids
        )
        num_turns = output.trajectory.num_turns

        # Calculate prune accuracy
        prune_accuracy = cls._calculate_prune_accuracy(output, dataset)

        # Calculate reranker metrics
        rerank_recall, rerank_dropped_relevant_count = cls._calculate_rerank_metrics(
            output, dataset
        )

        return cls(
            query_id=query_id,
            recall=recall,
            precision=precision,
            f1=f1,
            trajectory_recall=trajectory_recall,
            final_answer_recall=final_answer_recall,
            retrieved_document_ids=sorted(output.get_unique_output_document_ids()),
            num_turns=num_turns,
            prune_accuracy=prune_accuracy,
            rerank_recall=rerank_recall,
            rerank_dropped_relevant_count=rerank_dropped_relevant_count,
        )

    @staticmethod
    def _calculate_prune_accuracy(
        output: SearchTaskOutput,
        dataset: "Any",
    ) -> Optional[float]:
        """Calculate prune accuracy for a search task output.

        Prune accuracy is the percentage of correct prune calls, where a bad prune
        is defined as pruning an expected (ground truth) document ID.

        Returns None if no prune calls were made.
        """
        pruned_chunk_ids = output.get_all_pruned_chunk_ids()
        if not pruned_chunk_ids:
            return None

        # Get expected document IDs from the dataset (these are chunk IDs or doc IDs)
        expected_chunk_ids = set(dataset.get_expected_document_ids(output.query_id))
        # Also convert to doc IDs for comparison
        expected_doc_ids = chunk_ids_to_doc_ids(expected_chunk_ids)

        # Count bad prunes (prunes of expected document IDs)
        bad_prunes = 0
        for chunk_id in pruned_chunk_ids:
            # A prune is bad if the chunk_id itself matches expected OR
            # if the doc_id (prefix before _) matches expected doc IDs
            doc_id = chunk_id.split("_")[0] if "_" in chunk_id else chunk_id
            if chunk_id in expected_chunk_ids or doc_id in expected_doc_ids:
                bad_prunes += 1

        total_prunes = len(pruned_chunk_ids)
        correct_prunes = total_prunes - bad_prunes
        return correct_prunes / total_prunes

    @staticmethod
    def _calculate_rerank_metrics(
        output: SearchTaskOutput,
        dataset: "Any",
    ) -> tuple[Optional[float], Optional[int]]:
        """Calculate reranker metrics for a search task output.

        Computes how well the reranker preserved relevant documents:
        - rerank_recall: Fraction of relevant pre-rerank chunks that were kept after reranking
        - rerank_dropped_relevant_count: Number of relevant chunks that were dropped

        Returns (None, None) if no reranking was performed (no pre_rerank_chunk_ids).
        """
        pre_rerank_ids = output.get_unique_pre_rerank_chunk_ids()
        if not pre_rerank_ids:
            return None, None

        # Get the chunks that were actually returned after reranking
        returned_ids = output.get_unique_traversed_chunk_ids()

        # Get expected document/chunk IDs from the dataset
        expected_chunk_ids = set(dataset.get_expected_document_ids(output.query_id))
        expected_doc_ids = chunk_ids_to_doc_ids(expected_chunk_ids)

        def is_relevant(chunk_id: str) -> bool:
            """Check if a chunk_id is relevant (matches expected)."""
            doc_id = chunk_id.split("_")[0] if "_" in chunk_id else chunk_id
            return chunk_id in expected_chunk_ids or doc_id in expected_doc_ids

        # Find relevant chunks in pre-rerank results
        relevant_pre_rerank = {cid for cid in pre_rerank_ids if is_relevant(cid)}

        if not relevant_pre_rerank:
            # No relevant chunks were in pre-rerank results, can't compute recall
            return None, 0

        # Find how many relevant chunks were kept after reranking
        relevant_kept = relevant_pre_rerank & returned_ids
        relevant_dropped = relevant_pre_rerank - returned_ids

        rerank_recall = len(relevant_kept) / len(relevant_pre_rerank)
        rerank_dropped_count = len(relevant_dropped)

        return rerank_recall, rerank_dropped_count
