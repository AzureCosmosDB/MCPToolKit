# Cosmos Retriever (Python helper)

This package runs a multi-turn search agent against an Azure Cosmos DB corpus and
returns the curated documents as JSON. The agent is model-agnostic: it drives any
OpenAI-compatible endpoint (the `/responses` or `/chat/completions` APIs) or an
Anthropic Messages endpoint. The same code is available three ways, an importable
Python package (`CosmosRetriever`), a FastAPI service
(`python -m cosmos_retriever serve`), and a one-shot CLI
(`python -m cosmos_retriever search`).

The [Azure Cosmos DB MCP Toolkit](../MCPToolKit/)'s `agentic_search` tool calls
this service's `POST /search` endpoint over HTTP.

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

Example request to test a running service (the query and its answer depend on the corpus you configured):

```bash
curl -s http://127.0.0.1:9000/search \
  -H 'content-type: application/json' \
  -d '{"query": "Who discovered radium?", "maxDocuments": 5}'
```

## CLI

To smoke-test locally, use the command below to query the service with a single
question and print the answer documents. JSON goes to **stdout**, logs go to
**stderr**.

```bash
python -m cosmos_retriever search \
  --query "Who discovered radium?" \
  --max-documents 5
```

Expected output (same schema returned by `POST /search`):
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

All settings come from environment variables, or from a `.env` / `.env.local`
file in the `cosmos-retriever/` directory. Precedence is real environment
variables first, then `.env.local`, then `.env`. Use `.env.local` for local
secrets and overrides, it is gitignored. Required settings:

| Variables | Purpose |
|---|---|
| `INFERENCE_BACKEND`, `CHAT_BASE_URL`, `CHAT_API_KEY`, `CHAT_MODEL` | The backend, endpoint, key, and model for the LLM that drives the agent (see Inference backend below) |
| `ACCOUNT_URI`, `COSMOS_DATABASE`, `COSMOS_CORPUS_CONTAINER` | The Cosmos account, database, and container to search |
| `OPENAI_API_KEY`, `OPENAI_EMBEDDING_MODEL` | The embeddings key and model (set `EMBED_ENDPOINT` for Azure or a local server) |

Each row is a group of related settings, not alternatives. See
[`.env.example`](.env.example) for the complete list and defaults.

### Inference backend

`INFERENCE_BACKEND` selects what drives the retrieval agent:

| Value | Model | Endpoint vars |
|---|---|---|
| `openai_responses` *(default)* | Any OpenAI-compatible `/responses` model (reasoning models such as gpt-5.x). | `CHAT_BASE_URL`, `CHAT_API_KEY`, `CHAT_MODEL`, optional `CHAT_API_VERSION` |
| `openai_chat` | Any OpenAI-compatible `/chat/completions` model (Azure AI Foundry deployment, OpenAI, local server, ...). | `CHAT_BASE_URL`, `CHAT_API_KEY`, `CHAT_MODEL`, optional `CHAT_API_VERSION` |
| `anthropic_messages` | Any Anthropic Messages API endpoint — e.g. Claude on Azure AI Foundry (served over the Messages API, not OpenAI-shaped). | `CHAT_BASE_URL`, `CHAT_API_KEY`, `CHAT_MODEL`, optional `ANTHROPIC_VERSION`, `ANTHROPIC_AUTH_HEADER` |

All backends drive the same Cosmos tools, so retrieval quality depends on the
chosen model's tool-use ability. Example (Azure AI Foundry):

```bash
INFERENCE_BACKEND=openai_chat \
CHAT_BASE_URL=https://your-resource.services.ai.azure.com/openai/v1 \
CHAT_API_KEY=... \
CHAT_MODEL=gpt-4o \
python -m cosmos_retriever serve
```

### Optional reranker

An independent reranker model can be configured to reorder the retrieved
documents by relevance before they are returned, which improves the quality of
the final ranking. It is optional. Without it, the agent keeps the raw retrieval
order. Configure at most one of:

- `VLLM_RERANKER_URL`, a local vLLM `/score` endpoint serving Qwen3-Reranker-8B.
- `BASETEN_API_KEY` and `BASETEN_MODEL_URL`, a Baseten Qwen3-Reranker-8B deployment.

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

MIT — this package is covered by the repository's top-level [LICENSE](../LICENSE).
