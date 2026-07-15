# Cosmos Retriever — Quickstart

Spin up the `agentic_search` retriever service and test it locally on Windows (PowerShell).

## 1. Prerequisites

- Python 3.11 (fetched automatically by `uv`)
- `uv`, Azure CLI (`az`)
- An Azure Cosmos DB corpus container (fields: `id`, `docid`, `chunk_idx`, `text`, `embedding`; vector + FTS indexes enabled)
- An OpenAI-compatible LLM endpoint (e.g. Azure AI Foundry)
- An Azure OpenAI embeddings deployment (`text-embedding-3-small`)

## 2. Install (one time)

```powershell
cd cosmos-retriever
uv venv --python 3.11 .venv
uv pip install --python .venv\Scripts\python.exe -e ".[dev]"
```

## 3. Configure

Edit [`.env`](.env) and replace every `<PLACEHOLDER>`:

| Variable | What to put |
|---|---|
| `CHAT_BASE_URL` | LLM endpoint, e.g. `https://<resource>.services.ai.azure.com/openai/v1` |
| `CHAT_API_KEY` | LLM API key |
| `CHAT_MODEL` | Deployment/model name, e.g. `gpt-5.2` |
| `ACCOUNT_URI` | `https://<account>.documents.azure.com:443/` |
| `COSMOS_DATABASE` | Database name |
| `COSMOS_CORPUS_CONTAINER` | Corpus container name |
| `EMBED_ENDPOINT` | Azure OpenAI v1 base URL |
| `OPENAI_API_KEY` | Azure OpenAI embeddings key |

Defaults already set: `INFERENCE_BACKEND=openai_responses`, embeddings `text-embedding-3-small`, no reranker, Azure CLI credential for Cosmos, port `9000`.

## 4. Authenticate to Cosmos

```powershell
az login
```

## 5. Run the service

```powershell
.\run-retriever.ps1
```

It binds `0.0.0.0:9000` and keeps its Cosmos/LLM/embedding clients warm.

## 6. Test

**Health check** (new terminal):

```powershell
Invoke-RestMethod http://127.0.0.1:9000/health
# -> status : ok
```

**One-shot search via HTTP:**

```powershell
$body = '{"query":"Who discovered radium?","maxDocuments":5}'
Invoke-RestMethod -Uri http://127.0.0.1:9000/search -Method Post -ContentType application/json -Body $body
```

**Or via the CLI** (JSON to stdout, logs to stderr):

```powershell
.venv\Scripts\python.exe -m cosmos_retriever search --query "Who discovered radium?" --max-documents 5
```

**Target a specific corpus** from `corpus_registry.json`:

```powershell
$body = '{"query":"...","container":"enterprise_ragbench_corpus"}'
Invoke-RestMethod -Uri http://127.0.0.1:9000/search -Method Post -ContentType application/json -Body $body
```

Expected response shape:

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

## Troubleshooting

- **`status` not returned / connection refused** — the service isn't running; check the `run-retriever.ps1` terminal for errors.
- **Cosmos auth errors** — run `az login`; or set `COSMOS_KEY` in `.env`; or `COSMOS_USE_DEFAULT_CREDENTIAL=1` for managed identity.
- **Placeholder still in `.env`** — every `<...>` value must be replaced.
- **Wire into the MCP server** — set `COSMOS_RETRIEVER_URL=http://127.0.0.1:9000` in the repo-root `.env` and start the .NET server with `..\run-mcp-server.ps1`.
