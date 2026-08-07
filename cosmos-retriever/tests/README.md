# Tests

This suite has two kinds of tests.

## Fake tests vs real tests

**Fake tests (`tests/unit/`)** — the default suite. Every external dependency
(Cosmos DB, OpenAI/Azure embeddings, the chat model, the reranker, the network)
is replaced with an in-process fake or monkeypatch. They are fast, deterministic,
need no credentials, and run everywhere. This is the bulk of the coverage: config,
tools, retriever, planner, strategies, document resolvers, normalization,
embeddings, paths, expressions, security, server, rerank, token counting, and the
token-budget agent loops.

**Real tests (`tests/end_to_end/`)** — opt-in integration tests that talk to
actual services and real model tokenizers. They are skipped by default so a plain
`pytest` run stays green offline. Each file documents its own `How to run` steps
in its module docstring. They fall into three groups:

| File | Hits | Opt-in trigger |
|---|---|---|
| `test_skf_live.py` | Live Cosmos + embeddings + reranker + gpt-5.4 agent | `RUN_SKF_LIVE=1` |
| `test_skf_discovery_live.py` | Live Cosmos container metadata + embeddings | `RUN_SKF_LIVE=1` |
| `test_skf_cross_collection_live.py` | Live cross-collection RRF over Cosmos + embeddings | `RUN_SKF_LIVE=1` |
| `test_rerank_live.py` | A running Qwen3-Reranker `/score` server | server reachable |
| `test_tokenizer_comparison.py` | Real model tokenizers (tiktoken + HF ports) | libraries + tokenizers available |

> Env isolation: `tests/conftest.py` strips the ambient service configuration
> (from `.env.local`) for the fake tests so they always see clean defaults, and
> deliberately leaves it in place for `tests/end_to_end/`.

## How to run the fake tests

From the `cosmos-retriever/` directory:

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e ".[dev]"
source .venv/bin/activate

pytest            # runs all fake tests; real tests skip
```

You should see the unit tests pass and the `end_to_end` tests reported as
`skipped`.

## How to set up the real tests

### Reranker (`test_rerank_live.py`)

1. Serve `Qwen/Qwen3-Reranker-8B` with a vLLM-compatible `/score` endpoint on
   `http://127.0.0.1:8011`, for example:
   ```bash
   vllm serve Qwen/Qwen3-Reranker-8B --port 8011 \
     --hf-overrides '{"architectures":["Qwen3ForSequenceClassification"],"classifier_from_token":["no","yes"],"is_original_qwen3_reranker":true}'
   ```
   (Needs vLLM >= 0.10 for the score conversion.)
2. If it runs elsewhere, set `VLLM_RERANKER_URL` to its base URL.
3. `pytest tests/end_to_end/test_rerank_live.py`

### Tokenizer comparison (`test_tokenizer_comparison.py`)

1. `uv pip install --python .venv/bin/python tiktoken tokenizers huggingface_hub`
2. Allow network access on first run so the model tokenizers download from
   Hugging Face (or prime the HF cache first). Anything unavailable is skipped.
3. `pytest tests/end_to_end/test_tokenizer_comparison.py`
4. Regenerate the pinned numbers any time with
   `python tests/end_to_end/tokenizer_panel.py`.

### SKF live suites (`test_skf_*_live.py`)

These run against the `skf-rag-test` Cosmos DB account.

1. `az login`, and select the subscription that owns the `skf-rag-test` account.
2. Grant your identity the **Cosmos DB Built-in Data Reader** role on the account:
   ```bash
   az cosmosdb sql role assignment create \
     --account-name skf-rag-test --resource-group DiskANN_development \
     --role-definition-id 00000000-0000-0000-0000-000000000001 \
     --principal-id <your-aad-object-id> --scope "/"
   ```
3. Create `cosmos-retriever/.env.local` (copy from `.env.example`) and fill:
   - `ACCOUNT_URI=https://skf-rag-test.documents.azure.com:443/`
   - `COSMOS_DATABASE=skf-database`, `COSMOS_CORPUS_CONTAINER=skf-unstructured`
   - Embeddings: `EMBED_ENDPOINT` (`.../openai/v1`), `OPENAI_API_KEY`,
     `OPENAI_EMBEDDING_MODEL=text-embedding-3-small`, `OPENAI_EMBEDDING_DIMENSIONS=1536`
     (the embedding model must match the container's vectors: 1536 for
     `skf-unstructured`/`skf-structured`, 3072/`text-embedding-3-large` for
     `skf-unstructured-text-large`).
   - Chat (agent, `test_skf_live.py` only): `INFERENCE_BACKEND`, `CHAT_BASE_URL`
     (`.../openai/v1`), `CHAT_API_KEY`, `CHAT_MODEL`.
   - Reranker (agent assertions in `test_skf_live.py`): `VLLM_RERANKER_URL`, with
     the reranker server from above running.
4. `export RUN_SKF_LIVE=1`
5. Run a suite:
   ```bash
   RUN_SKF_LIVE=1 pytest tests/end_to_end/test_skf_discovery_live.py       # metadata + embeddings only
   RUN_SKF_LIVE=1 pytest tests/end_to_end/test_skf_cross_collection_live.py # + cross-collection RRF
   RUN_SKF_LIVE=1 pytest tests/end_to_end/test_skf_live.py                  # + full agent (chat + reranker)
   ```

`test_skf_discovery_live.py` and `test_skf_cross_collection_live.py` need only
Cosmos read access and embeddings. `test_skf_live.py` additionally needs the chat
model and the reranker. `.env.local` holds secrets, keep it gitignored.
