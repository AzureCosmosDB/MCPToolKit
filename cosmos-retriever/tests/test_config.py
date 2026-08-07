"""Exhaustive tests for `cosmos_retriever.config`.

Covers the internal *resolution* logic of the settings module without touching
Azure / OpenAI / Baseten: all external clients (CosmosClient, OpenAI,
AzureOpenAI, Azure credentials, Baseten PerformanceClient) are patched with
recording fakes, and ``os.environ`` is driven via monkeypatch.

Not duplicated here (already in test_runtime_config.py): apply_structural_overrides,
RuntimeConfig.structural_key, and RuntimeConfig validators / extra-forbid.

Deterministic settings are built with ``_env_file=None`` so no .env leaks and
explicit init kwargs win over any ambient environment variables.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import sys
from types import SimpleNamespace

import pytest

from cosmos_retriever import config
from cosmos_retriever.config import (
    CorpusConfig,
    RetrieverSettings,
    ServerConfigUpdate,
    get_config,
    get_settings,
)
from cosmos_retriever.retrieval.schema_override import SchemaOverride

# ────────────────────────────── helpers ───────────────────────────────────


def _settings(**kw) -> RetrieverSettings:
    return RetrieverSettings(_env_file=None, **kw)


class FakeCosmosClient:
    instances: list = []

    def __init__(self, account_uri, credential=None):
        self.account_uri = account_uri
        self.credential = credential
        self.db_requests: list = []
        FakeCosmosClient.instances.append(self)

    def get_database_client(self, name):
        self.db_requests.append(name)
        return SimpleNamespace(database=name)


class FakeOpenAI:
    instances: list = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        FakeOpenAI.instances.append(self)


class FakeAzureOpenAI:
    instances: list = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        FakeAzureOpenAI.instances.append(self)


@pytest.fixture(autouse=True)
def _reset_fakes():
    FakeCosmosClient.instances = []
    FakeOpenAI.instances = []
    FakeAzureOpenAI.instances = []
    yield


@pytest.fixture
def patch_clients(monkeypatch):
    monkeypatch.setattr(config, "CosmosClient", FakeCosmosClient)
    monkeypatch.setattr(config, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(config, "AzureCliCredential", lambda: "CLI-CRED")
    monkeypatch.setattr(config, "DefaultAzureCredential", lambda: "DEFAULT-CRED")
    monkeypatch.setattr("openai.AzureOpenAI", FakeAzureOpenAI)


# ═══════════════════════════ init_logging ═════════════════════════════════


def test_init_logging_smoke() -> None:
    config.init_logging(app_level=logging.DEBUG, lib_level=logging.WARNING, colors=False)


# ═══════════════════════════ CorpusConfig ═════════════════════════════════


def test_corpusconfig_is_frozen_with_defaults() -> None:
    c = CorpusConfig(
        container="c",
        account_uri="https://a",
        database="db",
        embed_base_url=None,
        embed_api_key=None,
        embed_model="m",
    )
    assert c.embed_query_instruction is None
    assert c.embed_dimensions is None
    assert c.cosmos_key is None and c.schema_override is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.container = "x"  # type: ignore[misc]


# ═══════════════════════ inference_backend validator ══════════════════════


@pytest.mark.parametrize(
    "value,expected",
    [("OPENAI_CHAT", "openai_chat"), ("  Openai_Responses ", "openai_responses"),
     ("anthropic_messages", "anthropic_messages")],
)
def test_inference_backend_normalized(value: str, expected: str) -> None:
    assert _settings(inference_backend=value).inference_backend == expected


def test_inference_backend_invalid_rejected() -> None:
    with pytest.raises(ValueError, match="INFERENCE_BACKEND must be one of"):
        _settings(inference_backend="bogus")


def test_schema_override_coerced_on_settings() -> None:
    s = _settings(cosmos_retriever_schema_override={"item_id_path": "/id"})
    assert isinstance(s.cosmos_retriever_schema_override, SchemaOverride)
    assert s.cosmos_retriever_schema_override.item_id_path == "/id"


# ═══════════════════════════ _load_registry ═══════════════════════════════


def test_load_registry_none_returns_empty() -> None:
    assert _settings()._load_registry() == {}


def test_load_registry_inline_json() -> None:
    reg = json.dumps({"corp": {"embed_model": "m"}})
    assert _settings(corpus_registry=reg)._load_registry() == {"corp": {"embed_model": "m"}}


def test_load_registry_invalid_json_raises() -> None:
    with pytest.raises(ValueError, match="not valid JSON"):
        _settings(corpus_registry="{not json")._load_registry()


def test_load_registry_non_dict_raises() -> None:
    with pytest.raises(ValueError, match="must be a JSON object"):
        _settings(corpus_registry="[1, 2, 3]")._load_registry()


def test_load_registry_missing_file_raises(tmp_path) -> None:
    missing = tmp_path / "nope.json"
    with pytest.raises(FileNotFoundError, match="missing file"):
        _settings(corpus_registry_file=str(missing))._load_registry()


def test_load_registry_reads_file(tmp_path) -> None:
    path = tmp_path / "reg.json"
    path.write_text(json.dumps({"corp": {"embed_model": "fm"}}), encoding="utf-8")
    assert _settings(corpus_registry_file=str(path))._load_registry() == {
        "corp": {"embed_model": "fm"}
    }


# ═══════════════════════ _lookup_registry_entry ═══════════════════════════


def test_lookup_prefers_db_container_over_container() -> None:
    reg = {"db/corp": {"x": 1}, "corp": {"x": 2}, "db": {"x": 3}}
    assert RetrieverSettings._lookup_registry_entry(reg, "db", "corp") == {"x": 1}


def test_lookup_falls_back_to_container_then_database() -> None:
    assert RetrieverSettings._lookup_registry_entry({"corp": {"x": 2}}, "db", "corp") == {"x": 2}
    assert RetrieverSettings._lookup_registry_entry({"db": {"x": 3}}, "db", "corp") == {"x": 3}


def test_lookup_without_database_only_tries_container() -> None:
    assert RetrieverSettings._lookup_registry_entry({"corp": {"x": 2}}, None, "corp") == {"x": 2}
    assert RetrieverSettings._lookup_registry_entry({"db": {"x": 3}}, None, "corp") is None


def test_lookup_no_match_returns_none() -> None:
    assert RetrieverSettings._lookup_registry_entry({"other": {}}, "db", "corp") is None


# ═══════════════════════════ resolve_corpus ═══════════════════════════════


def test_resolve_corpus_no_target_raises() -> None:
    with pytest.raises(ValueError, match="No Cosmos container specified"):
        _settings().resolve_corpus()


def test_resolve_corpus_default_no_database_raises() -> None:
    s = _settings(cosmos_corpus_container="corp", account_uri="https://a")
    with pytest.raises(ValueError, match="No Cosmos database specified"):
        s.resolve_corpus()


def test_resolve_corpus_default_no_account_uri_raises() -> None:
    s = _settings(cosmos_corpus_container="corp", cosmos_database="db")
    with pytest.raises(ValueError, match="no fallback ACCOUNT_URI"):
        s.resolve_corpus()


def test_resolve_corpus_default_happy() -> None:
    s = _settings(
        cosmos_corpus_container="corp",
        cosmos_database="db",
        account_uri="https://acct",
        embed_endpoint="https://embed",
        openai_api_key="sk-embed",
        openai_embedding_model="text-embed",
        embed_query_instruction="inst",
        openai_embedding_dimensions=256,
        cosmos_retriever_schema_override={"item_id_path": "/id"},
    )
    c = s.resolve_corpus()
    assert c.container == "corp" and c.database == "db"
    assert c.account_uri == "https://acct"
    assert c.embed_base_url == "https://embed"
    assert c.embed_api_key.get_secret_value() == "sk-embed"
    assert c.embed_model == "text-embed"
    assert c.embed_query_instruction == "inst"
    assert c.embed_dimensions == 256
    assert isinstance(c.schema_override, SchemaOverride)


def test_resolve_corpus_entry_env_keys_and_entry_base(monkeypatch) -> None:
    monkeypatch.setenv("MY_EMBED_KEY", "embed-secret")
    monkeypatch.setenv("MY_COSMOS_KEY", "cosmos-secret")
    reg = json.dumps(
        {
            "corp": {
                "embed_base_url": "https://entry-embed",
                "embed_model": "entry-model",
                "embed_api_key_env": "MY_EMBED_KEY",
                "cosmos_key_env": "MY_COSMOS_KEY",
                "account_uri": "https://entry-acct",
                "database": "entry-db",
            }
        }
    )
    s = _settings(cosmos_corpus_container="corp", corpus_registry=reg)
    c = s.resolve_corpus()
    assert c.account_uri == "https://entry-acct"
    assert c.database == "entry-db"
    assert c.embed_base_url == "https://entry-embed"
    assert c.embed_model == "entry-model"
    assert c.embed_api_key.get_secret_value() == "embed-secret"
    assert c.cosmos_key.get_secret_value() == "cosmos-secret"


def test_resolve_corpus_entry_without_base_uses_server_endpoint(monkeypatch) -> None:
    reg = json.dumps({"corp": {"embed_model": "entry-model", "account_uri": "https://a", "database": "db"}})
    s = _settings(
        cosmos_corpus_container="corp",
        corpus_registry=reg,
        embed_endpoint="https://server-embed",
        openai_api_key="server-key",
    )
    c = s.resolve_corpus()
    assert c.embed_base_url == "https://server-embed"
    assert c.embed_api_key.get_secret_value() == "server-key"  # inherits server key


def test_resolve_corpus_entry_missing_database_raises() -> None:
    reg = json.dumps({"corp": {"embed_model": "m", "account_uri": "https://a"}})
    s = _settings(cosmos_corpus_container="corp", corpus_registry=reg)
    with pytest.raises(ValueError, match="no database configured"):
        s.resolve_corpus()


def test_resolve_corpus_entry_missing_account_uri_raises() -> None:
    reg = json.dumps({"corp": {"embed_model": "m", "database": "db"}})
    s = _settings(cosmos_corpus_container="corp", corpus_registry=reg)
    with pytest.raises(ValueError, match="no account_uri configured"):
        s.resolve_corpus()


def test_resolve_corpus_entry_dimensions_zero_is_respected() -> None:
    reg = json.dumps(
        {"corp": {"embed_model": "m", "account_uri": "https://a", "database": "db", "embed_dimensions": 0}}
    )
    s = _settings(cosmos_corpus_container="corp", corpus_registry=reg, openai_embedding_dimensions=999)
    assert s.resolve_corpus().embed_dimensions == 0  # explicit 0 wins over settings default


def test_resolve_corpus_entry_schema_override_and_fallback() -> None:
    reg = json.dumps(
        {"corp": {"embed_model": "m", "account_uri": "https://a", "database": "db",
                  "schema_override": {"item_id_path": "/entry"}}}
    )
    s = _settings(cosmos_corpus_container="corp", corpus_registry=reg)
    assert s.resolve_corpus().schema_override.item_id_path == "/entry"

    reg2 = json.dumps({"corp": {"embed_model": "m", "account_uri": "https://a", "database": "db"}})
    s2 = _settings(
        cosmos_corpus_container="corp",
        corpus_registry=reg2,
        cosmos_retriever_schema_override={"item_id_path": "/default"},
    )
    assert s2.resolve_corpus().schema_override.item_id_path == "/default"


def test_resolve_corpus_explicit_container_argument() -> None:
    reg = json.dumps({"other": {"embed_model": "m", "account_uri": "https://a", "database": "db"}})
    s = _settings(corpus_registry=reg)
    assert s.resolve_corpus(container="other").container == "other"


# ═══════════════════════════ _cosmos_credential ═══════════════════════════


def test_cosmos_credential_default_uses_cli(patch_clients, monkeypatch) -> None:
    monkeypatch.delenv("COSMOS_USE_DEFAULT_CREDENTIAL", raising=False)
    assert _settings()._cosmos_credential() == "CLI-CRED"


@pytest.mark.parametrize("flag", ["1", "true", "YES"])
def test_cosmos_credential_default_azure(patch_clients, monkeypatch, flag: str) -> None:
    monkeypatch.setenv("COSMOS_USE_DEFAULT_CREDENTIAL", flag)
    assert _settings()._cosmos_credential() == "DEFAULT-CRED"


# ═══════════════════════ build_cosmos_client / database ════════════════════


def _corpus(**kw) -> CorpusConfig:
    base = dict(
        container="c", account_uri="https://acct", database="db",
        embed_base_url=None, embed_api_key=None, embed_model="m",
    )
    base.update(kw)
    return CorpusConfig(**base)


def test_build_cosmos_client_with_key(patch_clients) -> None:
    from pydantic import SecretStr

    client = _settings().build_cosmos_client(_corpus(cosmos_key=SecretStr("mykey")))
    assert client.account_uri == "https://acct"
    assert client.credential == "mykey"  # raw secret, not credential object


def test_build_cosmos_client_without_key_uses_credential(patch_clients, monkeypatch) -> None:
    monkeypatch.delenv("COSMOS_USE_DEFAULT_CREDENTIAL", raising=False)
    client = _settings().build_cosmos_client(_corpus())
    assert client.credential == "CLI-CRED"


def test_build_cosmos_database_chains(patch_clients) -> None:
    db = _settings().build_cosmos_database(_corpus(database="mydb"))
    assert db.database == "mydb"


# ═══════════════════════════ build_openai_client ══════════════════════════


def test_build_openai_client_with_base_url_and_key(patch_clients) -> None:
    from pydantic import SecretStr

    client = _settings().build_openai_client(
        _corpus(embed_base_url="https://e", embed_api_key=SecretStr("k"))
    )
    assert client.kwargs == {"base_url": "https://e", "api_key": "k"}


def test_build_openai_client_no_base_url_empty_key(patch_clients) -> None:
    client = _settings().build_openai_client(_corpus(embed_base_url=None, embed_api_key=None))
    assert "base_url" not in client.kwargs
    assert client.kwargs["api_key"] == "EMPTY"


# ═══════════════════════════ use_*_backend props ══════════════════════════


def test_backend_properties() -> None:
    assert _settings(inference_backend="openai_chat").use_chat_backend is True
    assert _settings(inference_backend="openai_responses").use_responses_backend is True
    assert _settings(inference_backend="anthropic_messages").use_anthropic_backend is True


def test_generic_backend_is_chat_or_responses() -> None:
    assert _settings(inference_backend="openai_chat").use_generic_llm_backend is True
    assert _settings(inference_backend="openai_responses").use_generic_llm_backend is True
    assert _settings(inference_backend="anthropic_messages").use_generic_llm_backend is False


# ═══════════════════════════ build_chat_client ════════════════════════════


def test_build_chat_client_requires_base_url() -> None:
    with pytest.raises(ValueError, match="CHAT_BASE_URL must be set"):
        _settings(chat_model="m").build_chat_client()


def test_build_chat_client_requires_model() -> None:
    with pytest.raises(ValueError, match="CHAT_MODEL"):
        _settings(chat_base_url="https://c").build_chat_client()


def test_build_chat_client_plain_openai(patch_clients) -> None:
    client = _settings(chat_base_url="https://c", chat_model="m").build_chat_client()
    assert isinstance(client, FakeOpenAI)
    assert client.kwargs == {"base_url": "https://c", "api_key": "EMPTY"}


def test_build_chat_client_azure_when_api_version(patch_clients) -> None:
    from pydantic import SecretStr

    s = _settings(chat_base_url="https://c", chat_model="m", chat_api_version="2024-01")
    s.chat_api_key = SecretStr("chatkey")
    client = s.build_chat_client()
    assert isinstance(client, FakeAzureOpenAI)
    assert client.kwargs == {
        "azure_endpoint": "https://c",
        "api_key": "chatkey",
        "api_version": "2024-01",
    }


# ═══════════════════════════ apply_server_updates ═════════════════════════


def test_apply_server_updates_maps_and_wraps() -> None:
    s = _settings(chat_model="old", cosmos_retriever_cache_max_entries=4)
    update = ServerConfigUpdate(
        chat_model="new",
        cache_max_entries=10,
        token_budget=8192,
        chat_api_key="secret",
        schema_override={"item_id_path": "/id"},
    )
    new = s.apply_server_updates(update)
    assert new.chat_model == "new"
    assert new.cosmos_retriever_cache_max_entries == 10
    assert new.cosmos_retriever_token_budget == 8192
    assert new.chat_api_key.get_secret_value() == "secret"
    assert isinstance(new.cosmos_retriever_schema_override, SchemaOverride)
    # original untouched (deep copy)
    assert s.chat_model == "old"
    assert s.cosmos_retriever_cache_max_entries == 4


def test_apply_server_updates_only_provided_fields() -> None:
    s = _settings(chat_model="keep", chat_max_tokens=1000)
    new = s.apply_server_updates(ServerConfigUpdate(chat_model="changed"))
    assert new.chat_model == "changed"
    assert new.chat_max_tokens == 1000  # untouched


# ═══════════════════════════ redacted_config ══════════════════════════════


def test_redacted_config_masks_secrets_and_dumps_override() -> None:
    from pydantic import SecretStr

    s = _settings(
        cosmos_database="db",
        cosmos_retriever_schema_override={"item_id_path": "/id"},
    )
    s.chat_api_key = SecretStr("x")
    s.cosmos_key = None
    red = s.redacted_config()
    assert red["chat_api_key"] == "***set***"
    assert red["cosmos_key"] is None
    assert red["cosmos_database"] == "db"
    assert red["cache_max_entries"] == s.cosmos_retriever_cache_max_entries
    assert red["schema_override"]["item_id_path"] == "/id"


def test_redacted_config_none_schema_override() -> None:
    assert _settings().redacted_config()["schema_override"] is None


# ═══════════════════════ get_* client delegation ══════════════════════════


def test_get_cosmos_client_delegates(patch_clients, monkeypatch) -> None:
    from pydantic import SecretStr

    corpus = _corpus(cosmos_key=SecretStr("k"), account_uri="https://x")
    monkeypatch.setattr(RetrieverSettings, "resolve_corpus", lambda self, container=None: corpus)
    client = _settings().get_cosmos_client()
    assert client.account_uri == "https://x" and client.credential == "k"


def test_get_cosmos_database_delegates(patch_clients, monkeypatch) -> None:
    corpus = _corpus(database="thedb")
    monkeypatch.setattr(RetrieverSettings, "resolve_corpus", lambda self, container=None: corpus)
    assert _settings().get_cosmos_database().database == "thedb"


def test_get_openai_client_delegates(patch_clients, monkeypatch) -> None:
    from pydantic import SecretStr

    corpus = _corpus(embed_base_url="https://e", embed_api_key=SecretStr("k"))
    monkeypatch.setattr(RetrieverSettings, "resolve_corpus", lambda self, container=None: corpus)
    client = _settings().get_openai_client()
    assert client.kwargs == {"base_url": "https://e", "api_key": "k"}


# ═══════════════════════════ get_baseten_client ═══════════════════════════


def test_get_baseten_client_requires_credentials() -> None:
    with pytest.raises(ValueError, match="BASETEN_API_KEY and BASETEN_MODEL_URL"):
        _settings().get_baseten_client()


def test_get_baseten_client_happy(monkeypatch) -> None:
    from pydantic import SecretStr

    built: list = []

    class FakePerf:
        def __init__(self, base_url, api_key):
            self.base_url = base_url
            self.api_key = api_key
            built.append(self)

    monkeypatch.setitem(
        sys.modules, "baseten_performance_client", SimpleNamespace(PerformanceClient=FakePerf)
    )
    s = _settings(baseten_model_url="https://bt")
    s.baseten_api_key = SecretStr("btkey")
    client = s.get_baseten_client()
    assert client.base_url == "https://bt" and client.api_key == "btkey"


# ═══════════════════ get_settings / get_config / log level ════════════════


def test_get_settings_is_cached_and_calls_init_logging(monkeypatch) -> None:
    get_settings.cache_clear()
    calls: list = []
    monkeypatch.setattr(config, "init_logging", lambda **kw: calls.append(kw))
    first = get_settings()
    second = get_settings()
    assert first is second  # lru_cache
    assert len(calls) == 1  # init_logging only on the cache-miss build


def test_get_config_returns_settings() -> None:
    get_settings.cache_clear()
    assert get_config() is get_settings()


@pytest.mark.parametrize(
    "level,expected",
    [("debug", logging.DEBUG), ("INFO", logging.INFO), ("Warning", logging.WARNING),
     ("bogus", logging.INFO)],
)
def test_log_level_to_int(level: str, expected: int) -> None:
    assert config._log_level_to_int(level) == expected


# ═══════════════════════════ ServerConfigUpdate ═══════════════════════════


def test_server_update_backend_validator() -> None:
    assert ServerConfigUpdate(inference_backend="OPENAI_CHAT").inference_backend == "openai_chat"
    with pytest.raises(ValueError, match="inference_backend must be one of"):
        ServerConfigUpdate(inference_backend="nope")


def test_server_update_schema_override_coerced() -> None:
    u = ServerConfigUpdate(schema_override={"item_id_path": "/id"})
    assert isinstance(u.schema_override, SchemaOverride)


def test_server_update_extra_forbidden() -> None:
    with pytest.raises(ValueError):
        ServerConfigUpdate(unknown_field="x")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"chat_temperature": 2.5},
        {"chat_max_tokens": 100},
        {"chat_max_turns": 0},
        {"token_budget": 100},
        {"threshold_budget": 100},
        {"cache_max_entries": 2000},
        {"cache_ttl_seconds": 0.0},
        {"search_display_limit": 100},
    ],
)
def test_server_update_numeric_bounds_rejected(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        ServerConfigUpdate(**kwargs)


# ═══════════════════════════════ __all__ ══════════════════════════════════


def test_all_exports_present() -> None:
    for name in config.__all__:
        assert hasattr(config, name), name
