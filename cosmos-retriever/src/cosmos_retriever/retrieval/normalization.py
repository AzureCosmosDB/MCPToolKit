from __future__ import annotations

from typing import Any

from cosmos_retriever.retrieval.models import RetrievedItem


def _display_text(
    text_fields: dict[str, str],
    fallback: str,
    queried: list[str] | None,
    primary: str | None,
) -> str:

    names = [n for n in (queried or []) if n in text_fields]
    if not names:
        if primary and primary in text_fields:
            return text_fields[primary]
        return fallback
    if primary and primary in text_fields and primary not in names:
        names = [*names, primary]
    if len(names) == 1:
        return text_fields.get(names[0], "") or ""
    return "\n\n".join(f"[{n}]\n{text_fields.get(n, '') or ''}" for n in names)


def normalize_rows(
    rows: list[dict[str, Any]],
    *,
    strategy: str,
    channels: list[str] | None = None,
    start_rank: int = 0,
    projected_aliases: dict[str, str] | None = None,
    queried_text_fields: list[str] | None = None,
    primary_text_field: str | None = None,
) -> list[RetrievedItem]:
    aliases = projected_aliases or {}
    items: list[RetrievedItem] = []
    for i, row in enumerate(rows):
        metadata = {
            key[len("md_") :]: value for key, value in row.items() if key.startswith("md_")
        }
        text_fields: dict[str, str] = {}
        for key, value in row.items():
            if key.startswith("txt_") and key in aliases:
                text_fields[aliases[key]] = value or ""
        display = _display_text(
            text_fields,
            row.get("text", "") or "",
            queried_text_fields,
            primary_text_field,
        )
        chunk_order = row.get("chunk_order")
        items.append(
            RetrievedItem(
                item_id=str(row.get("item_id")),
                document_id=(str(row["document_id"]) if row.get("document_id") is not None else None),
                chunk_id=(str(row["chunk_id"]) if row.get("chunk_id") is not None else None),
                chunk_order=chunk_order if isinstance(chunk_order, int) else None,
                text=display,
                text_fields=text_fields,
                title=row.get("title"),
                source=row.get("source"),
                metadata=metadata,
                retrieval_strategy=strategy,
                retrieval_channels=list(channels or []),
                rank=start_rank + i,
            )
        )
    return items
