# `agentic_search` — multi-turn retrieval as an MCP tool

`agentic_search` runs a multi-turn search agent — built from scratch for this
toolkit — against an Azure Cosmos DB corpus and returns the ranked, curated set of documents
that best answer a natural-language query. The agent issues hybrid (vector +
full-text) RRF searches, optionally reranks with Qwen3-Reranker-8B, fetches
full documents, and prunes its working context across multiple turns. From
the MCP client's perspective it's a single tool call; under the hood the
agent can take 20–40 turns and 30–60 s of wall-clock time.

## Architecture

```text
  MCP client                            MCPToolKit (.NET)                 cosmos-retriever (Python, FastAPI)
  ──────────                            ─────────────────                 ───────────────────────────────────
  Claude Desktop                                                              ┌─ TokenBudgetRetrievalSubagent
  AI Foundry         ─── MCP HTTP ───► [McpServerTool] AgenticSearch          │  ├─ SearchCorpus / Grep / Read / Prune
  VS Code Copilot                          │                                  │  └─ OpenAI-compatible inference
                                           ▼                                  │
                                      AgenticSearchExecutor ── HTTP POST ───► POST /search  (uvicorn, kept warm)
                                           │                                  │
                                           │ ◄────── JSON body ──────────────┤
                                           │                                  └─► LLM endpoint + Cosmos DB + embeddings
                                           ▼
                                      MCP tool response
```

The .NET server and the Python retriever are now **two long-lived
processes**. The retriever is started once (`python -m cosmos_retriever
serve`) and keeps its Cosmos/embedding/LLM clients warm; the .NET server
calls its `POST /search` endpoint per MCP tool call and passes the JSON
response through verbatim.

## Prerequisites

You need three things running on the same host (or reachable from it):

| Component | What it is |
|---|---|
| **An LLM endpoint** | Any OpenAI-compatible model — an Azure AI Foundry deployment, OpenAI, or a local server — via `INFERENCE_BACKEND=openai_responses` (default) or `openai_chat` (see below). |
| **Azure Cosmos DB for NoSQL** | Container populated with the standard chunked-corpus schema (`id`, `docid`, `chunk_idx`, `text`, `embedding`), vector + FTS indexes enabled. |
| **Embeddings backend** | Whatever model your corpus was ingested with — Azure OpenAI `text-embedding-3-small`, OpenAI native, or a local vLLM embedding server. |

### Inference backend

The retriever supports two backends, selected by `INFERENCE_BACKEND`:

- `openai_responses` *(default)* — any OpenAI-compatible `/responses` model
  (e.g. a reasoning model such as gpt-5.x), driven with standard tool calling.
- `openai_chat` — any OpenAI-compatible `/chat/completions` model (an Azure AI
  Foundry deployment, OpenAI, a local server, ...). Set `CHAT_BASE_URL`,
  `CHAT_API_KEY`, `CHAT_MODEL` (and `CHAT_API_VERSION` for Azure OpenAI-style
  endpoints). The agent uses the same Cosmos tools, so retrieval quality tracks
  the chosen model's tool-use ability.

The Python helper is **bundled in this repository** at
[`cosmos-retriever/`](../cosmos-retriever/) — no separate clone needed.
Install it into a virtualenv:

```bash
cd cosmos-retriever
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e .
```

Confirm it works:

```bash
.venv/bin/python -m cosmos_retriever serve --help
```

Then start the service (it reads its own `.env` / `.env.local` for
`CHAT_BASE_URL`, `ACCOUNT_URI`, `COSMOS_*`, `AZURE_OPENAI_*`, `HOST`, `PORT`):

```bash
.venv/bin/python -m cosmos_retriever serve          # binds HOST:PORT (default 0.0.0.0:9000)
curl -s http://127.0.0.1:9000/health                  # -> {"status":"ok"}
```

## Server configuration

