# foundry-harness

**Experimental.** Drive the *full* nine-tool Cosmos retrieval harness with a
generic Azure AI Foundry `/responses` model (e.g. `gpt-5.x`) instead of the
fine-tuned Harness-1 model.

This folder is **separate from the committed PR** and does not modify any
`cosmos_retriever` code. It reuses the harness at runtime.

## What it does

The production `openai_responses` / `openai_chat` backends in
`cosmos_retriever.inference.openai_chat` only expose the **four directly
executable** tools (`search_corpus`, `grep_corpus`, `read_document`,
`prune_chunks`) to a stock model, and reconstruct the final set by parsing
`<Document id=...>` blocks out of the model's text.

`foundry_harness` instead gives the Foundry model the **complete agentic
vocabulary** the fine-tuned model uses:

| Tool | Behavior |
|------|----------|
| `fan_out_search` | Run several diverse queries in parallel |
| `search_corpus` | Single semantic + keyword search |
| `grep_corpus` | Exact regex match over the corpus |
| `read_document` | Read a document's full text |
| `review_docs` | Re-read pooled docs from memory (free) |
| `curate` | Update the two-tier curated set — **this is the output** |
| `verify` | LLM claim-check over specific docs (only if `V8D_VERIFY_TOOL=1`) |
| `prune_chunks` | No-op (memory is auto-managed) |
| `end_search` | Submit the curated set and stop |

Each tool call is executed by the real
`cosmos_retriever.env_rl.SlidingWindowSearchEnv` dispatch against a live
`WorkingMemory`, so tool semantics are identical to the trained harness. The
final result is `WorkingMemory.curated_ids` — the set the model built with
`curate`, not a parsed text block.

## How it works

`SlidingWindowSearchEnv` is instantiated purely as a stateful **dispatcher**.
The driver:

1. Builds the nine OpenAI function schemas from `env._build_full_toolset()`.
2. Uses `cosmos_retriever.ultra_core.get_system_prompt(query)` (the same prompt
   the trained model sees).
3. Loops over the `/responses` API: model → function calls → `env._exec_*` →
   `function_call_output` continuation, until `end_search` or `max_turns`.
4. Returns a `cosmos_retriever.retriever.RetrievalResult` (drop-in with the
   harmony backend), including per-query `usage` and `trajectory`.

## Caveats

- **Not trained on this vocabulary.** A stock model was not fine-tuned on the
  `curate`/`fan_out_search`/`review_docs` rhythm; recall/quality may differ from
  Harness-1 and depends on the model's tool-following ability.
- **Cost.** `verify` (if enabled) and long tool loops add `/responses` calls.
- **Output contract differs** from the 4-tool backend: the answer is the
  curated set, not `<Document>` blocks.

## Running

Requires the `cosmos-retriever` venv (so `cosmos_retriever` imports) and the
corpus/model env vars.

```bash
cd /nvme/UpdatedMCPToolKit/cosmos-retriever
set -a; source /nvme/harness-1/.env.local; set +a
export INFERENCE_BACKEND=openai_responses \
       CHAT_BASE_URL="$ANSWER_OPENAI_ENDPOINT" \
       CHAT_MODEL="$ANSWER_MODEL" \
       CHAT_API_KEY="$ANSWER_OPENAI_API_KEY" \
       CHAT_REASONING_EFFORT=medium \
       VLLM_RERANKER_URL=http://172.17.0.2:8011 \
       CORPUS_REGISTRY_FILE="$PWD/corpus_registry.json"
unset CHAT_API_VERSION

PYTHONPATH=/nvme/UpdatedMCPToolKit/foundry-harness \
  .venv/bin/python -m foundry_harness.run "your question here" --max-turns 35 --json
```

### Programmatic use

```python
from foundry_harness import FoundryHarnessAgent

agent = FoundryHarnessAgent(reasoning_effort="medium", max_turns=35)
result = agent.search("who signed the 1994 supply agreement?")
print([d.id for d in result.documents], result.usage, result.trajectory)
```
