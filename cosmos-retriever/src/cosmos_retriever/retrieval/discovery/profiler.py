from __future__ import annotations

import time
from typing import Any

from cosmos_retriever.retrieval.discovery.models import (
    CapabilityFlag,
    CapabilityProfile,
    ContainerMetadata,
    VectorIndexInfo,
)


def parse_container_metadata(
    database: str,
    container: str,
    props: dict[str, Any],
    etag: str | None = None,
    *,
    fetched_at: float | None = None,
) -> ContainerMetadata:
    pk_paths = list((props.get("partitionKey") or {}).get("paths") or [])

    idx = props.get("indexingPolicy") or {}
    included = [p.get("path") for p in (idx.get("includedPaths") or []) if p.get("path")]
    excluded = [p.get("path") for p in (idx.get("excludedPaths") or []) if p.get("path")]
    ft_index_paths = [p.get("path") for p in (idx.get("fullTextIndexes") or []) if p.get("path")]
    vec_index = {p.get("path"): p for p in (idx.get("vectorIndexes") or []) if p.get("path")}

    ftp = props.get("fullTextPolicy") or {}
    ft_policy_paths = [p.get("path") for p in (ftp.get("fullTextPaths") or []) if p.get("path")]

    vep = props.get("vectorEmbeddingPolicy") or {}
    vectors: list[VectorIndexInfo] = []
    for emb in vep.get("vectorEmbeddings") or []:
        path = emb.get("path")
        if not path:
            continue
        vi = vec_index.get(path)
        vectors.append(
            VectorIndexInfo(
                path=path,
                dimensions=emb.get("dimensions"),
                distance_function=emb.get("distanceFunction"),
                data_type=emb.get("dataType"),
                index_type=(vi or {}).get("type"),
                indexed=vi is not None,
            )
        )

    return ContainerMetadata(
        database=database,
        container=container,
        etag=etag,
        fetched_at=fetched_at if fetched_at is not None else time.time(),
        partition_key_paths=pk_paths,
        included_paths=included,
        excluded_paths=excluded,
        full_text_paths=ft_index_paths,
        full_text_policy_paths=ft_policy_paths,
        vector_fields=vectors,
    )


class CapabilityProfiler:
    def profile(self, metadata: ContainerMetadata) -> CapabilityProfile:
        indexed_vectors = [v for v in metadata.vector_fields if v.indexed]
        has_fts = bool(metadata.full_text_paths)
        has_vec = bool(indexed_vectors)

        strategies: list[str] = []
        if has_vec and has_fts:
            strategies.append("native_hybrid")
        if has_vec:
            strategies.append("vector")
        if has_fts:
            strategies.append("full_text")
        strategies.append("item_lookup")

        return CapabilityProfile(
            database=metadata.database,
            container=metadata.container,
            fetched_at=metadata.fetched_at,
            partition_key_paths=metadata.partition_key_paths,
            full_text_paths=metadata.full_text_paths,
            vector_fields=indexed_vectors,
            can_full_text=CapabilityFlag(value=has_fts),
            can_vector=CapabilityFlag(value=has_vec),
            can_native_hybrid=CapabilityFlag(value=has_vec and has_fts),
            can_item_lookup=CapabilityFlag(value=True),
            recommended_strategies=strategies,
            confidence=1.0,
        )
