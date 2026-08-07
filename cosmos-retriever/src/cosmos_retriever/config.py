"""All the settings the service runs on, in one place.

This module is where the Cosmos Retriever gets its configuration. An operator
sets values through environment variables or a .env file: which inference
backend to use, how to reach the chat and embedding endpoints, which Cosmos
account to query, token budgets, cache sizes, and so on. 

Everything the service
needs to know about its environment is gathered here and validated on the way in,
so a bad value is caught at startup rather than mid request.

There are two things to read the module as. The settings object is the list of
knobs an operator can turn; each one carries a default and a short description of
what it does, and that set of fields is the whole public surface. The rest of the
module is the quiet machinery that turns those raw values into things the service
can actually use: live connections to Cosmos and the model endpoints, and a
resolved, per-corpus view that pins down the exact account, database, container,
and embedding details for one corpus. 

Callers ask for that resolved view and the
clients, they never touch the wiring behind it.

A single corpus can also override the shared defaults through a registry, so one
deployment can serve several corpora that live in different places or use
different embedding models.
"""

from __future__ import annotations

import hashlib
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
from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from cosmos_retriever.retrieval.schema_override import SchemaOverride

if TYPE_CHECKING:
    from baseten_performance_client import PerformanceClient

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILES = (str(REPO_ROOT / ".env.local"), str(REPO_ROOT / ".env"))

for _env_path in DEFAULT_ENV_FILES:
    load_dotenv(_env_path, override=False)


def init_logging(
    app_level: int = logging.INFO,
    *,
    lib_level: int = logging.WARNING,
    colors: bool = True,
) -> None:

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

    """Fully-resolved configuration for a single corpus (internal).

    Produced by :meth:`RetrieverSettings.resolve_corpus` by merging a corpus
    registry entry with the server defaults: the concrete Cosmos account /
    database / container plus the embedding endpoint, model, and (optional)
    output dimensionality and query instruction used to search it.
    """

    container: str
    account_uri: str
    database: str
    embed_base_url: str | None

    embed_api_key: SecretStr | None
    embed_model: str
    embed_query_instruction: str | None = None
    embed_dimensions: int | None = None

    cosmos_key: SecretStr | None = None
    schema_override: SchemaOverride | None = None


