from __future__ import annotations

from typing import Any

from cosmos_retriever.retrieval.models import RetrievedItem


def row_text_fields(row: dict[str, Any], aliases: dict[str, str]) -> dict[str, str]:

    out: dict[str, str] = {}
    for key, value in row.items():
        if key.startswith("txt_") and key in aliases:
            out[aliases[key]] = value or ""
    return out


def assemble_text(text_fields: dict[str, str], names: list[str] | None = None) -> str:

    selected = [n for n in names if n in text_fields] if names else list(text_fields)
    if not selected:
        return ""
    if len(selected) == 1:
        return text_fields.get(selected[0], "") or ""
    return "\n\n".join(f"[{n}]\n{text_fields.get(n, '') or ''}" for n in selected)


def normalize_rows(
    rows: list[dict[str, Any]],
    *,
    strategy: str,
    channels: list[str] | None = None,
    start_rank: int = 0,

    projected_aliases: dict[str, str] | None = None,
    queried_text_fields: list[str] | None = None,
) -> list[RetrievedItem]:
    aliases = projected_aliases or {}
    items: list[RetrievedItem] = []

    for i, row in enumerate(rows):
        metadata = {

            key[len("md_") :]: value for key, value in row.items() if key.startswith("md_")
        }
        text_fields = row_text_fields(row, aliases)
        display = assemble_text(text_fields, queried_text_fields)
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
