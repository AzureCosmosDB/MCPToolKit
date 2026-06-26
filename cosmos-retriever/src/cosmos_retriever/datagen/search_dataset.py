from abc import ABC, abstractmethod
import ast
from collections import defaultdict
from enum import Enum
from typing import List, Literal, Optional, Set, Tuple
import datasets
import csv
import json
import random
from urllib.parse import urlsplit, urlunsplit
import cosmos_retriever.config as config
from cosmos_retriever.tasks import chunk_ids_to_doc_ids


SPLIT_SEED = 42
TRAIN_RATIO = 0.8

# Within the train split, further divide into SFT and RL subsets
SFT_RL_SPLIT_SEED = 123  # Different seed from train/test split for independence
SFT_RATIO = 0.3  # 30% of train queries for SFT, 70% for RL

# Type alias for fact-level document structure
FactItem = dict  # {"fact": str, "chunk_ids": List[str], "is_final_answer": bool}


def normalize_document_id(document_id: str) -> str:
    """Normalize a document ID for evaluation.

    For URL-like IDs, strip the fragment to avoid mismatches between equivalent
    links such as ``/wiki/Foo`` and ``/wiki/Foo#section``.
    """
    if "://" not in document_id:
        return document_id

    parsed = urlsplit(document_id)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def load_hf_dataset_first_available(
    hf_path: str,
    *,
    split_preferences: Tuple[str, ...] = ("test", "train", "validation"),
) -> datasets.Dataset:
    """Load a HuggingFace dataset and pick the first available preferred split."""
    cfg = config.get_config()
    token = cfg.huggingface_token
    raw = datasets.load_dataset(hf_path, token=token)

    for split_name in split_preferences:
        if split_name in raw and len(raw[split_name]) > 0:
            return raw[split_name]

    # Fallback to first non-empty split, then first split if all are empty.
    for split_name in raw.keys():
        if len(raw[split_name]) > 0:
            return raw[split_name]

    first_split = next(iter(raw.keys()))
    return raw[first_split]


# ============================================================================
# Backward-compatible enum (used by existing callers)
# ============================================================================


class SearchDatasetName(Enum):
    """Backward-compatible enum. Prefer using get_dataset(name_str) directly."""
    BROWSECOMPPLUS = "browsecompplus"
    BC_PLUS = "bc_plus"
    EPSTEIN = "epstein"
    LONGSEALQA = "longsealqa"
    SEAL0QA = "seal0qa"
    FRAMES = "frames"
    HOTPOTQA_SUBSET = "hotpotqa_subset"
    PODCASTS_TEST = "podcasts_test"
    WEB = "web"
    PATENTS = "patents"
    SEC = "sec"
    WEB_SIMPLE = "web_simple"
    SEC_SIMPLE = "sec_simple"
    DEEPSEARCH = "deepsearch"
    GAIA = "gaia"
    OTHER = "other"


# ============================================================================
# Search Dataset Base Class
# ============================================================================


