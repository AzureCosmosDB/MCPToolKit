from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel


class SchemaOverride(BaseModel):
    """User-supplied hints layered on top of live schema discovery.

    Discovery reads the container's physical schema (vector fields, full-text
    paths, partition keys) but cannot infer the *semantic role* of fields. This
    override names them so chunks can be grouped back into parent documents:

      - ``document_id_path``  path of the parent-document id (groups chunks)
      - ``chunk_id_path``     path of the per-chunk id
      - ``chunk_order_path``  path of the chunk ordinal (orders chunks)
      - ``title_path`` / ``source_path``  optional display fields
      - ``item_id_path``      path of the item id (defaults to ``/id``)
      - ``use_dunder_codec``  chunk ids are encoded ``<docid>__<chunkindex>``

    These paths are **not** canonical Cosmos fields and are not guaranteed to
    exist. Cosmos DB is schema-agnostic: the only field present on every
    document is ``/id`` (plus system props like ``_rid``/``_ts``), which is why
    ``item_id_path`` defaults to ``/id``. The remaining paths are
    application-specific — they exist only if the ingestion pipeline created
    them — and are only meaningful for *chunked* (RAG) corpora where one logical
    document is split across many records. For one-record-per-document data,
    omit them: each item is then treated as its own document
    (see ``CorpusSchema.is_item_document_mode``). ``use_dunder_codec`` is a
    naming convention, not a Cosmos feature.

    All fields are optional; omit the object entirely for pure discovery.
    """

    model_config = {"extra": "forbid"}

    item_id_path: str | None = None
    document_id_path: str | None = None
    chunk_id_path: str | None = None
    chunk_order_path: str | None = None
    title_path: str | None = None
    source_path: str | None = None
    use_dunder_codec: bool = False

    @classmethod
    def coerce(cls, value: Any) -> "SchemaOverride | None":
        """Build a SchemaOverride from ``None``, a dict, a JSON string, or an
        existing instance. Returns ``None`` for empty/blank input."""
        if value is None:
            return None
        if isinstance(value, SchemaOverride):
            return value
        if isinstance(value, str):
            text = value.strip()
            if not text or text.lower() in {"none", "null"}:
                return None
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"schema_override is not valid JSON: {exc}") from exc
        if isinstance(value, dict):
            if not value:
                return None
            return cls(**value)
        raise ValueError(
            f"schema_override must be a JSON object (or null), got {type(value).__name__}."
        )

    def stable_key(self) -> str:
        """Deterministic string form for cache keys."""
        return json.dumps(self.model_dump(), sort_keys=True)