Two env vars are read by the `AgenticSearchExecutor` service; both optional.
If `COSMOS_RETRIEVER_URL` doesn't point at a running retriever service, the
tool returns a clean JSON `{"error":"...","hint":"..."}` envelope rather than
crashing the server.

| Variable | Default | Purpose |
|---|---|---|
| `COSMOS_RETRIEVER_URL` | `http://127.0.0.1:9000` | Base URL of the cosmos-retriever FastAPI service. |
| `COSMOS_RETRIEVER_TIMEOUT_S` | `600` | Per-request wall-clock cap; the request is abandoned if it exceeds this. |

Unlike the previous subprocess design, the retriever service has its **own**
environment. Everything it needs (`CHAT_BASE_URL`, `ACCOUNT_URI`,
`COSMOS_DATABASE`, `COSMOS_CORPUS_CONTAINER`, `AZURE_OPENAI_*`,
`CORPUS_REGISTRY_FILE`, …) is read from the retriever process's environment /
`.env` file, **not** inherited from the .NET server.

## Tool schema

```jsonc
{
  "name": "agentic_search",
  "description": "Runs a multi-turn retrieval agent against a Cosmos DB corpus and returns ranked, curated documents.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query":         { "type": "string",  "maxLength": 4096 },
      "maxDocuments":  { "type": "integer", "minimum": 1, "maximum": 30, "default": 20 },
      "database":      { "type": "string",  "maxLength": 256 },
      "container":     { "type": "string",  "maxLength": 256 }
    },
    "required": ["query"],
    "additionalProperties": false
  }
}
```