class SearchDataset(ABC):
    """
    Abstract base class for search datasets.

    A search dataset is a dataset of search queries and the documents that are required
    to answer the query or that are relevant to the query.

    Subclasses must implement `_load_dataset()` to populate `_search_queries_dataset`
    with a HuggingFace Dataset containing the following columns:
    - query_id: The query id
    - query: The search query
    - document_ids: The documents that are required to answer the query or that are relevant to the query.
                    For document-level evaluation: List[str] of document/chunk IDs.
                    For fact-level evaluation: List[FactItem] where each FactItem has
                    {"fact": str, "chunk_ids": List[str], "is_final_answer": bool}.
    - answer: The answer to the query

    Subclasses can override `evaluation_mode` property to change evaluation behavior:
    - "document": Standard document/chunk-level evaluation (default)
    - "fact": Fact-level evaluation where a fact is found if ANY of its chunk_ids are retrieved

    For final_answer_recall evaluation:
    - Document-level datasets can override `_get_final_answer_document_ids()` to specify
      which document IDs are "final answer" documents (e.g., gold vs evidence in BrowseCompPlus).
    - Fact-level datasets automatically use facts where is_final_answer=True.
    """

    _search_queries_dataset: datasets.Dataset
    _query_index: dict  # Maps query_id -> row dict for O(1) lookups
    _train_query_ids: List[str]  # Query IDs in the train split
    _test_query_ids: List[str]  # Query IDs in the test split

    # Cosmos container configuration - override in subclasses.
    # A list (typically of length 1 in the Cosmos port; load balancing is
    # handled server-side via RU/s rather than via per-request sharding).
    COSMOS_CONTAINERS: List[str] = []
    # Optional split-specific containers (if not set, falls back to COSMOS_CONTAINERS)
    COSMOS_CONTAINERS_TRAIN: Optional[List[str]] = None
    COSMOS_CONTAINERS_TEST: Optional[List[str]] = None

    def __init__(self) -> None:
        # Subclass loads dataset into self._search_queries_dataset
        self._load_dataset()

        # Build common indices
        self._build_query_index()
        self._create_train_test_split()

    @abstractmethod
    def _load_dataset(self) -> None:
        """Load the dataset into self._search_queries_dataset. Implemented by subclasses."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the name identifier for this dataset."""
        pass

    @property
    def evaluation_mode(self) -> Literal["document", "fact"]:
        """Return the evaluation mode for this dataset.

        - "document": Standard document/chunk-level evaluation. document_ids is List[str].
        - "fact": Fact-level evaluation. document_ids is List[FactItem] where each fact
                  has chunk_ids. A fact counts as found if ANY of its chunk_ids are retrieved.

        Override this in subclasses that use fact-level evaluation.
        """
        return "document"

    def get_cosmos_containers(
        self, split: Optional[Literal["train", "test"]] = None
    ) -> List[str]:
        """Get the Cosmos container names that back this dataset.

        Args:
            split: If provided, return containers specific to that split.
                   If None, returns the default containers.

        Returns:
            A list of Cosmos container names. In the Cosmos port this is
            typically a single-element list (no per-request sharding).

        Raises:
            ValueError: If no containers are configured for the requested split.
        """
        if split == "train" and self.COSMOS_CONTAINERS_TRAIN is not None:
            collections = self.COSMOS_CONTAINERS_TRAIN
        elif split == "test" and self.COSMOS_CONTAINERS_TEST is not None:
            collections = self.COSMOS_CONTAINERS_TEST
        else:
            collections = self.COSMOS_CONTAINERS

        if not collections:
            raise ValueError(
                f"No Cosmos containers configured for dataset '{self.name}'"
                + (f" (split={split})" if split else "")
            )
        return collections

    def _build_query_index(self) -> None:
        """Build query index for O(1) lookups instead of O(n) filter operations."""
        self._query_index = {}
        for i in range(len(self._search_queries_dataset)):
            row = self._search_queries_dataset[i]
            # Handle document_ids that may be stored as string instead of list
            # TODO: We should fix this in the dataset itself.
            document_ids = row["document_ids"]
            if isinstance(document_ids, str):
                document_ids = ast.literal_eval(document_ids)
            # For document-level evaluation, ensure document_ids are strings
            # (model outputs are strings, so we need consistent types for comparison)
            if self.evaluation_mode == "document":
                document_ids = [
                    normalize_document_id(str(doc_id)) for doc_id in document_ids
                ]
            # Ensure query_id is always a string
            query_id = str(row["query_id"])
            self._query_index[query_id] = {
                "query_id": query_id,
                "query": row["query"],
                "document_ids": document_ids,
                "answer": row["answer"],
            }

    def _create_train_test_split(self) -> None:
        """Create deterministic train/test split (80/20)."""
        all_query_ids = list(self._query_index.keys())
        all_query_ids_sorted = sorted(all_query_ids)  # Sort for determinism
        rng = random.Random(SPLIT_SEED)
        rng.shuffle(all_query_ids_sorted)
        split_idx = int(len(all_query_ids_sorted) * TRAIN_RATIO)
        self._train_query_ids = all_query_ids_sorted[:split_idx]
        self._test_query_ids = all_query_ids_sorted[split_idx:]

    def get_train_query_ids(self) -> List[str]:
        """Return all query ids in the train split (80% of data)."""
        return self._train_query_ids.copy()

    def get_test_query_ids(self) -> List[str]:
        """Return all query ids in the test split (20% of data)."""
        return self._test_query_ids.copy()

    def _create_sft_rl_split(self) -> None:
        """Split train queries into SFT (30%) and RL (70%) subsets.

        This is a deterministic sub-split of the train set. The split is
        performed after the train/test split, so it's independent of it.
        """
        train_ids_sorted = sorted(self._train_query_ids)  # Sort for determinism
        rng = random.Random(SFT_RL_SPLIT_SEED)
        rng.shuffle(train_ids_sorted)
        split_idx = int(len(train_ids_sorted) * SFT_RATIO)
        self._sft_query_ids = train_ids_sorted[:split_idx]
        self._rl_query_ids = train_ids_sorted[split_idx:]

    def get_sft_query_ids(self) -> List[str]:
        """Return query ids for SFT training (30% of train split)."""
        if not hasattr(self, "_sft_query_ids"):
            self._create_sft_rl_split()
        return self._sft_query_ids.copy()

    def get_rl_query_ids(self) -> List[str]:
        """Return query ids for RL training (70% of train split)."""
        if not hasattr(self, "_rl_query_ids"):
            self._create_sft_rl_split()
        return self._rl_query_ids.copy()

    def get_random_query(
        self, split: Optional[Literal["train", "test"]] = None
    ) -> Tuple[str, str]:
        """Get a random query from the search queries dataset.

        Args:
            split: If provided, only sample from the specified split ("train" or "test").
                   If None, sample from all queries.

        Returns the query id and query text.
        """
        if split == "train":
            query_ids = self._train_query_ids
        elif split == "test":
            query_ids = self._test_query_ids
        else:
            query_ids = list(self._query_index.keys())

        query_id = random.choice(query_ids)
        return (query_id, self._query_index[query_id]["query"])

    def get_all_query_ids(
        self, split: Optional[Literal["train", "test", "sft", "rl"]] = None
    ) -> List[str]:
        """Return all query ids contained in the dataset.

        Args:
            split: If provided, only return query ids from the specified split.
                   - "train": All train queries (80% of data)
                   - "test": All test queries (20% of data)
                   - "sft": SFT subset of train queries (30% of train = 24% of total)
                   - "rl": RL subset of train queries (70% of train = 56% of total)
                   - None: All query ids
        """
        if split == "train":
            return self._train_query_ids.copy()
        elif split == "test":
            return self._test_query_ids.copy()
        elif split == "sft":
            return self.get_sft_query_ids()
        elif split == "rl":
            return self.get_rl_query_ids()
        return list(self._query_index.keys())

    def get_expected_document_ids(self, query_id: str) -> List[str]:
        """Get the expected document/chunk ids for a given query id.

        For document-level datasets: returns the document_ids list directly.
        For fact-level datasets: returns a flattened list of all chunk_ids from all facts.

        Returns a list of document/chunk IDs.
        """
        return list(self._get_all_relevant_chunk_ids(query_id))

    def get_expected_facts(self, query_id: str) -> List[FactItem]:
        """Get the expected facts for a given query id.

        Only meaningful for fact-level datasets (evaluation_mode == "fact").
        For document-level datasets, this returns an empty list.

        Returns a list of fact objects, each with keys:
        - "fact": str - description of the fact
        - "chunk_ids": List[str] - chunk IDs containing this fact
        - "is_final_answer": bool - whether this fact is the final answer
        """
        if self.evaluation_mode != "fact":
            raise ValueError(f"Dataset {self.name} is not a fact-level dataset")
        return self._query_index[query_id]["document_ids"]

    def get_expected_answer(self, query_id: str) -> str:
        """Get the expected answer for a given query id.

        Returns the expected answer.
        """
        return self._query_index[query_id]["answer"]

    def get_query_by_id(self, query_id: str) -> Tuple[str, str]:
        """Get a query by id from the search queries dataset.

        Returns the query id and query text.
        """
        row = self._query_index[query_id]
        return (row["query_id"], row["query"])

    def _get_all_relevant_chunk_ids(self, query_id: str) -> Set[str]:
        """Get all relevant chunk IDs for a query, handling both evaluation modes.

        For document-level: returns document_ids directly.
        For fact-level: extracts and flattens all chunk_ids from fact objects.
        """
        document_ids = self._query_index[query_id]["document_ids"]

        if self.evaluation_mode == "fact":
            # Fact-level: extract chunk_ids from each fact object
            all_chunk_ids: Set[str] = set()
            for fact in document_ids:
                all_chunk_ids.update(fact["chunk_ids"])
            return all_chunk_ids
        else:
            # Document-level: document_ids is already a flat list
            return set(document_ids)

    def _get_final_answer_document_ids(self, query_id: str) -> Set[str]:
        """Get document IDs that correspond to "final answer" documents.

        For document-level datasets: By default, returns all document_ids.
        Subclasses can override this to return only "gold" or "final answer" documents.

        For fact-level datasets: Returns chunk_ids from facts where is_final_answer=True.
        """
        document_ids = self._query_index[query_id]["document_ids"]

        if self.evaluation_mode == "fact":
            # Fact-level: extract chunk_ids only from final answer facts
            final_answer_chunk_ids: Set[str] = set()
            for fact in document_ids:
                if fact.get("is_final_answer", False):
                    final_answer_chunk_ids.update(fact["chunk_ids"])
            return final_answer_chunk_ids
        else:
            # Document-level: by default, all documents are considered "final answer"
            # Subclasses can override to provide gold-only documents
            return set(document_ids)

    def _get_final_answer_facts(self, query_id: str) -> List[FactItem]:
        """Get facts that are marked as final answer.

        Only meaningful for fact-level datasets.
        Returns facts where is_final_answer=True.
        """
        if self.evaluation_mode != "fact":
            return []
        document_ids = self._query_index[query_id]["document_ids"]
        return [fact for fact in document_ids if fact.get("is_final_answer", False)]

    def evaluate_results_recall(
        self, query_id: str, retrieved_chunk_ids: List[str]
    ) -> float:
        """Evaluate the recall of the retrieved chunk ids for a given query.

        For document-level evaluation:
            Recall = True Positives / (True Positives + False Negatives)
            where positives are document IDs.

        For fact-level evaluation:
            Recall = (facts found) / (total facts)
            A fact is considered found if ANY of its chunk_ids are in the retrieved set.
        """
        retrieved_set = set(retrieved_chunk_ids)

        if self.evaluation_mode == "fact":
            # Fact-level recall: count facts where at least one chunk_id is retrieved
            facts = self._query_index[query_id]["document_ids"]
            if len(facts) == 0:
                return 0.0

            facts_found = sum(
                1
                for fact in facts
                if set(fact["chunk_ids"]).intersection(retrieved_set)
            )
            return facts_found / len(facts)
        else:
            # Document-level recall
            retrieved_document_ids_set: Set[str] = chunk_ids_to_doc_ids(retrieved_set)
            relevant_document_ids_set: Set[str] = set(
                self._query_index[query_id]["document_ids"]
            )

            true_positives = len(
                retrieved_document_ids_set.intersection(relevant_document_ids_set)
            )
            false_negatives = len(
                relevant_document_ids_set - retrieved_document_ids_set
            )
            if true_positives + false_negatives == 0:
                return 0.0
            return true_positives / (true_positives + false_negatives)

    def evaluate_results_final_answer_recall(
        self, query_id: str, retrieved_chunk_ids: List[str]
    ) -> float:
        """Evaluate the final answer recall of the retrieved chunk ids for a given query.

        This metric measures recall specifically on "final answer" or "gold" documents/facts:

        For document-level evaluation (e.g., BrowseCompPlus):
            Uses _get_final_answer_document_ids() which can be overridden by subclasses
            to return only "gold" documents (excluding "evidence" documents).
            Recall = (gold docs found) / (total gold docs)

        For fact-level evaluation:
            Only considers facts where is_final_answer=True.
            Recall = (final answer facts found) / (total final answer facts)
            A fact is found if ANY of its chunk_ids are in the retrieved set.
        """
        retrieved_set = set(retrieved_chunk_ids)

        if self.evaluation_mode == "fact":
            # Fact-level: only count final answer facts
            final_answer_facts = self._get_final_answer_facts(query_id)
            if len(final_answer_facts) == 0:
                return 0.0

            facts_found = sum(
                1
                for fact in final_answer_facts
                if set(fact["chunk_ids"]).intersection(retrieved_set)
            )
            return facts_found / len(final_answer_facts)
        else:
            # Document-level: use final answer document IDs
            retrieved_document_ids_set: Set[str] = chunk_ids_to_doc_ids(retrieved_set)
            final_answer_document_ids_set: Set[str] = (
                self._get_final_answer_document_ids(query_id)
            )

            if len(final_answer_document_ids_set) == 0:
                return 0.0

            true_positives = len(
                retrieved_document_ids_set.intersection(final_answer_document_ids_set)
            )
            return true_positives / len(final_answer_document_ids_set)

    def evaluate_results_precision(
        self, query_id: str, retrieved_chunk_ids: List[str]
    ) -> float:
        """Evaluate the precision of the retrieved chunk ids for a given query.

        For document-level evaluation:
            Precision = True Positives / (True Positives + False Positives)
            where positives are document IDs.

        For fact-level evaluation:
            Precision = (relevant chunks retrieved) / (total chunks retrieved)
            A chunk is relevant if it appears in any fact's chunk_ids.
        """
        retrieved_set = set(retrieved_chunk_ids)

        if self.evaluation_mode == "fact":
            # Fact-level precision: what fraction of retrieved chunks are relevant
            if len(retrieved_set) == 0:
                return 0.0

            all_relevant_chunk_ids = self._get_all_relevant_chunk_ids(query_id)
            relevant_retrieved = len(retrieved_set.intersection(all_relevant_chunk_ids))
            return relevant_retrieved / len(retrieved_set)
        else:
            # Document-level precision
            retrieved_document_ids_set: Set[str] = chunk_ids_to_doc_ids(retrieved_set)
            relevant_document_ids_set: Set[str] = set(
                self._query_index[query_id]["document_ids"]
            )

            true_positives = len(
                retrieved_document_ids_set.intersection(relevant_document_ids_set)
            )
            false_positives = len(
                retrieved_document_ids_set - relevant_document_ids_set
            )
            if true_positives + false_positives == 0:
                return 0.0
            return true_positives / (true_positives + false_positives)

    def evaluate_results_f1_score(
        self, query_id: str, retrieved_chunk_ids: List[str]
    ) -> float:
        """Evaluate the F1 score of the retrieved chunk ids for a given query.

        F1 score is defined as 2 * (Precision * Recall) / (Precision + Recall)
        Works for both document-level and fact-level evaluation modes.
        """
        precision = self.evaluate_results_precision(query_id, retrieved_chunk_ids)
        recall = self.evaluate_results_recall(query_id, retrieved_chunk_ids)
        if precision + recall == 0:
            return 0.0
        return 2 * (precision * recall) / (precision + recall)

    @classmethod
    def from_known_dataset(cls, name: "SearchDatasetName") -> "SearchDataset":
        """Backward-compatible factory method. Prefer get_dataset(name_str) instead."""
        return get_dataset(name.value)


