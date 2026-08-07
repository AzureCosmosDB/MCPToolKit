"""Exhaustive tests for the HTTP service (`cosmos_retriever.server`).

Covers, without Cosmos / OpenAI / real engines:

  1. RetrievalScope.resolve  — db/container fallbacks + "*" whole-database mode
  2. SearchRequest           — defaults, alias, populate_by_name, bounds
  3. _RetrieverPool          — stats mapping, build-once caching, per-key locks,
                               _build deep-copy + scope wiring, update_settings
                               (clear vs rebuild), settings property
  4. create_app routes       — /health (with/without pool), GET/PATCH /config,
                               POST /search (happy, missing db, engine error),
                               get_settings fallback

`server.CosmosRetriever` is patched with a fake recording engine; real
`RetrieverSettings` (with ``_env_file=None`` so no .env leaks) drives config
logic. Async pool methods are driven with ``anyio.run``; routes via
``fastapi.testclient.TestClient``.
"""
from __future__ import annotations

from dataclasses import dataclass

import anyio
import pytest
from fastapi.testclient import TestClient

from cosmos_retriever import config, server
from cosmos_retriever.config import RetrieverSettings, RuntimeConfig
from cosmos_retriever.server import RetrievalScope, SearchRequest, _RetrieverPool, create_app

# ────────────────────────────── helpers ───────────────────────────────────


def _settings(**kw) -> RetrieverSettings:
    """Deterministic settings: init kwargs win over env, .env disabled."""
    base: dict = {
        "cosmos_database": None,
        "cosmos_corpus_container": None,
        "cosmos_retriever_cache_max_entries": 4,
        "cosmos_retriever_cache_ttl_seconds": 100.0,
    }
    base.update(kw)
    return RetrieverSettings(_env_file=None, **base)


@dataclass
class FakeResult:
    answer: str
    documents: list


def _install_fake_retriever(monkeypatch, search_fn=None) -> list:
    """Patch server.CosmosRetriever with a recorder; return list of built engines."""
    built: list = []

    class FakeCosmosRetriever:
        def __init__(self, *, settings, corpus_name):
            self.settings = settings
            self.corpus_name = corpus_name
            self.search_calls: list = []
            built.append(self)

        def search(self, query, max_documents=20, overrides=None):
            self.search_calls.append((query, max_documents, overrides))
            if search_fn is not None:
                return search_fn(query, max_documents, overrides)
            return FakeResult(answer=f"ans:{query}", documents=[1, 2])

    monkeypatch.setattr(server, "CosmosRetriever", FakeCosmosRetriever)
    return built


def _run(func, *args):
    return anyio.run(func, *args)


# ═══════════════════════ 1. RetrievalScope.resolve ════════════════════════


def test_scope_is_namedtuple_fields() -> None:
    s = RetrievalScope(database="d", container="c")
    assert (s.database, s.container) == ("d", "c")


def test_scope_uses_settings_defaults() -> None:
    s = RetrievalScope.resolve(_settings(cosmos_database="D", cosmos_corpus_container="C"), None, None)
    assert s == ("D", "C")


def test_scope_container_defaults_to_star() -> None:
    s = RetrievalScope.resolve(_settings(cosmos_database="D"), None, None)
    assert s == ("D", "*")


def test_scope_database_none_when_unset() -> None:
    s = RetrievalScope.resolve(_settings(), None, None)
    assert s == (None, "*")


def test_scope_explicit_args_override_settings() -> None:
    s = RetrievalScope.resolve(
        _settings(cosmos_database="D", cosmos_corpus_container="C"), "D2", "C2"
    )
    assert s == ("D2", "C2")


def test_scope_explicit_db_container_omitted_uses_star() -> None:
    s = RetrievalScope.resolve(_settings(cosmos_database="D"), "D2", None)
    assert s == ("D2", "*")


# ═══════════════════════════ 2. SearchRequest ═════════════════════════════


def test_search_request_defaults() -> None:
    r = SearchRequest(query="q")
    assert r.max_documents == 20
    assert r.database is None and r.container is None and r.overrides is None


def test_search_request_alias_and_field_name() -> None:
    assert SearchRequest(**{"query": "q", "maxDocuments": 5}).max_documents == 5
    assert SearchRequest(query="q", max_documents=7).max_documents == 7  # populate_by_name


def test_search_request_query_min_length() -> None:
    with pytest.raises(ValueError):
        SearchRequest(query="")