Tool result (the retriever service's `POST /search` JSON body, passed through verbatim):

```jsonc
{
  "query": "Who discovered radium and when did she win her second Nobel?",
  "num_turns": 5,
  "elapsed_s": 32.3,
  "documents": [
    {
      "id": "96308__3",
      "rank": 0,
      "justification": "This biography directly states that Marie Curie ...",
      "text": "..."
    }
  ]
}
```

On failure the helper (or the C# executor) returns a JSON error envelope:

```jsonc
{ "error": "agentic_search timed out after 600s.", "stderr": "..." }
```

## Multi-corpus targeting

`agentic_search` accepts optional `database` and `container` arguments so a
single MCP server can be aimed at multiple Cosmos corpora at request time.
For per-corpus *embedding-model* selection (e.g. one corpus ingested with
`text-embedding-3-small`, another with `qwen3-embed`), point
`CORPUS_REGISTRY_FILE` at a JSON file in the cosmos-retriever package:

```jsonc
{
  "browsecomp_corpus_container": {
    "account_uri":  "https://acct-a.documents.azure.com:443/",
    "database":     "search_retrieval_database",
    "embed_base_url": "https://embedding.services.ai.azure.com/openai/v1",
    "embed_api_key_env": "AZURE_OPENAI_API_KEY",
    "embed_model":  "text-embedding-3-small"
  },
  "enterprise_ragbench_corpus": {
    "account_uri":  "https://acct-b.documents.azure.com:443/",
    "database":     "search_retrieval_database",
    "embed_base_url": "http://localhost:8002/v1",
    "embed_api_key_env": null,
    "embed_model":  "qwen3-embed",
    "embed_query_instruction": "Given a question, retrieve documents that answer it"
  }
}
```

Then call:

```jsonc
{ "name": "agentic_search",
  "arguments": {
    "query": "What was the temporary mitigation applied to the internal load balancer ...",
    "container": "enterprise_ragbench_corpus"
  } }
```

The matching account, database, embedding URL, model, and optional
`Instruct:` prefix all get picked automatically per call. Adding a third
corpus is a one-line registry edit — no rebuild, no restart.

## Local demo

End-to-end against any OpenAI-compatible endpoint plus Cosmos DB and embeddings.

**1. Start the retriever service** (the bundled `cosmos-retriever/` folder; it
reads its own `.env`):

```bash
cd cosmos-retriever
INFERENCE_BACKEND=openai_responses \
CHAT_BASE_URL=https://your-resource.services.ai.azure.com/openai/v1 \
CHAT_API_KEY=... \
CHAT_MODEL=gpt-5.2 \
VLLM_RERANKER_URL=http://localhost:8011 \
CORPUS_REGISTRY_FILE=$PWD/corpus_registry.json \
PORT=9000 \
.venv/bin/python -m cosmos_retriever serve
```

**2. Start the .NET MCP server** (from the repo root), pointing it at the retriever URL:

```bash
DEV_BYPASS_AUTH=true \
COSMOS_RETRIEVER_URL=http://127.0.0.1:9000 \
OPENAI_ENDPOINT="$AZURE_OPENAI_ENDPOINT" \
OPENAI_EMBEDDING_DEPLOYMENT="$AZURE_OPENAI_EMBED_DEPLOYMENT" \
dotnet run --project src/AzureCosmosDB.MCP.Toolkit
```

Then point any MCP client at `http://127.0.0.1:8080/mcp/`.

## Operational notes

- **The retriever service has its own environment.** Configure
  `CHAT_BASE_URL`, `ACCOUNT_URI`, `COSMOS_*`, `AZURE_OPENAI_*`,
  `CORPUS_REGISTRY_FILE`, etc. where you launch `cosmos_retriever serve`
  (env or its `.env` file) — the .NET server no longer forwards them.
- **`COSMOS_USE_DEFAULT_CREDENTIAL`** controls the retriever's Cosmos auth.
  By default it uses `AzureCliCredential`; set it to `1` to opt into the
  broader `DefaultAzureCredential` chain (managed identity, etc.).
- **Warm process, no cold start.** Because the service stays up, the heavy
  client init happens once. Per-call latency is dominated by Cosmos
  round-trips + LLM generation; don't expect sub-second latency.
- **Retrieval quality is corpus-dependent.** Cosmos's hybrid RRF puts gold
  docs in the top 5 reliably; the Qwen3-Reranker step on top can over- or
  under-shoot depending on how close the corpus distribution is to the
  reranker's training data. If you see recall regressions, try disabling the
  reranker for that corpus (omit `VLLM_RERANKER_URL` / `BASETEN_API_KEY`).
- **The tool always returns parseable JSON.** Unreachable service, request
  timeouts, and non-2xx responses all yield
  `{"error": "...", "hint"?: "...", "body"?: "..."}` envelopes rather than
  HTTP 500s to the MCP client.

## Implementation pointers

| File | Role |
|---|---|
| [`Services/AgenticSearchExecutor.cs`](../src/AzureCosmosDB.MCP.Toolkit/Services/AgenticSearchExecutor.cs) | HTTP call to the retriever service, timeout, error-envelope generation. |
| [`Services/CosmosDbToolsService.cs`](../src/AzureCosmosDB.MCP.Toolkit/Services/CosmosDbToolsService.cs) | `AgenticSearch` instance method called by both controllers. |
| [`Program.cs`](../src/AzureCosmosDB.MCP.Toolkit/Program.cs) | `[McpServerTool] AgenticSearch` static method discovered by the MCP SDK. |
| [`Controllers/MCPProtocolController.cs`](../src/AzureCosmosDB.MCP.Toolkit/Controllers/MCPProtocolController.cs) | JSON-RPC `tools/list` + `tools/call` dispatch for the custom `/mcp/http` transport. |
| [`Controllers/MCPTestController.cs`](../src/AzureCosmosDB.MCP.Toolkit/Controllers/MCPTestController.cs) | REST sibling at `POST /api/mcp/tools/agentic_search`. |
| [`Services/McpToolRequestValidator.cs`](../src/AzureCosmosDB.MCP.Toolkit/Services/McpToolRequestValidator.cs) | Strict input validation schema. |
| [`cosmos-retriever/`](../cosmos-retriever/) | The bundled Python FastAPI service (`POST /search`) the executor calls; run with `python -m cosmos_retriever serve`. |
