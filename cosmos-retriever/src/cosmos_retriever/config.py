"""Runtime configuration for the Cosmos retriever.

All values are loaded from environment variables (or a ``.env`` file at the
repo root). Sensitive fields use :class:`pydantic.SecretStr` so they're not
accidentally rendered into logs.

**Multi-corpus support.** When you have more than one ingested corpus that was
built with *different* embedding models, register them via ``CORPUS_REGISTRY``
(JSON string) or ``CORPUS_REGISTRY_FILE`` (path to a JSON file). Each entry
overrides the Cosmos account / database and embedding-client config for that
container name. Caller passes ``container="<name>"`` at search time and the
right embedder is picked automatically.

Example registry JSON::

    {
      "browsecomp_corpus_container": {
        "account_uri": "https://accountA.documents.azure.com:443/",
        "database":    "search_retrieval_database",
        "embed_base_url": "https://embedding-west-us-resource.services.ai.azure.com/openai/v1",
        "embed_api_key_env": "AZURE_OPENAI_API_KEY",
        "embed_model":  "text-embedding-3-small"
      },
      "enterprise_ragbench_corpus": {
        "account_uri":  "https://accountB.documents.azure.com:443/",
        "database":     "search_retrieval_database",
        "embed_base_url": "http://172.17.0.2:8002/v1",
        "embed_api_key_env": null,
        "embed_model":  "qwen3-embed",
        "embed_query_instruction": "Given a question, retrieve documents that answer it"
      }
    }
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
from azure.cosmos import CosmosClient, DatabaseProxy
from azure.identity import AzureCliCredential, DefaultAzureCredential
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from baseten_performance_client import PerformanceClient

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILES = (str(REPO_ROOT / ".env.local"), str(REPO_ROOT / ".env"))

# Also export to os.environ so the registry's *_env indirection
# (e.g. embed_api_key_env="AZURE_OPENAI_EMBED_API_KEY") can find values
# that live only in the .env file.
for _env_path in DEFAULT_ENV_FILES:
    load_dotenv(_env_path, override=False)


def init_logging(
    app_level: int = logging.INFO,
    *,
    lib_level: int = logging.WARNING,
    colors: bool = True,
) -> None:
    """Configure structlog without lowering library log thresholds.

    Logs are written to **stderr** so that subprocess invocations (e.g. the
    MCP Toolkit's ``agentic_search`` tool) can keep stdout reserved for the
    JSON result.
    """

    logging.basicConfig(level=lib_level, format="%(message)s", stream=sys.stderr, force=True)
    structlog.configure_once(
        processors=[
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(colors=colors),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(app_level),
        cache_logger_on_first_use=True,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )


@dataclass(frozen=True)
class CorpusConfig:
    """Per-corpus resolved configuration.

    All fields are *resolved* — no env-var references, no ``${...}`` placeholders.
    :py:meth:`RetrieverSettings.resolve_corpus` does the lookup and fallback.
    """

    container: str
    account_uri: str
    database: str
    embed_base_url: str | None

    embed_api_key: SecretStr | None
    embed_model: str
    embed_query_instruction: str | None = None

    cosmos_key: SecretStr | None = None


class RetrieverSettings(BaseSettings):
    """Runtime configuration loaded from environment variables or .env files."""

    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Inference backend selection --------------------------------------
    # The agent is driven by any OpenAI-compatible model via standard
    # function/tool calling over the four real Cosmos tools
    # (search_corpus, grep_corpus, read_document, prune_chunks):
    # "openai_responses" (default): the /responses API, required by reasoning
    #   models such as gpt-5.x that are only exposed there.
    # "openai_chat": the /chat/completions API for standard chat models.
    # Configure the endpoint with the CHAT_* vars below.
    inference_backend: str = Field(
        default="openai_responses",
        description='Inference backend: "openai_responses" or "openai_chat".',
    )

    @field_validator("inference_backend")
    @classmethod
    def _validate_inference_backend(cls, v: str) -> str:
        normalized = (v or "").strip().lower()
        allowed = {"openai_chat", "openai_responses"}
        if normalized not in allowed:
            raise ValueError(
                f"INFERENCE_BACKEND must be one of {sorted(allowed)}, got {v!r}."
            )
        return normalized

    # --- Generic chat LLM endpoint -----------------------------------------
    # Any OpenAI-compatible chat-completions endpoint. For Azure AI Foundry,
    # CHAT_BASE_URL is the deployment's OpenAI-compatible URL (or set
    # CHAT_API_VERSION to use the Azure OpenAI client) and CHAT_MODEL is the
    # deployment name.
    chat_base_url: str | None = Field(
        default=None,
        description="Base URL of an OpenAI-compatible chat-completions endpoint.",
    )
    chat_api_key: SecretStr | None = None
    chat_model: str | None = Field(
        default=None, description="Chat model / Foundry deployment name."
    )
    chat_api_version: str | None = Field(
        default=None,
        description="Set for Azure OpenAI-style endpoints (uses the AzureOpenAI client).",
    )
    chat_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    chat_max_tokens: int = Field(default=4096, ge=256)
    chat_max_turns: int = Field(default=20, ge=1, le=200)
    chat_reasoning_effort: str | None = Field(
        default=None,
        description='Reasoning effort for reasoning models on the responses API (e.g. "low", "medium", "high").',
    )

    # --- Cosmos DB (default / fallback corpus) -----------------------------
    account_uri: str = Field(description="Cosmos DB account URI (default corpus).")
    cosmos_database: str
    cosmos_corpus_container: str
    cosmos_key: SecretStr | None = None

    # --- Embeddings (default corpus) --------------------------------------
    openai_api_key: SecretStr | None = None
    openai_embedding_model: str | None = None
    embed_endpoint: str | None = Field(
        default=None,
        description=(
            "Embedding endpoint base URL. Leave unset to use plain OpenAI "
            "(api.openai.com). For Azure pass https://<resource>.../openai/v1; "
            "for a local server pass http://host:port/v1."
        ),
    )
    embed_query_instruction: str | None = None

    # --- Multi-corpus registry --------------------------------------------
    corpus_registry: str | None = Field(
        default=None,
        description="JSON string mapping container name -> CorpusConfig overrides.",
    )
    corpus_registry_file: str | None = Field(
        default=None,
        description="Path to a JSON file holding the corpus registry.",
    )

    # --- Reranker (optional) ----------------------------------------------
    baseten_api_key: SecretStr | None = None
    baseten_model_url: str | None = None
    vllm_reranker_url: str | None = None  # local vLLM /score endpoint

    # --- Retriever knobs --------------------------------------------------
    cosmos_retriever_max_turns: int = Field(default=35, ge=1, le=200, alias="COSMOS_RETRIEVER_MAX_TURNS")
    cosmos_retriever_threshold_budget: int = Field(
        default=16384, ge=1024, alias="COSMOS_RETRIEVER_THRESHOLD_BUDGET"
    )
    cosmos_retriever_token_budget: int = Field(
        default=32268, ge=4096, alias="COSMOS_RETRIEVER_TOKEN_BUDGET"
    )
    cosmos_retriever_search_display_limit: int = Field(default=15, ge=1, le=50)

    # --- HTTP server ------------------------------------------------------
    host: str = Field(default="0.0.0.0")  # noqa: S104  binding to all is intended for containers
    port: int = Field(default=9000, ge=1, le=65535)
    log_level: str = Field(default="info")

    # ------------------------------------------------------------------
    # Registry parsing + corpus resolution
    # ------------------------------------------------------------------
    def _load_registry(self) -> dict[str, dict[str, Any]]:
        """Return the parsed registry (empty dict if none configured)."""

        if self.corpus_registry_file:
            path = Path(self.corpus_registry_file)
            if not path.is_file():
                raise FileNotFoundError(f"CORPUS_REGISTRY_FILE points at missing file: {path}")
            raw = path.read_text(encoding="utf-8")
        elif self.corpus_registry:
            raw = self.corpus_registry
        else:
            return {}

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"corpus_registry is not valid JSON: {exc}") from exc

        if not isinstance(data, dict):
            raise ValueError("corpus_registry must be a JSON object {container_name: {...}}")
        return data

    def resolve_corpus(self, container: str | None = None) -> CorpusConfig:
        """Return the fully-resolved :class:`CorpusConfig` for ``container``.

        Resolution order:

        1. If ``container`` is set and present in the registry, use that entry.
        2. If ``container`` is set but **not** in the registry, fall back to
           the default-corpus env vars, swapping in just the container name.
        3. If ``container`` is ``None``, use the default-corpus env vars verbatim.
        """

        registry = self._load_registry()
        target = container or self.cosmos_corpus_container
        entry = registry.get(target)

        def _resolve_default_embed() -> tuple[str | None, SecretStr | None, str | None]:
            # ``embed_endpoint`` unset (None) => plain OpenAI against api.openai.com.
            return self.embed_endpoint, self.openai_api_key, self.openai_embedding_model

        if entry is None:
            base, key, model = _resolve_default_embed()
            return CorpusConfig(
                container=target,
                account_uri=self.account_uri,
                database=self.cosmos_database,
                embed_base_url=base,
                embed_api_key=key,
                embed_model=model,
                embed_query_instruction=self.embed_query_instruction,
                cosmos_key=self.cosmos_key,
            )

        # Registry entry — resolve every field, with sensible fallbacks.
        api_key_env = entry.get("embed_api_key_env")
        api_key_value: SecretStr | None = None
        if api_key_env:
            raw_key = os.environ.get(api_key_env)
            if raw_key:
                api_key_value = SecretStr(raw_key)

        cosmos_key_env = entry.get("cosmos_key_env")
        cosmos_key_value: SecretStr | None = self.cosmos_key
        if cosmos_key_env:
            raw_ck = os.environ.get(cosmos_key_env)
            if raw_ck:
                cosmos_key_value = SecretStr(raw_ck)

        return CorpusConfig(
            container=target,
            account_uri=entry.get("account_uri") or self.account_uri,
            database=entry.get("database") or self.cosmos_database,
            embed_base_url=entry.get("embed_base_url"),
            embed_api_key=api_key_value,
            embed_model=entry.get("embed_model") or self.openai_embedding_model,
            embed_query_instruction=entry.get("embed_query_instruction"),
            cosmos_key=cosmos_key_value,
        )

    # ------------------------------------------------------------------
    # Client factories
    # ------------------------------------------------------------------
    def _cosmos_credential(self):
        """Build the credential the Cosmos SDK should use.

        We default to :class:`AzureCliCredential` (i.e. whoever ran
        ``az login``) rather than :class:`DefaultAzureCredential` because on
        Azure VMs the broader chain picks up the host's managed identity
        first, which often lives in a *different* AAD tenant from the Cosmos
        account and produces a misleading 401. Users who explicitly want the
        broader chain can opt in by setting ``COSMOS_USE_DEFAULT_CREDENTIAL=1``.
        """

        if os.environ.get("COSMOS_USE_DEFAULT_CREDENTIAL", "").lower() in {"1", "true", "yes"}:
            return DefaultAzureCredential()
        return AzureCliCredential()

    def build_cosmos_database(self, corpus: CorpusConfig) -> DatabaseProxy:
        """Return a Cosmos database proxy for ``corpus`` (its account + database)."""

        if corpus.cosmos_key is not None:
            client = CosmosClient(corpus.account_uri, credential=corpus.cosmos_key.get_secret_value())
        else:
            client = CosmosClient(corpus.account_uri, credential=self._cosmos_credential())
        return client.get_database_client(corpus.database)

    def build_openai_client(self, corpus: CorpusConfig) -> OpenAI:
        """Return an embeddings client for ``corpus``.

        Works for plain OpenAI, Azure OpenAI (when ``embed_base_url`` ends in
        ``/openai/v1``), and any OpenAI-compatible local server (vLLM, TGI,
        Ollama).
        """

        kwargs: dict[str, Any] = {}
        if corpus.embed_base_url:
            kwargs["base_url"] = corpus.embed_base_url
        # The OpenAI SDK rejects api_key=None, so substitute a placeholder
        # when talking to a keyless local server.
        kwargs["api_key"] = (
            corpus.embed_api_key.get_secret_value() if corpus.embed_api_key is not None else "EMPTY"
        )
        return OpenAI(**kwargs)

    # ----- Generic chat backend ------------------------------------------
    @property
    def use_chat_backend(self) -> bool:
        """True when the agent should be driven by a generic chat-completions model."""

        return self.inference_backend.strip().lower() == "openai_chat"

    @property
    def use_responses_backend(self) -> bool:
        """True when the agent should be driven via the OpenAI /responses API."""

        return self.inference_backend.strip().lower() == "openai_responses"

    @property
    def use_generic_llm_backend(self) -> bool:
        """True for any OpenAI-compatible backend (chat-completions or responses)."""

        return self.use_chat_backend or self.use_responses_backend

    def build_chat_client(self) -> OpenAI:
        """Return an OpenAI-compatible chat client for the configured endpoint.

        Supports plain OpenAI / any OpenAI-compatible server via
        ``CHAT_BASE_URL``, and Azure OpenAI-style endpoints when
        ``CHAT_API_VERSION`` is set (uses :class:`openai.AzureOpenAI`).
        """

        if not self.chat_base_url:
            raise ValueError(
                "CHAT_BASE_URL must be set when INFERENCE_BACKEND=openai_chat."
            )
        if not self.chat_model:
            raise ValueError(
                "CHAT_MODEL (the deployment / model name) must be set when "
                "INFERENCE_BACKEND=openai_chat."
            )
        api_key = (
            self.chat_api_key.get_secret_value() if self.chat_api_key is not None else "EMPTY"
        )
        if self.chat_api_version:
            from openai import AzureOpenAI  # noqa: PLC0415 — optional Azure path

            return AzureOpenAI(
                azure_endpoint=self.chat_base_url,
                api_key=api_key,
                api_version=self.chat_api_version,
            )
        return OpenAI(base_url=self.chat_base_url, api_key=api_key)

    # ----- Legacy single-corpus accessors (kept for backwards compat) -----
    def get_cosmos_client(self) -> CosmosClient:
        corpus = self.resolve_corpus()
        if corpus.cosmos_key is not None:
            return CosmosClient(corpus.account_uri, credential=corpus.cosmos_key.get_secret_value())
        return CosmosClient(corpus.account_uri, credential=self._cosmos_credential())

    def get_cosmos_database(self) -> DatabaseProxy:
        return self.build_cosmos_database(self.resolve_corpus())

    def get_openai_client(self) -> OpenAI:
        return self.build_openai_client(self.resolve_corpus())

    def get_baseten_client(self) -> PerformanceClient:
        """Return a Baseten classify client (only valid when both env vars are set)."""

        if self.baseten_api_key is None or not self.baseten_model_url:
            raise ValueError(
                "BASETEN_API_KEY and BASETEN_MODEL_URL must both be set to use Baseten reranking."
            )
        # Imported lazily so the optional dependency isn't required at import time.
        from baseten_performance_client import PerformanceClient  # noqa: PLC0415

        return PerformanceClient(
            base_url=self.baseten_model_url,
            api_key=self.baseten_api_key.get_secret_value(),
        )


@lru_cache(maxsize=1)
def get_settings() -> RetrieverSettings:
    """Return a cached :class:`RetrieverSettings` instance and configure logging."""

    settings = RetrieverSettings()  # type: ignore[call-arg]
    init_logging(app_level=_log_level_to_int(settings.log_level))
    return settings


def get_config() -> "RetrieverSettings":
    return get_settings()


def _log_level_to_int(level: str) -> int:
    return getattr(logging, level.upper(), logging.INFO)


__all__ = [
    "CorpusConfig",
    "DEFAULT_ENV_FILES",
    "REPO_ROOT",
    "RetrieverSettings",
    "get_config",
    "get_settings",
    "init_logging",
]
