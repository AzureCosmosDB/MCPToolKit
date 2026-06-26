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
   └─ VLLMHarmonyInferenceModel  ──► vLLM /v1/completions (token-IDs)
                                     Cosmos DB hybrid RRF
                                     Azure OpenAI embeddings
                                     Qwen3-Reranker (Baseten or local vLLM)
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
| `VLLM_BASE_URL` | OpenAI-compatible vLLM endpoint serving Harness-1 |
| `ACCOUNT_URI` / `COSMOS_DATABASE` / `COSMOS_CORPUS_CONTAINER` | Cosmos target |
| `OPENAI_API_KEY` *(or `AZURE_OPENAI_*`)* | Embeddings backend |

### Inference backend

`INFERENCE_BACKEND` selects what drives the retrieval agent:

| Value | Model | Endpoint vars |
|---|---|---|
| `harmony_vllm` *(default)* | The fine-tuned `pat-jj/harness-1` checkpoint, driven with raw Harmony token-IDs. | `VLLM_BASE_URL`, `VLLM_MODEL_NAME` |
| `openai_chat` | **Any** OpenAI-compatible chat model (Azure AI Foundry deployment, OpenAI, local server, ...), driven with standard function/tool calling. | `CHAT_BASE_URL`, `CHAT_API_KEY`, `CHAT_MODEL`, optional `CHAT_API_VERSION` |

With `openai_chat` the agent uses the same Cosmos tools, so retrieval quality
depends on the chosen model's tool-use ability rather than the Harness-1
checkpoint. Example (Azure AI Foundry):

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
  agent.py           # 3 agent classes + prune_chunks_from_trajectory
  tools.py           # SearchCorpus / Grep / ReadDocument / PruneChunks
  trajectory.py      # Action / Observation / Trajectory + Harmony rendering
  rerank.py          # Reranker ABC + Baseten + local-vLLM
  inference/
    base.py          # AgentInferenceModel ABC
    vllm.py          # VLLMHarmonyInferenceModel (httpx → /v1/completions)
  prompts.py         # retrieval subagent system prompt
  config.py          # RetrieverSettings (pydantic-settings)
  utils.py
```

## License

Apache 2.0.