# ============================================================================
# Pre-Split Dataset Base Class
# ============================================================================


class PreSplitSearchDataset(SearchDataset):
    """
    Base class for search datasets with separate train/test HuggingFace paths.

    Instead of loading a single dataset and applying an 80/20 split, this class
    loads from separate train and test HF paths and uses those as the canonical splits.

    Subclasses must define:
    - HF_PATH_TRAIN: HuggingFace path for train split
    - HF_PATH_TEST: HuggingFace path for test split
    - name property

    Optionally:
    - HF_SPLIT_TRAIN: The split name in the train dataset (default: "train")
    - HF_SPLIT_TEST: The split name in the test dataset (default: "test")
    - Override `_post_load_setup()` for additional processing (e.g., gold_document_ids)
    """

    HF_PATH_TRAIN: str
    HF_PATH_TEST: str
    HF_SPLIT_TRAIN: str = "train"
    HF_SPLIT_TEST: str = "test"

    def _load_dataset(self) -> None:
        """Load train and test datasets from separate HF paths."""
        cfg = config.get_config()
        token = cfg.huggingface_token

        train_ds = datasets.load_dataset(self.HF_PATH_TRAIN, token=token)[
            self.HF_SPLIT_TRAIN
        ]
        test_ds = datasets.load_dataset(self.HF_PATH_TEST, token=token)[
            self.HF_SPLIT_TEST
        ]

        # Store query IDs from each split before combining
        self._presplit_train_ids = [str(qid) for qid in train_ds["query_id"]]
        self._presplit_test_ids = [str(qid) for qid in test_ds["query_id"]]

        # Combine into single dataset for unified access
        self._search_queries_dataset = datasets.concatenate_datasets(
            [train_ds, test_ds]
        )

        # Hook for subclass-specific post-load processing
        self._post_load_setup()

    def _post_load_setup(self) -> None:
        """Override in subclasses for additional setup after loading."""
        pass

    def _create_train_test_split(self) -> None:
        """Use the pre-defined splits instead of random 80/20."""
        self._train_query_ids = self._presplit_train_ids
        self._test_query_ids = self._presplit_test_ids


