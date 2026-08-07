"""Shared pytest fixtures.

``config.py`` calls ``load_dotenv(.env.local)`` at import, which injects the
live service configuration into ``os.environ``. Unit tests construct
``RetrieverSettings`` expecting a clean environment (env vars outrank
``_env_file=None``), so this autouse fixture strips those keys for everything
except the live tests under ``tests/end_to_end/``, which intentionally use the
real ``.env.local``.
"""
from __future__ import annotations

import pytest

# Env vars that .env.local / a real deployment may set and that map onto
# RetrieverSettings fields — cleared so offline unit tests see defaults.
_CONFIG_ENV_VARS = [
    "INFERENCE_BACKEND",
    "CHAT_BASE_URL",
    "CHAT_API_KEY",
    "CHAT_MODEL",
    "CHAT_API_VERSION",
    "CHAT_TEMPERATURE",
    "CHAT_MAX_TOKENS",
    "CHAT_MAX_TURNS",
    "CHAT_REASONING_EFFORT",
    "ANTHROPIC_VERSION",
    "ANTHROPIC_AUTH_HEADER",
    "ACCOUNT_URI",
    "COSMOS_DATABASE",
    "COSMOS_CORPUS_CONTAINER",
    "COSMOS_KEY",
    "OPENAI_API_KEY",
    "OPENAI_EMBEDDING_MODEL",
    "OPENAI_EMBEDDING_DIMENSIONS",
    "EMBED_ENDPOINT",
    "EMBED_QUERY_INSTRUCTION",
    "CORPUS_REGISTRY",
    "CORPUS_REGISTRY_FILE",
    "BASETEN_API_KEY",
    "BASETEN_MODEL_URL",
    "VLLM_RERANKER_URL",
    "LOG_LEVEL",
    "HOST",
    "PORT",
]


@pytest.fixture(autouse=True)
def _isolate_config_env(request, monkeypatch):
    # Live end-to-end tests rely on the real .env.local; leave their env intact.
    if "end_to_end" in str(request.fspath):
        return
    for var in _CONFIG_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    # Also stop pydantic-settings from auto-loading the repo-root .env.local file
    # (it is read via model_config regardless of os.environ).
    from cosmos_retriever.config import RetrieverSettings

    monkeypatch.setitem(RetrieverSettings.model_config, "env_file", None)