class RetrieverSettings(BaseSettings):

    """Service settings (pydantic-settings), sourced from env vars + ``.env``.

    The *fields* below are the user-facing configuration schema; the *methods*
    (``resolve_corpus``, ``build_*_client``, ``apply_structural_overrides``, the
    ``use_*_backend`` properties) are internal resolution used by the server. See
    the module docstring for the split.
    """

    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    inference_backend: str = Field(
        default="openai_responses",
        description='Inference backend: "openai_responses", "openai_chat", or "anthropic_messages".',
    )

    @field_validator("inference_backend")
    @classmethod
    def _validate_inference_backend(cls, v: str) -> str:
        normalized = (v or "").strip().lower()
        allowed = {"openai_chat", "openai_responses", "anthropic_messages"}
        if normalized not in allowed:
            raise ValueError(
                f"INFERENCE_BACKEND must be one of {sorted(allowed)}, got {v!r}."
            )
        return normalized

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
    anthropic_version: str = Field(
        default="2023-06-01",
        description="anthropic-version header for the anthropic_messages backend.",
    )
    anthropic_auth_header: str = Field(
        default="x-api-key",
        description='Auth header name for the anthropic_messages endpoint (e.g. "x-api-key" or "api-key").',
    )

    account_uri: str | None = Field(
        default=None,
        description=(
            "Fallback Cosmos account URI for corpora not found in the registry. "
            "Registry entries provide their own account_uri (which wins), so this "
            "is only needed when querying an unregistered database/container."
        ),
    )
    cosmos_database: str | None = Field(
        default=None,
        description=(
            "Cosmos database to query. There is no default: every request must "
            "specify the database (the MCP client selects it dynamically)."
        ),
    )
    cosmos_corpus_container: str | None = Field(
        default=None,
        description=(
            "Cosmos container to query. There is no default: every request must "
            "specify the container (the MCP client selects it dynamically)."
        ),
    )
    cosmos_key: SecretStr | None = None

    openai_api_key: SecretStr | None = None
    openai_embedding_model: str | None = None
    openai_embedding_dimensions: int | None = Field(
        default=None,
        description=(
            "Requested embedding output dimensionality. Set when the query "
            "embedder supports Matryoshka/`dimensions` truncation (e.g. serving "
            "Qwen3-Embedding-8B at 2560 dims to match a corpus). Corpus-registry "
            "entries may override this per corpus via 'embed_dimensions'."
        ),
    )
    embed_endpoint: str | None = Field(
        default=None,
        description=(
            "Embedding endpoint base URL. Leave unset to use plain OpenAI "
            "(api.openai.com). For Azure pass https://<resource>.../openai/v1; "
            "for a local server pass http://host:port/v1."
        ),
    )
    embed_query_instruction: str | None = None

    corpus_registry: str | None = Field(
        default=None,
        description="JSON string mapping container name -> CorpusConfig overrides.",
    )
    corpus_registry_file: str | None = Field(
        default=None,
        description="Path to a JSON file holding the corpus registry.",
    )

    baseten_api_key: SecretStr | None = None
    baseten_model_url: str | None = None
    vllm_reranker_url: str | None = None

    cosmos_retriever_max_turns: int = Field(default=35, ge=1, le=200, alias="COSMOS_RETRIEVER_MAX_TURNS")
    cosmos_retriever_threshold_budget: int = Field(
        default=16384, ge=1024, alias="COSMOS_RETRIEVER_THRESHOLD_BUDGET"
    )
    cosmos_retriever_token_budget: int = Field(
        default=32268, ge=4096, alias="COSMOS_RETRIEVER_TOKEN_BUDGET"
    )
    cosmos_retriever_search_display_limit: int = Field(default=15, ge=1, le=50)

    cosmos_retriever_cache_max_entries: int = Field(default=32, ge=1, le=1024)
    cosmos_retriever_cache_ttl_seconds: float = Field(default=900.0, gt=0.0)

    cosmos_retriever_schema_override: SchemaOverride | None = Field(
        default=None,
        description=(
            "Default schema override applied to any corpus that does not define "
            "its own in the corpus registry. Accepts a JSON object with keys like "
            "document_id_path, chunk_id_path, chunk_order_path, title_path, "
            "source_path, item_id_path, use_dunder_codec. Omit for pure discovery."
        ),
    )

    cosmos_retriever_raw_query_enabled: bool = Field(
        default=True,
        description=(
            "Expose the read-only custom Cosmos SQL query tool (execute_query) to "
            "the agent. Set false to remove the tool entirely."
        ),
    )

    @field_validator("cosmos_retriever_schema_override", mode="before")
    @classmethod
    def _coerce_schema_override(cls, v: Any) -> SchemaOverride | None:
        return SchemaOverride.coerce(v)

    host: str = Field(default="0.0.0.0")
    port: int = Field(default=9000, ge=1, le=65535)
    log_level: str = Field(default="info")

    def _load_registry(self) -> dict[str, dict[str, Any]]:

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

    @staticmethod
    def _lookup_registry_entry(
        registry: dict[str, dict[str, Any]],
        database: str | None,
        container: str,
    ) -> dict[str, Any] | None:
        """Resolve a corpus-registry entry for a (database, container) pair.

        Keys are tried from most to least specific so embedding config can be
        pinned per database, per container, or per database-wide default:

            1. "<database>/<container>"  — exact collection
            2. "<container>"             — same container name in any database
            3. "<database>"              — database-wide default (all containers)

        Returns the first matching entry, or ``None`` if nothing matches.
        """
        candidates: list[str] = []
        if database:
            candidates.append(f"{database}/{container}")
        candidates.append(container)
        if database:
            candidates.append(database)
        for key in candidates:
            entry = registry.get(key)
            if entry is not None:
                return entry
        return None

    def resolve_corpus(self, container: str | None = None) -> CorpusConfig:

        registry = self._load_registry()
        target = container or self.cosmos_corpus_container
        if not target:
            raise ValueError(
                "No Cosmos container specified. Pass 'container' on the request "
                "(the MCP client selects it per call); there is no server default."
            )
        entry = self._lookup_registry_entry(registry, self.cosmos_database, target)

        def _resolve_default_embed() -> tuple[str | None, SecretStr | None, str | None]:
            return self.embed_endpoint, self.openai_api_key, self.openai_embedding_model

        if entry is None:
            database = self.cosmos_database
            if not database:
                raise ValueError(
                    "No Cosmos database specified. Pass 'database' on the request "
                    "(the MCP client selects it per call); there is no server default."
                )
            base, key, model = _resolve_default_embed()
            if not self.account_uri:
                raise ValueError(
                    f"No Cosmos account for corpus '{target}': it is not in the "
                    "registry and no fallback ACCOUNT_URI is configured."
                )
            return CorpusConfig(
                container=target,
                account_uri=self.account_uri,
                database=database,
                embed_base_url=base,
                embed_api_key=key,
                embed_model=model,
                embed_query_instruction=self.embed_query_instruction,
                embed_dimensions=self.openai_embedding_dimensions,
                cosmos_key=self.cosmos_key,
                schema_override=self.cosmos_retriever_schema_override,
            )

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

        database = entry.get("database") or self.cosmos_database
        if not database:
            raise ValueError(
                f"Corpus '{target}' has no database configured and none was passed "
                "on the request."
            )

        # Endpoint fallback: an entry may list only a model (no endpoint). In
        # that case reuse the server-default embed endpoint + key and simply
        # query it for the entry's model. An entry that brings its own endpoint
        # keeps its own key (never inherits the default key for a different host).
        entry_base = entry.get("embed_base_url")
        if entry_base:
            embed_base_url = entry_base
            embed_api_key = api_key_value
        else:
            embed_base_url = self.embed_endpoint
            embed_api_key = api_key_value or self.openai_api_key

        # Schema override: an entry may define its own; otherwise fall back to
        # the server-level default. Absent both -> pure discovery (None).
        schema_override = SchemaOverride.coerce(entry.get("schema_override"))
        if schema_override is None:
            schema_override = self.cosmos_retriever_schema_override

        account_uri = entry.get("account_uri") or self.account_uri
        if not account_uri:
            raise ValueError(
                f"Corpus '{target}' has no account_uri configured (registry entry "
                "omits it and no fallback ACCOUNT_URI is set)."
            )

        return CorpusConfig(
            container=target,
            account_uri=account_uri,
            database=database,
            embed_base_url=embed_base_url,
            embed_api_key=embed_api_key,
            embed_model=entry.get("embed_model") or self.openai_embedding_model,
            embed_query_instruction=entry.get("embed_query_instruction")
            or self.embed_query_instruction,
            embed_dimensions=entry.get("embed_dimensions")
            if entry.get("embed_dimensions") is not None
            else self.openai_embedding_dimensions,
            cosmos_key=cosmos_key_value,
            schema_override=schema_override,
        )

    def _cosmos_credential(self):

        if os.environ.get("COSMOS_USE_DEFAULT_CREDENTIAL", "").lower() in {"1", "true", "yes"}:
            return DefaultAzureCredential()
        return AzureCliCredential()

    def build_cosmos_client(self, corpus: CorpusConfig) -> CosmosClient:

        if corpus.cosmos_key is not None:
            return CosmosClient(
                corpus.account_uri, credential=corpus.cosmos_key.get_secret_value()
            )
        return CosmosClient(corpus.account_uri, credential=self._cosmos_credential())

    def build_cosmos_database(self, corpus: CorpusConfig) -> DatabaseProxy:

        return self.build_cosmos_client(corpus).get_database_client(corpus.database)

    def build_openai_client(self, corpus: CorpusConfig) -> OpenAI:

        kwargs: dict[str, Any] = {}
        if corpus.embed_base_url:
            kwargs["base_url"] = corpus.embed_base_url
        kwargs["api_key"] = (
            corpus.embed_api_key.get_secret_value() if corpus.embed_api_key is not None else "EMPTY"
        )
        return OpenAI(**kwargs)

    @property
    def use_chat_backend(self) -> bool:

        return self.inference_backend.strip().lower() == "openai_chat"

    @property
    def use_responses_backend(self) -> bool:

        return self.inference_backend.strip().lower() == "openai_responses"

    @property
    def use_anthropic_backend(self) -> bool:

        return self.inference_backend.strip().lower() == "anthropic_messages"

    @property
    def use_generic_llm_backend(self) -> bool:

        return self.use_chat_backend or self.use_responses_backend

    def build_chat_client(self) -> OpenAI:

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
            from openai import AzureOpenAI

            return AzureOpenAI(
                azure_endpoint=self.chat_base_url,
                api_key=api_key,
                api_version=self.chat_api_version,
            )
        return OpenAI(base_url=self.chat_base_url, api_key=api_key)

    def apply_structural_overrides(self, rc: "RuntimeConfig | None") -> "RetrieverSettings":
        if rc is None:
            return self
        updated = self.model_copy(deep=True)
        mapping = {
            "inference_backend": "inference_backend",
            "chat_base_url": "chat_base_url",
            "chat_model": "chat_model",
            "chat_api_version": "chat_api_version",
            "embed_endpoint": "embed_endpoint",
            "openai_embedding_model": "openai_embedding_model",
            "account_uri": "account_uri",
            "embed_query_instruction": "embed_query_instruction",
            "schema_override": "cosmos_retriever_schema_override",
            "search_display_limit": "cosmos_retriever_search_display_limit",
        }
        for src, dst in mapping.items():
            value = getattr(rc, src)
            if value is not None:
                setattr(updated, dst, value)
        if rc.chat_api_key is not None:
            updated.chat_api_key = SecretStr(rc.chat_api_key)
        if rc.openai_api_key is not None:
            updated.openai_api_key = SecretStr(rc.openai_api_key)
        return updated

    # Maps ServerConfigUpdate field names -> RetrieverSettings attribute names.
    _SERVER_UPDATE_MAP = {
        "schema_override": "cosmos_retriever_schema_override",
        "search_display_limit": "cosmos_retriever_search_display_limit",
        "token_budget": "cosmos_retriever_token_budget",
        "threshold_budget": "cosmos_retriever_threshold_budget",
        "max_turns": "cosmos_retriever_max_turns",
        "cache_max_entries": "cosmos_retriever_cache_max_entries",
        "cache_ttl_seconds": "cosmos_retriever_cache_ttl_seconds",
    }
    _SERVER_SECRET_FIELDS = frozenset(
        {"chat_api_key", "openai_api_key", "cosmos_key", "baseten_api_key"}
    )

    def apply_server_updates(self, update: "ServerConfigUpdate") -> "RetrieverSettings":
        """Return a new settings object with the runtime-mutable server-level
        fields overridden. Only fields explicitly set on ``update`` are applied;
        secrets are wrapped in ``SecretStr``."""
        updated = self.model_copy(deep=True)
        for src, value in update.model_dump(exclude_none=True).items():
            dst = self._SERVER_UPDATE_MAP.get(src, src)
            if src in self._SERVER_SECRET_FIELDS:
                value = SecretStr(value)
            elif src == "schema_override":
                value = SchemaOverride.coerce(value)
            setattr(updated, dst, value)
        return updated

    def redacted_config(self) -> dict[str, Any]:
        """Current server-level config for GET /config, with secrets masked."""

        def _mask(v: SecretStr | None) -> str | None:
            return "***set***" if v is not None else None

        return {
            "inference_backend": self.inference_backend,
            "chat_base_url": self.chat_base_url,
            "chat_model": self.chat_model,
            "chat_api_version": self.chat_api_version,
            "chat_api_key": _mask(self.chat_api_key),
            "chat_temperature": self.chat_temperature,
            "chat_max_tokens": self.chat_max_tokens,
            "chat_max_turns": self.chat_max_turns,
            "chat_reasoning_effort": self.chat_reasoning_effort,
            "anthropic_version": self.anthropic_version,
            "anthropic_auth_header": self.anthropic_auth_header,
            "embed_endpoint": self.embed_endpoint,
            "openai_embedding_model": self.openai_embedding_model,
            "openai_api_key": _mask(self.openai_api_key),
            "embed_query_instruction": self.embed_query_instruction,
            "account_uri": self.account_uri,
            "cosmos_database": self.cosmos_database,
            "cosmos_corpus_container": self.cosmos_corpus_container,
            "cosmos_key": _mask(self.cosmos_key),
            "schema_override": (
                self.cosmos_retriever_schema_override.model_dump()
                if self.cosmos_retriever_schema_override is not None
                else None
            ),
            "search_display_limit": self.cosmos_retriever_search_display_limit,
            "token_budget": self.cosmos_retriever_token_budget,
            "threshold_budget": self.cosmos_retriever_threshold_budget,
            "max_turns": self.cosmos_retriever_max_turns,
            "baseten_model_url": self.baseten_model_url,
            "baseten_api_key": _mask(self.baseten_api_key),
            "vllm_reranker_url": self.vllm_reranker_url,
            "cache_max_entries": self.cosmos_retriever_cache_max_entries,
            "cache_ttl_seconds": self.cosmos_retriever_cache_ttl_seconds,
            "log_level": self.log_level,
            "host": self.host,
            "port": self.port,
        }

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

        if self.baseten_api_key is None or not self.baseten_model_url:
            raise ValueError(
                "BASETEN_API_KEY and BASETEN_MODEL_URL must both be set to use Baseten reranking."
            )
        from baseten_performance_client import PerformanceClient

        return PerformanceClient(
            base_url=self.baseten_model_url,
            api_key=self.baseten_api_key.get_secret_value(),
        )