class SingleSplitSearchDataset(SearchDataset):
    """Dataset helper for eval-only corpora that expose a single HF split.

    For these datasets we typically want deterministic sampling from the full set,
    so we expose all query IDs through both train and test partitions.
    """

    HF_PATH: str
    HF_SPLIT_PREFERENCES: Tuple[str, ...] = ("test", "train", "validation")

    def _load_dataset(self) -> None:
        self._search_queries_dataset = load_hf_dataset_first_available(
            self.HF_PATH, split_preferences=self.HF_SPLIT_PREFERENCES
        )

    def _create_train_test_split(self) -> None:
        all_query_ids = sorted(self._query_index.keys())
        self._train_query_ids = all_query_ids
        self._test_query_ids = all_query_ids


# ============================================================================
# BrowseComp+ Dataset
# ============================================================================


class BrowseCompPlusDataset(SearchDataset):
    """BrowseComp+ search dataset."""

    _gold_document_ids: dict[str, Set[str]]  # Maps query_id -> gold document IDs

    # Container name comes from config.cosmos_corpus_container (see get_cosmos_containers).
    COSMOS_CONTAINERS = ["browsecomp_corpus_container"]

    def get_cosmos_containers(self, split=None):
        return [config.get_config().cosmos_corpus_container]

    @property
    def name(self) -> str:
        return "browsecompplus"

    def _load_dataset(self) -> None:
        cfg = config.get_config()

        qrels_gold = self._load_qrels(cfg.browsecompplus_qrels_gold_path)
        qrels_evidence = self._load_qrels(cfg.browsecompplus_qrels_evidence_path)

        # Store gold document IDs separately for final_answer_recall
        self._gold_document_ids = {
            query_id: set(doc_ids) for query_id, doc_ids in qrels_gold.items()
        }

        # Combine qrels_gold and qrels_evidence for overall recall
        qrels: dict[str, list] = defaultdict(list)
        for query_id, doc_ids in qrels_gold.items():
            qrels[query_id].extend(doc_ids)
        for query_id, doc_ids in qrels_evidence.items():
            qrels[query_id].extend(doc_ids)

        queries = self._load_queries(cfg.browsecompplus_queries_path)
        answers = self._load_decrypted_answers(cfg.browsecompplus_answers_path)

        query_ids = list(queries.keys())
        self._search_queries_dataset = datasets.Dataset.from_dict(
            {
                "query_id": query_ids,
                "query": [queries[query_id] for query_id in query_ids],
                "document_ids": [qrels[query_id] for query_id in query_ids],
                "answer": [answers[query_id] for query_id in query_ids],
            }
        )

    def _get_final_answer_document_ids(self, query_id: str) -> Set[str]:
        """Return only gold document IDs (excluding evidence documents)."""
        return self._gold_document_ids.get(query_id, set())

    @staticmethod
    def _load_qrels(path: str) -> dict:
        """Load qrels from a TREC-format file."""
        qrels: dict[str, dict[str, int]] = {}
        with open(path, "r") as f:
            for line in f:
                parts = line.strip().split()
                query_id = parts[0]
                doc_id = parts[2]
                relevance = int(parts[3])
                if query_id not in qrels:
                    qrels[query_id] = {}
                qrels[query_id][doc_id] = relevance
        return qrels

    @staticmethod
    def _load_queries(path: str) -> dict:
        """Load queries from a TSV file."""
        queries = {}
        with open(path) as fd:
            rd = csv.reader(fd, delimiter="\t", quotechar='"')
            for row in rd:
                query_id = row[0]
                query_text = row[1]
                queries[query_id] = query_text
        return queries

    @staticmethod
    def _load_decrypted_answers(path: str) -> dict:
        """Load decrypted answers from a JSONL file."""
        answers = {}
        with open(path, "r") as f:
            for line in f:
                doc = json.loads(line)
                answers[doc["query_id"]] = doc["answer"]
        return answers


