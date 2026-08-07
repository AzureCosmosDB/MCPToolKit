
"""Pick the search strategy that best fits a container.

Different containers can do different things: some are set up for vector search,
some for full text search, some for both, some for neither. This module looks at
what a container actually supports and chooses how a given request should be run,
handing back a ready-to-use strategy object.

The choice is driven by two inputs. The corpus schema says which fields exist and
where they live; the capabilities (see the capabilities file) say which of those
fields are truly searchable, and how.

A request may also pin a mode outright, in which case the planner either follows
it or raises if the container can't satisfy it. Left on auto, it prefers the
richest option available and falls back gracefully: native hybrid if the
container ranks vector and text together for you, otherwise combining the two
results itself, then whichever single mode is available, and finally a bounded
scan if the policy permits one.

The planner only decides, it does not run anything. The strategy it returns (one
of the classes defined in the strategies file) is what goes on to build SQL
through the compiler and run it through the executor.
"""

from __future__ import annotations

import structlog

from cosmos_retriever.retrieval.capabilities import RetrievalCapabilities, SupportLevel
from cosmos_retriever.retrieval.errors import UnsupportedRetrievalCapability
from cosmos_retriever.retrieval.models import GrepRequest, PartitionQueryPolicy, SearchRequest
from cosmos_retriever.retrieval.schema import CorpusSchema
from cosmos_retriever.retrieval.strategies import (
    BoundedScanStrategy,
    ClientSideFusionStrategy,
    FullTextGrepCandidateStrategy,
    FullTextSearchStrategy,
    GrepCandidateStrategy,
    NativeHybridStrategy,
    SearchStrategy,
    VectorSearchStrategy,
)

logger = structlog.get_logger("cosmos_retriever.retrieval.planner")


class RetrievalPlanner:
    def __init__(
        self,
        schema: CorpusSchema,
        capabilities: RetrievalCapabilities,
        policy: PartitionQueryPolicy,
    ) -> None:
        self.schema = schema
        self.capabilities = capabilities
        self.policy = policy

    def _vector_ok(self, req: SearchRequest | None = None) -> bool:
        if not self.schema.vector_fields or not self.capabilities.vector_supported:
            return False
        name = req.vector_field if req is not None else None
        try:
            field = self.schema.resolve_vector_config(name)
        except Exception:
            return False
        cap = self.capabilities.vector_capability_for(field.path)
        if cap is None or cap.support in (SupportLevel.UNSUPPORTED, SupportLevel.UNKNOWN):
            return False
        if cap.dimensions != field.dimensions:
            logger.warning(
                "embedding_dimension_mismatch",
                schema_dims=field.dimensions,
                capability_dims=cap.dimensions,
            )
            return False
        return True

    def _fts_ok(self, req: SearchRequest | None = None) -> bool:
        if not self.capabilities.full_text_supported:
            return False
        names = req.text_fields if req is not None else None
        if not names:
            # No specific field requested. Full-text is available as long as the
            # schema exposes at least one full-text-capable field; the concrete
            # field(s) must be chosen by the caller at execution time.
            return any(
                self.capabilities.has_full_text_path(p) for p in self.schema.text_paths
            )
        try:
            paths = self.schema.resolve_text_fields(names)
        except Exception:
            return False
        return all(self.capabilities.has_full_text_path(p) for p in paths)

    def plan_search(self, req: SearchRequest) -> SearchStrategy:
        vector_ok = self._vector_ok(req)
        fts_ok = self._fts_ok(req)
        mode = getattr(req, "mode", "auto")

        if mode == "vector":
            if not vector_ok:
                raise UnsupportedRetrievalCapability(
                    "vector mode requested but the selected vector field is unavailable "
                    "or embedding-incompatible"
                )
            return VectorSearchStrategy()
        if mode == "text":
            if not fts_ok:
                raise UnsupportedRetrievalCapability(
                    "text mode requested but full-text search is unavailable for the "
                    "selected field(s)"
                )
            return FullTextSearchStrategy()
        if mode == "hybrid":
            if vector_ok and fts_ok:
                return (
                    NativeHybridStrategy()
                    if self.capabilities.native_hybrid_supported
                    else ClientSideFusionStrategy()
                )
            raise UnsupportedRetrievalCapability(
                "hybrid mode requested but vector and full-text are not both available "
                "for the selected fields"
            )

        if self.capabilities.native_hybrid_supported and vector_ok and fts_ok:
            return NativeHybridStrategy()
        if vector_ok and fts_ok:
            return ClientSideFusionStrategy()
        if vector_ok:
            return VectorSearchStrategy()
        if fts_ok:
            return FullTextSearchStrategy()
        if self.policy.allow_bounded_scan:
            return BoundedScanStrategy()
        raise UnsupportedRetrievalCapability(
            "no search strategy available for the configured container"
        )

    def plan_grep(self, req: GrepRequest) -> GrepCandidateStrategy:
        if self.capabilities.full_text_supported:
            return FullTextGrepCandidateStrategy()
        raise UnsupportedRetrievalCapability(
            "grep requires a full-text candidate source, which is unavailable"
        )