class RuntimeConfig(BaseModel):
    model_config = {"extra": "forbid"}

    inference_backend: str | None = None
    chat_base_url: str | None = None
    chat_api_key: str | None = None
    chat_model: str | None = None
    chat_api_version: str | None = None
    embed_endpoint: str | None = None
    openai_api_key: str | None = None
    openai_embedding_model: str | None = None
    account_uri: str | None = None
    embed_query_instruction: str | None = None
    schema_override: SchemaOverride | None = None
    search_display_limit: int | None = None

    chat_temperature: float | None = None
    chat_max_tokens: int | None = None
    chat_max_turns: int | None = None
    chat_reasoning_effort: str | None = None
    anthropic_version: str | None = None
    anthropic_auth_header: str | None = None
    max_documents: int | None = None

    @field_validator("inference_backend")
    @classmethod
    def _validate_backend(cls, v: str | None) -> str | None:
        if v is None:
            return None
        normalized = v.strip().lower()
        allowed = {"openai_chat", "openai_responses", "anthropic_messages"}
        if normalized not in allowed:
            raise ValueError(f"inference_backend must be one of {sorted(allowed)}, got {v!r}.")
        return normalized

    @field_validator("schema_override", mode="before")
    @classmethod
    def _validate_schema_override(cls, v: Any) -> SchemaOverride | None:
        return SchemaOverride.coerce(v)

    def structural_key(self) -> tuple:
        def _h(value: str | None) -> str | None:
            return hashlib.sha256(value.encode()).hexdigest()[:16] if value else None

        return (
            self.inference_backend,
            self.chat_base_url,
            _h(self.chat_api_key),
            self.chat_model,
            self.chat_api_version,
            self.embed_endpoint,
            _h(self.openai_api_key),
            self.openai_embedding_model,
            self.account_uri,
            self.embed_query_instruction,
            self.schema_override.stable_key() if self.schema_override else None,
            self.search_display_limit,
        )