# ============================================================================
# Other Datasets
# ============================================================================


class WebDataset(SearchDataset):
    """Web search dataset.

    Loads from kellyhongg/web_1_17_test (test split) and kellyhongg/web_train_1_17 (train split).
    If the train dataset is empty/unavailable, falls back to using only the test dataset
    with an 80/20 random split.
    """

    HF_PATH_TRAIN = "kellyhongg/1_17_web_train"
    HF_PATH_TEST = "kellyhongg/1_17_web_test"
    COSMOS_CONTAINERS_TRAIN = [f"web_train_1_17_replica_{i}" for i in range(1, 45)]
    COSMOS_CONTAINERS_TEST = [f"web_test_1_17_replica_{i}" for i in range(1, 45)]

    _gold_document_ids: dict[str, Set[str]]
    _has_presplit: bool = False  # Whether we have separate train/test data

    @property
    def name(self) -> str:
        return "web"

    @property
    def evaluation_mode(self) -> Literal["document", "fact"]:
        return "document"

    def _load_dataset(self) -> None:
        cfg = config.get_config()
        token = cfg.huggingface_token

        test_ds = None
        train_ds = None

        # Load test dataset
        try:
            test_ds = datasets.load_dataset(self.HF_PATH_TEST, token=token)["test"]
        except Exception:
            pass

        # Try loading train dataset
        try:
            raw_train = datasets.load_dataset(self.HF_PATH_TRAIN, token=token)
            # Pick the first available split
            for split_name in ["train", "test"]:
                if split_name in raw_train and len(raw_train[split_name]) > 0:
                    train_ds = raw_train[split_name]
                    break
        except Exception:
            pass

        if train_ds is not None and test_ds is not None:
            # Both available: use pre-split
            self._has_presplit = True
            self._presplit_train_ids = [str(qid) for qid in train_ds["query_id"]]
            self._presplit_test_ids = [str(qid) for qid in test_ds["query_id"]]
            self._search_queries_dataset = datasets.concatenate_datasets([train_ds, test_ds])
        elif test_ds is not None:
            # Only test available: use it with random 80/20 split
            self._has_presplit = False
            self._search_queries_dataset = test_ds
        elif train_ds is not None:
            # Only train available
            self._has_presplit = False
            self._search_queries_dataset = train_ds
        else:
            raise ValueError("Neither train nor test data could be loaded for WebDataset")

        # Extract gold_document_ids
        gold_document_ids = [
            ast.literal_eval(docids) if isinstance(docids, str) else docids
            for docids in self._search_queries_dataset["gold_document_ids"]
        ]
        self._gold_document_ids = {
            str(query_id): set(doc_ids)
            for query_id, doc_ids in zip(
                self._search_queries_dataset["query_id"], gold_document_ids
            )
        }

    def _create_train_test_split(self) -> None:
        """Use pre-split if available, otherwise random 80/20."""
        if self._has_presplit:
            self._train_query_ids = self._presplit_train_ids
            self._test_query_ids = self._presplit_test_ids
        else:
            # Fall back to random split
            super()._create_train_test_split()

    def _get_final_answer_document_ids(self, query_id: str) -> Set[str]:
        """Return only gold document IDs (excluding evidence documents)."""
        return self._gold_document_ids.get(query_id, set())


