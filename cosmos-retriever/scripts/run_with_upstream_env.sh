#!/bin/bash
# Bridge: source the upstream harness-1 .env.local and re-export the values our
# RetrieverSettings expects under its own variable names, then exec whatever
# command was passed on the command line.
#
# Maps:
#   AZURE_OPENAI_EMBED_API_KEY  -> AZURE_OPENAI_API_KEY   (the embed-only key)
#   AZURE_OPENAI_EMBED_DEPLOYMENT -> OPENAI_EMBEDDING_MODEL
#   ACCOUNT_URI / COSMOS_DATABASE / COSMOS_CORPUS_CONTAINER -> passed through
#   AZURE_OPENAI_ENDPOINT -> passed through
#
# Targets the live vLLM in the running pytorch container at 172.17.0.2:8000
# (harness-1 model) and the matching reranker on :8011.
#
# Usage:  scripts/run_with_upstream_env.sh python -m cosmos_retriever smoke --query "..."

set -euo pipefail

UPSTREAM_ENV="${UPSTREAM_ENV:-/nvme/harness-1/.env.local}"

if [[ ! -r "${UPSTREAM_ENV}" ]]; then
  echo "error: cannot read ${UPSTREAM_ENV}" >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a
source "${UPSTREAM_ENV}"
set +a

# --- Map upstream var names to ours -----------------------------------------
export OPENAI_EMBEDDING_MODEL="${AZURE_OPENAI_EMBED_DEPLOYMENT:-text-embedding-3-small}"
if [[ -n "${AZURE_OPENAI_EMBED_API_KEY:-}" ]]; then
  # Our config reads AZURE_OPENAI_API_KEY for the embedding endpoint.
  export AZURE_OPENAI_API_KEY="${AZURE_OPENAI_EMBED_API_KEY}"
fi

# --- Point at the running vLLM in the pytorch container --------------------
export VLLM_BASE_URL="${VLLM_BASE_URL:-http://172.17.0.2:8000}"
export VLLM_MODEL_NAME="${VLLM_MODEL_NAME:-harness-1}"
export VLLM_RERANKER_URL="${VLLM_RERANKER_URL:-http://172.17.0.2:8011}"

# --- Sensible default timeouts / budgets so we don't wait forever ----------
export VLLM_TIMEOUT_S="${VLLM_TIMEOUT_S:-600}"

exec "$@"
