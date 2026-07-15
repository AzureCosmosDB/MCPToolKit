"""Typed errors for the retrieval layer.

These make failure modes explicit instead of silently degrading to a weaker
query. Never catch a Cosmos exception and "try something cheaper" — surface one
of these so the caller (and startup validation) can react deliberately.
"""

from __future__ import annotations


class RetrievalError(Exception):
    """Base class for all retrieval-layer errors."""


class InvalidCorpusSchema(RetrievalError):
    """The configured :class:`CorpusSchema` is internally inconsistent."""


class UnsafeCosmosPath(RetrievalError):
    """A configured property path could not be safely parsed/rendered."""


class UnsupportedRetrievalCapability(RetrievalError):
    """No strategy can satisfy the request against the configured container."""


class UnknownField(RetrievalError):
    """The caller requested a text/vector field name not present in the schema."""


class EmbeddingProfileMismatch(RetrievalError):
    """Query embedding is incompatible with the stored vector policy."""


class MissingPartitionKey(RetrievalError):
    """A partition key is required for a safe query but none was supplied."""


class CrossPartitionQueryDisabled(RetrievalError):
    """A cross-partition query is required but disallowed by policy."""


class UnboundedScanRejected(RetrievalError):
    """A plan would scan the container and bounded-scan is not enabled."""


class DocumentResolutionUnsupported(RetrievalError):
    """The configured schema cannot reconstruct a complete document."""


class QueryCompilationError(RetrievalError):
    """A logical plan could not be compiled into valid Cosmos SQL."""


class IndexNotReady(RetrievalError):
    """A required index exists but is still transforming."""