class EpsteinDataset(SearchDataset):
    HF_PATH = "kellyhongg/epstein_1_14"

    @property
    def name(self) -> str:
        return "epstein"

    @property
    def evaluation_mode(self) -> Literal["document", "fact"]:
        """Epstein uses document-level evaluation."""
        return "document"

    def _load_dataset(self) -> None:
        self._search_queries_dataset = datasets.load_dataset(self.HF_PATH)["test"]
        gold_document_ids = [
            ast.literal_eval(docids)
            for docids in self._search_queries_dataset["gold_document_ids"]
        ]

        self._gold_document_ids = {
            str(query_id): set(doc_ids)
            for query_id, doc_ids in zip(
                self._search_queries_dataset["query_id"], gold_document_ids
            )
        }

    def _get_final_answer_document_ids(self, query_id: str) -> Set[str]:
        """Return only gold document IDs (excluding evidence documents)."""
        return self._gold_document_ids.get(query_id, set())


class PatentsDataset(PreSplitSearchDataset):
    """Patents search dataset with pre-split train/test HF paths."""

    HF_PATH_TRAIN = "kellyhongg/1_18_patents_train"
    HF_PATH_TEST = "kellyhongg/1_18_patents_test"
    HF_SPLIT_TRAIN = "train"
    HF_SPLIT_TEST = "test"
    COSMOS_CONTAINERS_TRAIN = [f"patents_train_1_18_replica_{i}" for i in range(1, 45)]
    COSMOS_CONTAINERS_TEST = [f"patents_test_1_18_replica_{i}" for i in range(1, 45)]

    _gold_document_ids: dict[str, Set[str]]

    @property
    def name(self) -> str:
        return "patents"

    @property
    def evaluation_mode(self) -> Literal["document", "fact"]:
        return "document"

    def _post_load_setup(self) -> None:
        """Extract gold_document_ids from the combined dataset."""
        gold_document_ids = [
            ast.literal_eval(docids) if isinstance(docids, str) else docids
            for docids in self._search_queries_dataset["gold_document_ids"]
        ]
        self._gold_document_ids = {
            str(query_id): set(doc_ids)
            for query_id, doc_ids in zip(
                self._search_queries_dataset["query_id"], gold_document_ids
            )
        }

    def _get_final_answer_document_ids(self, query_id: str) -> Set[str]:
        """Return only gold document IDs (excluding evidence documents)."""
        return self._gold_document_ids.get(query_id, set())


class SECDataset(PreSplitSearchDataset):
    """SEC Filings search dataset with pre-split train/test HF paths.

    Uses sec_1_4 (full combined corpus, ~2.1M chunks) for both train and test
    retrieval. The previous sec_train_1_14 collection was missing ~15% of GT
    chunk IDs for train queries. Test HF data uses kellyhongg/sec_test_new
    which filters out tasks with overlapping chunks.
    """

    HF_PATH_TRAIN = "kellyhongg/1_18_sec_train"
    HF_PATH_TEST = "kellyhongg/sec_test_new"
    HF_SPLIT_TRAIN = "train"
    HF_SPLIT_TEST = "test"
    COSMOS_CONTAINERS_TRAIN = ["sec_1_4"]
    COSMOS_CONTAINERS_TEST = ["sec_1_4"]

    @property
    def name(self) -> str:
        return "sec"

    @property
    def evaluation_mode(self) -> Literal["document", "fact"]:
        """SEC Filings uses fact-level evaluation."""
        return "fact"


class PodcastsTestSet(SearchDataset):
    HF_PATH = "kellyhongg/1_25_podcasts_test"

    @property
    def name(self) -> str:
        return "podcasts_test"

    @property
    def evaluation_mode(self) -> Literal["document", "fact"]:
        """Podcasts uses document-level evaluation."""
        return "document"

    def _load_dataset(self) -> None:
        self._search_queries_dataset = datasets.load_dataset(
            self.HF_PATH, token=config.get_config().huggingface_token
        )["test"]
        gold_document_ids = [
            ast.literal_eval(docids) if isinstance(docids, str) else docids
            for docids in self._search_queries_dataset["gold_document_ids"]
        ]

        # Ensure gold_document_ids are strings (model outputs are strings)
        self._gold_document_ids = {
            str(query_id): set(str(doc_id) for doc_id in doc_ids)
            for query_id, doc_ids in zip(
                self._search_queries_dataset["query_id"], gold_document_ids
            )
        }

    def _get_final_answer_document_ids(self, query_id: str) -> Set[str]:
        """Return only gold document IDs (excluding evidence documents)."""
        return self._gold_document_ids.get(query_id, set())


class WebSimpleDataset(PreSplitSearchDataset):
    """Web Simple search dataset with pre-split train/test HF paths."""

    HF_PATH_TRAIN = "kellyhongg/1_25_web_simple_train"
    HF_PATH_TEST = "kellyhongg/1_25_web_simple_test"
    HF_SPLIT_TRAIN = "train"
    HF_SPLIT_TEST = "test"
    # Same as WebDataset
    COSMOS_CONTAINERS_TRAIN = [f"web_train_1_17_replica_{i}" for i in range(1, 45)]
    COSMOS_CONTAINERS_TEST = [f"web_test_1_17_replica_{i}" for i in range(1, 45)]

    _gold_document_ids: dict[str, Set[str]]

    @property
    def name(self) -> str:
        return "web_simple"

    @property
    def evaluation_mode(self) -> Literal["document", "fact"]:
        return "document"

    def _post_load_setup(self) -> None:
        """Extract gold_document_ids from the combined dataset."""
        gold_document_ids = [
            ast.literal_eval(docids) if isinstance(docids, str) else docids
            for docids in self._search_queries_dataset["gold_document_ids"]
        ]
        self._gold_document_ids = {
            str(query_id): set(str(doc_id) for doc_id in doc_ids)
            for query_id, doc_ids in zip(
                self._search_queries_dataset["query_id"], gold_document_ids
            )
        }

    def _get_final_answer_document_ids(self, query_id: str) -> Set[str]:
        """Return only gold document IDs (excluding evidence documents)."""
        return self._gold_document_ids.get(query_id, set())


