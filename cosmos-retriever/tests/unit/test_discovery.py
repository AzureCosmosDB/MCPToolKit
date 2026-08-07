from __future__ import annotations

from typing import Any

from cosmos_retriever.retrieval.discovery import (
    CapabilityProfiler,
    ResourceCatalog,
    parse_container_metadata,
)


def _props(
    *,
    pk: list[str] | None = None,
    fts_paths: list[str] | None = None,
    vectors: list[dict[str, Any]] | None = None,
    vector_indexes: list[str] | None = None,
) -> dict[str, Any]:
    idx: dict[str, Any] = {"includedPaths": [{"path": "/*"}], "excludedPaths": []}
    if fts_paths:
        idx["fullTextIndexes"] = [{"path": p} for p in fts_paths]
    if vector_indexes:
        idx["vectorIndexes"] = [{"path": p, "type": "diskANN"} for p in vector_indexes]
    props: dict[str, Any] = {
        "id": "c",
        "partitionKey": {"paths": pk or ["/id"], "kind": "Hash"},
        "indexingPolicy": idx,
    }
    if fts_paths:
        props["fullTextPolicy"] = {"fullTextPaths": [{"path": p} for p in fts_paths]}
    if vectors:
        props["vectorEmbeddingPolicy"] = {"vectorEmbeddings": vectors}
    return props


class _FakeContainer:
    def __init__(self, props: dict[str, Any]) -> None:
        self._props = props
        self.reads = 0

        class _Conn:
            last_response_headers = {"etag": "W/\"1\""}

        self.client_connection = _Conn()

    def read(self) -> dict[str, Any]:
        self.reads += 1
        return self._props


class _FakeDatabase:
    def __init__(self, containers: dict[str, _FakeContainer]) -> None:
        self._containers = containers

    def get_container_client(self, name: str) -> _FakeContainer:
        return self._containers[name]

    def list_containers(self) -> list[dict[str, str]]:
        return [{"id": n} for n in self._containers]


class _FakeClient:
    def __init__(self, dbs: dict[str, _FakeDatabase]) -> None:
        self._dbs = dbs

    def get_database_client(self, name: str) -> _FakeDatabase:
        return self._dbs[name]

    def list_databases(self) -> list[dict[str, str]]:
        return [{"id": n} for n in self._dbs]


class _FakeConnection:
    def __init__(self, client: _FakeClient) -> None:
        self._client = client

    def client(self) -> _FakeClient:
        return self._client


def _catalog(scenarios: dict[str, dict[str, Any]], **kw: Any) -> ResourceCatalog:
    containers = {name: _FakeContainer(props) for name, props in scenarios.items()}
    client = _FakeClient({"db": _FakeDatabase(containers)})
    return ResourceCatalog(_FakeConnection(client), **kw)


# ---- capability scenarios (7-10) -------------------------------------------

def test_text_only_container() -> None:
    p = CapabilityProfiler().profile(
        parse_container_metadata("db", "c", _props(fts_paths=["/text"]))
    )
    assert p.can_full_text.value is True
    assert p.can_vector.value is False
    assert p.can_native_hybrid.value is False
    assert p.recommended_strategies == ["full_text", "item_lookup"]


def test_vector_only_container() -> None:
    p = CapabilityProfiler().profile(
        parse_container_metadata(
            "db", "c",
            _props(
                vectors=[{"path": "/embedding", "dimensions": 2560, "distanceFunction": "cosine"}],
                vector_indexes=["/embedding"],
            ),
        )
    )
    assert p.can_vector.value is True
    assert p.can_full_text.value is False
    assert p.can_native_hybrid.value is False
    assert p.vector_fields[0].dimensions == 2560


def test_vector_embedding_without_index_is_not_searchable() -> None:
    # embedding policy present but NO vector index -> capability must be False
    p = CapabilityProfiler().profile(
        parse_container_metadata(
            "db", "c",
            _props(vectors=[{"path": "/embedding", "dimensions": 2560}]),  # no vector_indexes
        )
    )
    assert p.can_vector.value is False


def test_hybrid_container() -> None:
    p = CapabilityProfiler().profile(
        parse_container_metadata(
            "db", "c",
            _props(
                fts_paths=["/text"],
                vectors=[{"path": "/embedding", "dimensions": 2560, "distanceFunction": "cosine"}],
                vector_indexes=["/embedding"],
            ),
        )
    )
    assert p.can_native_hybrid.value is True
    assert p.recommended_strategies[0] == "native_hybrid"


def test_structured_container_has_only_item_lookup() -> None:
    p = CapabilityProfiler().profile(parse_container_metadata("db", "c", _props()))
    assert p.can_full_text.value is False
    assert p.can_vector.value is False
    assert p.can_native_hybrid.value is False
    assert p.can_item_lookup.value is True
    assert p.recommended_strategies == ["item_lookup"]


# ---- discovery + catalog lifecycle -----------------------------------------

def test_discovery_lists_databases_and_containers() -> None:
    cat = _catalog({"t": _props(fts_paths=["/text"]), "s": _props()})
    assert cat.databases() == ["db"]
    assert set(cat.containers("db")) == {"t", "s"}


def test_profile_caches_and_refresh_forces_reread() -> None:
    scenarios = {"t": _props(fts_paths=["/text"])}
    containers = {n: _FakeContainer(p) for n, p in scenarios.items()}
    client = _FakeClient({"db": _FakeDatabase(containers)})
    cat = ResourceCatalog(_FakeConnection(client), ttl_seconds=1000.0)

    cat.profile("db", "t")
    cat.profile("db", "t")
    assert containers["t"].reads == 1  # second call served from cache

    cat.refresh("db", "t")
    cat.profile("db", "t")
    assert containers["t"].reads == 2  # re-read after refresh


def test_invalidate_forces_reread() -> None:
    scenarios = {"t": _props(fts_paths=["/text"])}
    containers = {n: _FakeContainer(p) for n, p in scenarios.items()}
    cat = ResourceCatalog(_FakeConnection(_FakeClient({"db": _FakeDatabase(containers)})))
    cat.profile("db", "t")
    cat.invalidate("db", "t")
    cat.profile("db", "t")
    assert containers["t"].reads == 2


def test_bounded_cache_evicts() -> None:
    scenarios = {f"c{i}": _props() for i in range(5)}
    cat = _catalog(scenarios, max_entries=2)
    for n in scenarios:
        cat.profile("db", n)
    assert cat.cached_container_count() == 2


def _run_all() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
