"""``python -m cosmos_retriever search ...`` — one-shot CLI.

Designed to be invoked as a subprocess by the Azure Cosmos DB MCP Toolkit's
``agentic_search`` tool. Prints a single JSON document to **stdout**;
structured logs go to **stderr** so the consumer can pipe stdout straight
into ``json.loads`` / ``JsonDocument.Parse`` without filtering.

Output schema::

    {
      "query":         str,
      "num_turns":     int,
      "elapsed_s":     float,
      "documents": [
        { "id": str, "text": str, "justification": str | null, "rank": int }
      ]
    }

Errors are printed as ``{"error": "<message>"}`` to stdout with non-zero exit.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cosmos-retriever",
        description="Run the multi-turn Cosmos retrieval agent and emit JSON.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    search = sub.add_parser("search", help="Run one search end-to-end.")
    search.add_argument("--query", required=True)
    search.add_argument("--max-documents", type=int, default=20)
    search.add_argument(
        "--database",
        default=None,
        help="Override Cosmos database name (else COSMOS_DATABASE env var).",
    )
    search.add_argument(
        "--container",
        default=None,
        help="Override Cosmos corpus container name (else COSMOS_CORPUS_CONTAINER env var).",
    )

    serve = sub.add_parser(
        "serve",
        help="Run the FastAPI HTTP service the MCP Toolkit calls into.",
    )
    serve.add_argument(
        "--host",
        default=None,
        help="Bind address (else HOST env var, default 0.0.0.0).",
    )
    serve.add_argument(
        "--port",
        type=int,
        default=None,
        help="Bind port (else PORT env var, default 9000).",
    )
    return parser


def _cmd_search(args: argparse.Namespace) -> int:
    # Defer heavy imports so `--help` and bad CLI calls fail fast without
    # initialising clients (or scanning .env). `get_settings()` calls
    # `init_logging()` itself, so we don't need to call it explicitly.
    from cosmos_retriever.config import get_settings  # noqa: PLC0415
    from cosmos_retriever.retriever import CosmosRetriever  # noqa: PLC0415

    settings = get_settings()
    if args.database:
        # Manual database override only meaningful when no registry entry
        # already pins the database for this container.
        settings.cosmos_database = args.database

    retriever = CosmosRetriever(settings=settings, corpus_name=args.container)
    result = retriever.search(args.query, max_documents=args.max_documents)
    json.dump(asdict(result), sys.stdout, default=str, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.stdout.flush()
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    # Defer heavy imports so `--help` stays fast and import errors surface here.
    import uvicorn  # noqa: PLC0415

    from cosmos_retriever.config import get_settings  # noqa: PLC0415
    from cosmos_retriever.server import create_app  # noqa: PLC0415

    settings = get_settings()
    host = args.host or settings.host
    port = args.port or settings.port
    app = create_app(settings)
    uvicorn.run(app, host=host, port=port, log_level=settings.log_level.lower())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.cmd == "search":
            return _cmd_search(args)
        if args.cmd == "serve":
            return _cmd_serve(args)
    except Exception as exc:  # noqa: BLE001 — propagate as JSON error to caller
        json.dump(
            {"error": str(exc), "type": type(exc).__name__},
            sys.stdout,
            ensure_ascii=False,
        )
        sys.stdout.write("\n")
        sys.stdout.flush()
        return 1
    parser.error(f"Unknown command: {args.cmd}")
    return 2  # unreachable


if __name__ == "__main__":
    raise SystemExit(main())