class SECSimpleDataset(PreSplitSearchDataset):
    """SEC Simple search dataset with pre-split train/test HF paths."""

    HF_PATH_TRAIN = "kellyhongg/1_25_sec_simple_train"
    HF_PATH_TEST = "kellyhongg/1_25_sec_simple_test"
    HF_SPLIT_TRAIN = "train"
    HF_SPLIT_TEST = "test"
    COSMOS_CONTAINERS_TRAIN = ["sec_1_4"]
    COSMOS_CONTAINERS_TEST = ["sec_1_4"]

    @property
    def name(self) -> str:
        return "sec_simple"

    @property
    def evaluation_mode(self) -> Literal["document", "fact"]:
        """SEC Simple uses fact-level evaluation."""
        return "fact"


# ============================================================================
# Additional Benchmark Datasets (Kelly April 2026 refresh)
# ============================================================================


class BCPlusDataset(SingleSplitSearchDataset):
    """BrowseComp+ benchmark loaded directly from HuggingFace."""

    HF_PATH = "kellyhongg/bc_plus"
    HF_SPLIT_PREFERENCES = ("test", "train")
    COSMOS_CONTAINERS = ["browsecomp_corpus_container"]

    def get_cosmos_containers(self, split=None):
        return [config.get_config().cosmos_corpus_container]

    _gold_document_ids: dict[str, Set[str]]

    @property
    def name(self) -> str:
        return "bc_plus"

    def _load_dataset(self) -> None:
        self._search_queries_dataset = load_hf_dataset_first_available(
            self.HF_PATH, split_preferences=self.HF_SPLIT_PREFERENCES
        )

        gold_document_ids = [
            ast.literal_eval(docids) if isinstance(docids, str) else docids
            for docids in self._search_queries_dataset["gold_document_ids"]
        ]
        self._gold_document_ids = {
            str(query_id): {
                normalize_document_id(str(doc_id)) for doc_id in doc_ids
            }
            for query_id, doc_ids in zip(
                self._search_queries_dataset["query_id"], gold_document_ids
            )
        }

    def _get_final_answer_document_ids(self, query_id: str) -> Set[str]:
        return self._gold_document_ids.get(query_id, set())


class LongSealQADataset(SingleSplitSearchDataset):
    """LongSealQA retrieval dataset backed by a Chroma collection."""

    HF_PATH = "kellyhongg/longsealqa"
    HF_SPLIT_PREFERENCES = ("test", "train")
    COSMOS_CONTAINERS = ["longsealqa"]

    @property
    def name(self) -> str:
        return "longsealqa"


class Seal0QADataset(SingleSplitSearchDataset):
    """Seal0QA open-web retrieval dataset (web search based)."""

    HF_PATH = "kellyhongg/seal0qa"
    HF_SPLIT_PREFERENCES = ("test", "train")

    @property
    def name(self) -> str:
        return "seal0qa"


class FramesDataset(SingleSplitSearchDataset):
    """FRAMES benchmark for Wikipedia-focused retrieval."""

    HF_PATH = "kellyhongg/frames"
    HF_SPLIT_PREFERENCES = ("test", "train")

    @property
    def name(self) -> str:
        return "frames"


class HotpotQASubsetDataset(SingleSplitSearchDataset):
    """HotpotQA subset benchmark for Wikipedia-focused retrieval."""

    HF_PATH = "kellyhongg/hotpotqa_subset"
    HF_SPLIT_PREFERENCES = ("test", "train")

    @property
    def name(self) -> str:
        return "hotpotqa_subset"


# ============================================================================
# SEC Filings Dataset (legacy - uses HuggingFace kellyhongg/sec_filings)
# ============================================================================


class SECFilingsDataset(SearchDataset):
    """SEC Filings search dataset from HuggingFace.

    This dataset uses fact-level evaluation where document_ids contains a list of
    fact objects, each with chunk_ids. A fact is considered found if ANY of its
    chunk_ids are retrieved.
    """

    HF_PATH = "kellyhongg/sec_filings"
    COSMOS_CONTAINERS = [f"latest_sec_filings_replica_{i}" for i in range(46)]

    @property
    def name(self) -> str:
        return "sec_filings"

    @property
    def evaluation_mode(self) -> Literal["document", "fact"]:
        """SEC Filings uses fact-level evaluation."""
        return "fact"

    def _load_dataset(self) -> None:
        self._search_queries_dataset = datasets.load_dataset(self.HF_PATH)["test"]

    def get_cosmos_containers(
        self, split: Optional[Literal["train", "test"]] = None
    ) -> List[str]:
        """Return the Cosmos container names for SEC Filings."""
        return self.COSMOS_CONTAINERS


# ============================================================================
# QA-Only Benchmark Datasets (no document_ids, answer-evaluation only)
# ============================================================================


class DeepSearchDataset(SearchDataset):
    """xbench/DeepSearch benchmark dataset.

    This is an answer-evaluation benchmark (no document_ids / recall evaluation).
    The dataset is encrypted; the decrypt code is available at the xbench_evals
    GitHub repo. We load the raw HF dataset and map it to the SearchDataset
    interface with empty document_ids so that the query/answer pipeline works.

    HF columns: id, prompt, answer, reference_steps, canary
    """

    HF_PATH = "xbench/DeepSearch"

    @property
    def name(self) -> str:
        return "deepsearch"

    def _load_dataset(self) -> None:
        raw_ds = datasets.load_dataset(self.HF_PATH, split="train")

        self._search_queries_dataset = datasets.Dataset.from_dict(
            {
                "query_id": [str(row["id"]) for row in raw_ds],
                "query": [row["prompt"] for row in raw_ds],
                "document_ids": [[] for _ in range(len(raw_ds))],
                "answer": [row["answer"] for row in raw_ds],
            }
        )


