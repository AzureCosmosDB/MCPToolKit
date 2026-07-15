from __future__ import annotations

DOC_TRUNCATION = 51_200_000


def format_result_blocks(
    triples: list[tuple[str, str, int | None]],
) -> str:

    blocks = [
        "\n# DOCUMENT ID: {}{} \n{}".format(
            id_,
            f" ({tokens} tokens)" if tokens is not None else "",
            text[:DOC_TRUNCATION],
        )
        for id_, text, tokens in triples
    ]
    return "\n".join(blocks) if blocks else "No results found"
