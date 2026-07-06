# Cosmos Retriever (Python helper)

A Python library + FastAPI service that runs the **Harness-1** multi-turn
search agent (`pat-jj/harness-1`, a fine-tuned `openai/gpt-oss-20b` served by
vLLM) against an Azure Cosmos DB corpus and returns the curated documents as
JSON.

The [Azure Cosmos DB MCP Toolkit](../MCPToolKit/)'s `agentic_search` tool
calls this service's `POST /search` endpoint over HTTP. A one-shot CLI is also
provided for local testing.

```text
  Claude Desktop / AI Foundry / VS Code
            │
            │   MCP streamable-HTTP
            ▼
  Azure Cosmos DB MCP Toolkit  (.NET)
   ├─ list_databases / list_collections / ...   (8 native tools)
   └─ agentic_search                            ◀─── 9th tool
            │
            │   HTTP: POST http://127.0.0.1:9000/search
            ▼
  cosmos_retriever  (this package, FastAPI + uvicorn)
   ├─ TokenBudgetRetrievalSubagent
   ├─ SearchCorpus / Grep / ReadDocument / PruneChunks tools
    └─ OpenAI-compatible model  ──► /responses or /chat/completions
```

## Install

```bash
cd cosmos-retriever
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
```

## HTTP service

The MCP Toolkit talks to a long-lived FastAPI service. Start it with:

```bash
python -m cosmos_retriever serve            # binds HOST:PORT (default 0.0.0.0:9000)
```

Endpoints:

| Method & path | Body / response |
|---|---|
| `GET /health` | `{"status": "ok"}` |
| `POST /search` | request `{"query": str, "maxDocuments": int, "database": str?, "container": str?}` → the JSON result below |

```bash
curl -s http://127.0.0.1:9000/search \
  -H 'content-type: application/json' \
  -d '{"query": "Who discovered radium?", "maxDocuments": 5}'
```

## CLI

A one-shot CLI for local testing. JSON goes to **stdout**, logs go to **stderr**.

```bash
python -m cosmos_retriever search \
  --query "Who discovered radium?" \
  --max-documents 5
```

Output (same schema returned by `POST /search`):
```json
{
  "query": "Who discovered radium?",
  "num_turns": 5,
  "elapsed_s": 32.3,
  "documents": [
    { "id": "96308__3", "rank": 0, "justification": "...", "text": "..." }
  ]
}
```

## Configuration

All settings come from environment variables (or a `.env` / `.env.local` file
at the repo root). Required:

| Variable | Purpose |
|---|---|
| `CHAT_BASE_URL` / `CHAT_MODEL` / `CHAT_API_KEY` | OpenAI-compatible model endpoint |
| `ACCOUNT_URI` / `COSMOS_DATABASE` / `COSMOS_CORPUS_CONTAINER` | Cosmos target |
| `OPENAI_API_KEY` *(or `AZURE_OPENAI_*`)* | Embeddings backend |

### Inference backend

`INFERENCE_BACKEND` selects which OpenAI-compatible API surface drives the
retrieval agent over the four Cosmos tools:

| Value | API | Endpoint vars |
|---|---|---|
| `openai_responses` *(default)* | The `/responses` API, required by reasoning models such as gpt-5.x. | `CHAT_BASE_URL`, `CHAT_API_KEY`, `CHAT_MODEL`, optional `CHAT_API_VERSION`, `CHAT_REASONING_EFFORT` |
| `openai_chat` | The `/chat/completions` API for standard chat models. | `CHAT_BASE_URL`, `CHAT_API_KEY`, `CHAT_MODEL`, optional `CHAT_API_VERSION` |

Either way the agent uses the same Cosmos tools, so retrieval quality depends on
the chosen model's tool-use ability. Example (Azure AI Foundry):

```bash
INFERENCE_BACKEND=openai_chat \
CHAT_BASE_URL=https://your-resource.services.ai.azure.com/openai/v1 \
CHAT_API_KEY=... \
CHAT_MODEL=gpt-4o \
python -m cosmos_retriever serve
```

Optional reranker (pick at most one):
- `BASETEN_API_KEY` + `BASETEN_MODEL_URL` — Baseten Qwen3-Reranker-8B classify
- `VLLM_RERANKER_URL` — local vLLM `/score` endpoint with Qwen3-Reranker-8B

A bundled wrapper script reads `../harness-1/.env.local` (the upstream repo's
local config) and re-exports under our variable names:

```bash
scripts/run_with_upstream_env.sh \
  python -m cosmos_retriever search --query "..."
```

## Layout

```text
src/cosmos_retriever/
  __init__.py        # CosmosRetriever, RetrievalResult, RetrievedDocument
  __main__.py        # `python -m cosmos_retriever {search,serve}`
  server.py          # FastAPI app: GET /health + POST /search
  retriever.py       # CosmosRetriever facade
  tools.py           # SearchCorpus / Grep / ReadDocument / PruneChunks
  rerank.py          # Reranker ABC + Baseten + local-vLLM
  inference/
    openai_chat.py   # run_chat_search / run_responses_search (4-tool)
  prompts.py         # retrieval subagent system prompt
  config.py          # RetrieverSettings (pydantic-settings)
  utils.py
```

## License

Apache 2.0.