class GAIADataset(SearchDataset):
    """GAIA benchmark dataset (gaia-benchmark/GAIA).

    This is an answer-evaluation benchmark for general AI assistants.
    It is a gated dataset — you must accept the terms on the HF page before
    loading:  https://huggingface.co/datasets/gaia-benchmark/GAIA

    We load the '2023_all' config and combine validation + test splits.
    HF columns: task_id, Question, Level, Final answer, file_name, file_path,
                Annotator Metadata

    document_ids is set to empty because GAIA does not provide retrieval labels.
    """

    HF_PATH = "gaia-benchmark/GAIA"
    HF_CONFIG = "2023_all"

    @property
    def name(self) -> str:
        return "gaia"

    def _load_dataset(self) -> None:
        cfg = config.get_config()
        token = cfg.huggingface_token

        raw_ds = datasets.load_dataset(
            self.HF_PATH, self.HF_CONFIG, token=token
        )

        # GAIA typically has 'validation' and 'test' splits.
        # 'test' answers are hidden, so we use 'validation' as our primary data.
        # If both exist, concatenate them; otherwise use whichever is available.
        splits_to_use = []
        for split_name in ["validation", "test"]:
            if split_name in raw_ds:
                splits_to_use.append(raw_ds[split_name])

        if not splits_to_use:
            raise ValueError(
                f"GAIA dataset has no usable splits. Available: {list(raw_ds.keys())}"
            )

        combined = datasets.concatenate_datasets(splits_to_use)

        self._search_queries_dataset = datasets.Dataset.from_dict(
            {
                "query_id": [str(row["task_id"]) for row in combined],
                "query": [row["Question"] for row in combined],
                "document_ids": [[] for _ in range(len(combined))],
                "answer": [row["Final answer"] for row in combined],
            }
        )


# ============================================================================
# Dataset Registry & Factory
# ============================================================================




# ============================================================================
# Enterprise RAG Bench Dataset (Onyx EnterpriseRAG-Bench)
# ============================================================================


class EnterpriseRagBenchDataset(SearchDataset):
    """Onyx EnterpriseRAG-Bench, 500-question leaderboard split.

    Document-level retrieval eval. 30 of the 500 questions
    (high_level + info_not_found) have empty `expected_doc_ids` — they are
    included by default but contribute recall=0.
    """

    _gold_document_ids: dict

    def get_cosmos_containers(self, split=None):
        import os
        return [os.environ.get("ENT_RAG_CONTAINER", "enterprise_ragbench_corpus")]

    @property
    def name(self) -> str:
        return "enterprise_rag"

    def _load_dataset(self) -> None:
        ds = datasets.load_dataset(
            "onyx-dot-app/EnterpriseRAG-Bench", "questions", split="test"
        )
        rows = []
        for r in ds:
            qid = r.get("question_id") or r.get("qid")
            if qid is None:
                continue
            rows.append({
                "qid": str(qid),
                "question": r.get("question", ""),
                "expected_doc_ids": list(r.get("expected_doc_ids") or []),
                "gold_answer": r.get("gold_answer", ""),
            })
        self._gold_document_ids = {
            r["qid"]: set(r["expected_doc_ids"]) for r in rows
        }
        self._search_queries_dataset = datasets.Dataset.from_dict({
            "query_id": [r["qid"] for r in rows],
            "query": [r["question"] for r in rows],
            "document_ids": [list(r["expected_doc_ids"]) for r in rows],
            "answer": [r["gold_answer"] for r in rows],
        })

    def _get_final_answer_document_ids(self, query_id):
        return self._gold_document_ids.get(query_id, set())

    def _create_train_test_split(self) -> None:
        all_query_ids = sorted(self._query_index.keys())
        self._train_query_ids = all_query_ids
        self._test_query_ids = all_query_ids


DATASET_REGISTRY: dict[str, type[SearchDataset]] = {
    "browsecompplus": BrowseCompPlusDataset,
    "enterprise_rag": EnterpriseRagBenchDataset,
    "bc_plus": BCPlusDataset,
    "epstein": EpsteinDataset,
    "longsealqa": LongSealQADataset,
    "seal0qa": Seal0QADataset,
    "frames": FramesDataset,
    "hotpotqa_subset": HotpotQASubsetDataset,
    "podcasts_test": PodcastsTestSet,
    "web": WebDataset,
    "patents": PatentsDataset,
    "sec": SECDataset,
    "web_simple": WebSimpleDataset,
    "sec_simple": SECSimpleDataset,
    "sec_filings": SECFilingsDataset,  # Legacy dataset - works with existing collections
    "deepsearch": DeepSearchDataset,
    "gaia": GAIADataset,
}


def get_dataset(name: str) -> SearchDataset:
    """Create a search dataset by name.

    Args:
        name: The dataset name. Available datasets:
            - "browsecompplus": BrowseComp+ dataset
            - "bc_plus": BrowseComp+ HF dataset variant (single collection)
            - "epstein": Epstein dataset
            - "longsealqa": LongSeal QA dataset
            - "seal0qa": Seal0 QA dataset (open-web)
            - "frames": FRAMES dataset
            - "hotpotqa_subset": HotpotQA subset dataset
            - "podcasts_test": Podcasts test dataset
            - "web": Web dataset (pre-split train/test)
            - "patents": Patents dataset (pre-split train/test)
            - "sec": SEC Filings dataset (pre-split train/test)
            - "web_simple": Web Simple dataset (pre-split train/test)
            - "sec_simple": SEC Simple dataset (pre-split train/test)
            - "deepsearch": xbench/DeepSearch benchmark (answer-eval only)
            - "gaia": GAIA benchmark (answer-eval only, gated)

    Returns:
        An instance of the corresponding dataset class.

    Raises:
        ValueError: If the dataset name is not recognized.
    """
    if name not in DATASET_REGISTRY:
        available = ", ".join(DATASET_REGISTRY.keys())
        raise ValueError(f"Unknown dataset: {name}. Available datasets: {available}")
    return DATASET_REGISTRY[name]()
