
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
        help="Cosmos database name to query (required).",
    )
    search.add_argument(
        "--container",
        default=None,
        help="Optional Cosmos container to narrow to; omit to search the whole database.",
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
    from cosmos_retriever.config import get_settings
    from cosmos_retriever.retriever import CosmosRetriever

    settings = get_settings()
    if args.database:
        settings.cosmos_database = args.database

    # Container is optional: default to the whole database (cross-collection).
    container = args.container or "*"
    retriever = CosmosRetriever(settings=settings, corpus_name=container)
    result = retriever.search(args.query, max_documents=args.max_documents)
    json.dump(asdict(result), sys.stdout, default=str, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.stdout.flush()
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from cosmos_retriever.config import get_settings
    from cosmos_retriever.server import create_app

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
    except Exception as exc:
        json.dump(
            {"error": str(exc), "type": type(exc).__name__},
            sys.stdout,
            ensure_ascii=False,
        )
        sys.stdout.write("\n")
        sys.stdout.flush()
        return 1
    parser.error(f"Unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
