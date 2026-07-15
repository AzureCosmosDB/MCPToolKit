
from __future__ import annotations


class RetrievalError(Exception):
    pass


class InvalidCorpusSchema(RetrievalError):
    pass


class UnsafeCosmosPath(RetrievalError):
    pass


class UnsupportedRetrievalCapability(RetrievalError):
    pass


class UnknownField(RetrievalError):
    pass


class EmbeddingProfileMismatch(RetrievalError):
    pass


class MissingPartitionKey(RetrievalError):
    pass


class CrossPartitionQueryDisabled(RetrievalError):
    pass


class UnboundedScanRejected(RetrievalError):
    pass


class DocumentResolutionUnsupported(RetrievalError):
    pass


class QueryCompilationError(RetrievalError):
    pass


class IndexNotReady(RetrievalError):
    pass