@pytest.mark.parametrize("n", [1, 30])
def test_search_request_max_documents_bounds_ok(n: int) -> None:
    assert SearchRequest(query="q", max_documents=n).max_documents == n


@pytest.mark.parametrize("n", [0, 31])
def test_search_request_max_documents_out_of_range(n: int) -> None:
    with pytest.raises(ValueError):
        SearchRequest(query="q", max_documents=n)


def test_search_request_overrides_parsed_to_runtime_config() -> None:
    r = SearchRequest(query="q", overrides={"chat_model": "m"})
    assert isinstance(r.overrides, RuntimeConfig)
    assert r.overrides.chat_model == "m"


# ═══════════════════════════ 3. _RetrieverPool ════════════════════════════


async def _get(pool, a, b, o):
    return await pool.get(a, b, o)


async def _get_twice(pool, a, b, o1, o2):
    r1 = await pool.get(a, b, o1)
    r2 = await pool.get(a, b, o2)
    return r1, r2


def test_pool_stats_shape_initial() -> None:
    pool = _RetrieverPool(_settings(cosmos_retriever_cache_max_entries=9, cosmos_retriever_cache_ttl_seconds=42.0))
    s = pool.stats()
    assert set(s) == {
        "entries", "max_entries", "ttl_seconds", "hits", "misses", "evictions", "expirations"
    }
    assert s["entries"] == 0
    assert s["max_entries"] == 9
    assert s["ttl_seconds"] == 42.0


def test_pool_settings_property() -> None:
    st = _settings(cosmos_database="D")
    pool = _RetrieverPool(st)
    assert pool.settings is st


def test_pool_get_builds_once_and_caches(monkeypatch) -> None:
    built = _install_fake_retriever(monkeypatch)
    pool = _RetrieverPool(_settings(cosmos_database="D"))
    (r1, lock1), (r2, lock2) = _run(_get_twice, pool, None, None, None, None)
    assert r1 is r2  # cached engine reused
    assert lock1 is lock2  # stable per-key lock
    assert len(built) == 1
    stats = pool.stats()
    # First get misses twice (double-checked lock re-reads the cache); second hits once.
    assert stats["entries"] == 1 and stats["hits"] == 1 and stats["misses"] == 2


def test_pool_get_scope_wires_database_and_container(monkeypatch) -> None:
    built = _install_fake_retriever(monkeypatch)
    pool = _RetrieverPool(_settings(cosmos_database="D"))
    _run(_get, pool, None, None, None)
    engine = built[0]
    assert engine.settings.cosmos_database == "D"
    assert engine.corpus_name == "*"  # container omitted -> whole database


def test_pool_build_deep_copies_and_does_not_mutate_pool_settings(monkeypatch) -> None:
    built = _install_fake_retriever(monkeypatch)
    st = _settings(cosmos_database="D")
    pool = _RetrieverPool(st)
    _run(_get, pool, "OTHER", None, None)
    engine = built[0]
    assert engine.settings is not st  # deep copy, not the pool's own settings
    assert engine.settings.cosmos_database == "OTHER"
    assert st.cosmos_database == "D"  # pool settings untouched


def test_pool_distinct_overrides_build_separate_engines(monkeypatch) -> None:
    built = _install_fake_retriever(monkeypatch)
    pool = _RetrieverPool(_settings(cosmos_database="D"))
    o1 = RuntimeConfig(chat_model="a")
    o2 = RuntimeConfig(chat_model="b")
    (r1, lock1), (r2, lock2) = _run(_get_twice, pool, None, None, o1, o2)
    assert r1 is not r2
    assert lock1 is not lock2
    assert len(built) == 2


def test_pool_update_settings_clears_cache_when_size_unchanged(monkeypatch) -> None:
    _install_fake_retriever(monkeypatch)
    pool = _RetrieverPool(_settings(cosmos_database="D", cosmos_retriever_cache_max_entries=4))
    _run(_get, pool, None, None, None)
    assert pool.stats()["entries"] == 1
    cache_before = pool._cache
    new = _settings(cosmos_database="D2", cosmos_retriever_cache_max_entries=4, cosmos_retriever_cache_ttl_seconds=100.0)
    _run(pool.update_settings, new)
    assert pool._cache is cache_before  # same cache object, just cleared
    assert pool.stats()["entries"] == 0
    assert pool.settings is new
    assert pool._locks == {}