class ServerConfigUpdate(BaseModel):
    """Partial, runtime-mutable server-level configuration accepted by the
    PATCH /config admin endpoint. Every field is optional; only provided fields
    are applied. Unknown fields are rejected."""

    model_config = {"extra": "forbid"}

    # inference / LLM defaults
    inference_backend: str | None = None
    chat_base_url: str | None = None
    chat_api_key: str | None = None
    chat_model: str | None = None
    chat_api_version: str | None = None
    chat_temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    chat_max_tokens: int | None = Field(default=None, ge=256)
    chat_max_turns: int | None = Field(default=None, ge=1, le=200)
    chat_reasoning_effort: str | None = None
    anthropic_version: str | None = None
    anthropic_auth_header: str | None = None

    # embeddings
    embed_endpoint: str | None = None
    openai_api_key: str | None = None
    openai_embedding_model: str | None = None
    embed_query_instruction: str | None = None

    # default corpus / Cosmos account
    account_uri: str | None = None
    cosmos_database: str | None = None
    cosmos_corpus_container: str | None = None
    cosmos_key: str | None = None

    # retrieval defaults
    schema_override: SchemaOverride | None = None
    search_display_limit: int | None = Field(default=None, ge=1, le=50)
    token_budget: int | None = Field(default=None, ge=4096)
    threshold_budget: int | None = Field(default=None, ge=1024)
    max_turns: int | None = Field(default=None, ge=1, le=200)

    # reranker
    baseten_api_key: str | None = None
    baseten_model_url: str | None = None
    vllm_reranker_url: str | None = None

    # pool / logging
    cache_max_entries: int | None = Field(default=None, ge=1, le=1024)
    cache_ttl_seconds: float | None = Field(default=None, gt=0.0)
    log_level: str | None = None

    @field_validator("inference_backend")
    @classmethod
    def _validate_backend(cls, v: str | None) -> str | None:
        if v is None:
            return None
        normalized = v.strip().lower()
        allowed = {"openai_chat", "openai_responses", "anthropic_messages"}
        if normalized not in allowed:
            raise ValueError(f"inference_backend must be one of {sorted(allowed)}, got {v!r}.")
        return normalized

    @field_validator("schema_override", mode="before")
    @classmethod
    def _validate_schema_override(cls, v: Any) -> SchemaOverride | None:
        return SchemaOverride.coerce(v)


@lru_cache(maxsize=1)
def get_settings() -> RetrieverSettings:

    settings = RetrieverSettings()
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
    "RuntimeConfig",
    "ServerConfigUpdate",
    "get_config",
    "get_settings",
    "init_logging",
]