def test_pool_update_settings_rebuilds_cache_on_size_change(monkeypatch) -> None:
    _install_fake_retriever(monkeypatch)
    pool = _RetrieverPool(_settings(cosmos_database="D", cosmos_retriever_cache_max_entries=4))
    _run(_get, pool, None, None, None)
    cache_before = pool._cache
    new = _settings(cosmos_database="D", cosmos_retriever_cache_max_entries=8)
    _run(pool.update_settings, new)
    assert pool._cache is not cache_before  # rebuilt due to size change
    assert pool.stats()["max_entries"] == 8
    assert pool.stats()["entries"] == 0


# ═══════════════════════════ 4. create_app routes ═════════════════════════


def test_health_without_pool_returns_empty_cache() -> None:
    app = create_app(_settings())
    client = TestClient(app)  # no context manager -> lifespan not run
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "retriever_cache": {}}


def test_health_with_pool_returns_stats() -> None:
    app = create_app(_settings())
    with TestClient(app) as client:
        body = client.get("/health").json()
    assert body["status"] == "ok"
    assert set(body["retriever_cache"]) >= {"entries", "max_entries", "hits", "misses"}


def test_get_config_returns_redacted_and_pool() -> None:
    app = create_app(_settings(cosmos_database="D", cosmos_retriever_cache_max_entries=6))
    with TestClient(app) as client:
        body = client.get("/config").json()
    assert body["config"]["cosmos_database"] == "D"
    assert body["config"]["cache_max_entries"] == 6
    assert "pool" in body and body["pool"]["entries"] == 0


def test_patch_config_applies_and_propagates(monkeypatch) -> None:
    built = _install_fake_retriever(monkeypatch)
    app = create_app(_settings(cosmos_database="D"))
    with TestClient(app) as client:
        resp = client.patch("/config", json={"chat_model": "newmodel"})
        body = resp.json()
        assert resp.status_code == 200
        assert body["status"] == "ok"
        assert body["changed"] == ["chat_model"]
        assert body["config"]["chat_model"] == "newmodel"
        # New engine built after update carries the new setting.
        client.post("/search", json={"query": "q", "database": "D"})
    assert built[-1].settings.chat_model == "newmodel"


def test_patch_config_error_returns_400(monkeypatch) -> None:
    def _boom(self, update):
        raise ValueError("bad update")

    monkeypatch.setattr(config.RetrieverSettings, "apply_server_updates", _boom)
    app = create_app(_settings(cosmos_database="D"))
    with TestClient(app) as client:
        resp = client.patch("/config", json={"chat_model": "x"})
    assert resp.status_code == 400
    assert resp.json() == {"error": "bad update", "type": "ValueError"}


def test_search_happy_path_returns_result_dict(monkeypatch) -> None:
    built = _install_fake_retriever(monkeypatch)
    app = create_app(_settings(cosmos_database="D"))
    with TestClient(app) as client:
        resp = client.post(
            "/search",
            json={"query": "hi", "database": "D", "maxDocuments": 5,
                  "overrides": {"chat_model": "m"}},
        )
    assert resp.status_code == 200
    assert resp.json() == {"answer": "ans:hi", "documents": [1, 2]}
    query, max_docs, overrides = built[0].search_calls[0]
    assert query == "hi" and max_docs == 5
    assert isinstance(overrides, RuntimeConfig) and overrides.chat_model == "m"


def test_search_missing_database_returns_400(monkeypatch) -> None:
    _install_fake_retriever(monkeypatch)
    app = create_app(_settings())  # no default database
    with TestClient(app) as client:
        resp = client.post("/search", json={"query": "hi"})
    assert resp.status_code == 400
    assert resp.json()["type"] == "ValueError"
    assert "Missing required field: database" in resp.json()["error"]


def test_search_engine_exception_returns_500(monkeypatch) -> None:
    def _raise(query, max_documents, overrides):
        raise RuntimeError("kaboom")

    _install_fake_retriever(monkeypatch, search_fn=_raise)
    app = create_app(_settings(cosmos_database="D"))
    with TestClient(app) as client:
        resp = client.post("/search", json={"query": "hi", "database": "D"})
    assert resp.status_code == 500
    assert resp.json() == {"error": "kaboom", "type": "RuntimeError"}


def test_create_app_falls_back_to_get_settings(monkeypatch) -> None:
    sentinel = _settings(cosmos_database="FROM_GET_SETTINGS")
    monkeypatch.setattr(server, "get_settings", lambda: sentinel)
    app = create_app()  # settings=None -> get_settings()
    with TestClient(app) as client:
        body = client.get("/config").json()
    assert body["config"]["cosmos_database"] == "FROM_GET_SETTINGS"
