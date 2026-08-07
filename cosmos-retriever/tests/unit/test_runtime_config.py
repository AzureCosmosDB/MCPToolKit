from __future__ import annotations

import asyncio

from cosmos_retriever.config import RetrieverSettings, RuntimeConfig
from cosmos_retriever.server import _RetrieverPool


def _settings() -> RetrieverSettings:
    return RetrieverSettings(
        account_uri="https://x.documents.azure.com:443/",
        cosmos_database="db",
        cosmos_corpus_container="corpus",
    )


def test_apply_structural_overrides_produces_new_settings() -> None:
    s = _settings()
    rc = RuntimeConfig(
        inference_backend="openai_chat",
        chat_base_url="http://chat/v1",
        chat_api_key="secret123",
        chat_model="my-model",
        openai_api_key="embkey",
        openai_embedding_model="emb-model",
        embed_endpoint="http://embed/v1",
        embed_query_instruction="do the thing",
        account_uri="https://acct.documents.azure.com:443/",
        schema_override={"document_id_path": "/docid", "use_dunder_codec": True},
        search_display_limit=7,
    )
    eff = s.apply_structural_overrides(rc)
    assert eff.inference_backend == "openai_chat"
    assert eff.chat_base_url == "http://chat/v1"
    assert eff.chat_api_key.get_secret_value() == "secret123"
    assert eff.chat_model == "my-model"
    assert eff.openai_api_key.get_secret_value() == "embkey"
    assert eff.openai_embedding_model == "emb-model"
    assert eff.embed_endpoint == "http://embed/v1"
    assert eff.account_uri == "https://acct.documents.azure.com:443/"
    assert eff.cosmos_retriever_schema_override is not None
    assert str(eff.cosmos_retriever_schema_override.document_id_path) == "/docid"
    assert eff.cosmos_retriever_schema_override.use_dunder_codec is True
    assert eff.cosmos_retriever_search_display_limit == 7
    # base is untouched
    assert s.chat_model is None and s.inference_backend == "openai_responses"


def test_apply_none_returns_same_object() -> None:
    s = _settings()
    assert s.apply_structural_overrides(None) is s


def test_structural_key_ignores_execution_fields() -> None:
    a = RuntimeConfig(chat_model="m", chat_max_turns=1, chat_temperature=0.1, max_documents=5)
    b = RuntimeConfig(chat_model="m", chat_max_turns=999, chat_temperature=1.9, max_documents=30)
    assert a.structural_key() == b.structural_key()


def test_structural_key_distinguishes_structural_fields() -> None:
    a = RuntimeConfig(chat_model="m")
    b = RuntimeConfig(chat_model="other")
    assert a.structural_key() != b.structural_key()


def test_structural_key_hashes_secrets() -> None:
    key = RuntimeConfig(chat_api_key="topsecret", openai_api_key="alsosecret").structural_key()
    flat = str(key)
    assert "topsecret" not in flat and "alsosecret" not in flat


def test_validators_and_extra_forbid() -> None:
    for kwargs in (
        {"inference_backend": "bogus"},
        {"schema_override": "weird"},
        {"unknown_field": 1},
    ):
        try:
            RuntimeConfig(**kwargs)
        except Exception:
            continue
        raise AssertionError(f"expected validation error for {kwargs}")


def test_pool_shares_retriever_for_execution_only_overrides() -> None:
    pool = _RetrieverPool(_settings())
    builds = {"n": 0}

    def fake_build(scope, overrides):
        builds["n"] += 1
        return object()

    pool._build = fake_build  # type: ignore[method-assign]

    async def run() -> None:
        r1, _ = await pool.get(None, None, RuntimeConfig(chat_max_turns=5))
        r2, _ = await pool.get(None, None, RuntimeConfig(chat_max_turns=99))
        assert r1 is r2

    asyncio.run(run())
    assert builds["n"] == 1


def test_pool_rebuilds_for_structural_overrides() -> None:
    pool = _RetrieverPool(_settings())
    builds = {"n": 0}

    def fake_build(scope, overrides):
        builds["n"] += 1
        return object()

    pool._build = fake_build  # type: ignore[method-assign]

    async def run() -> None:
        await pool.get(None, None, RuntimeConfig(chat_model="a"))
        await pool.get(None, None, RuntimeConfig(chat_model="b"))
        await pool.get(None, None, None)

    asyncio.run(run())
    assert builds["n"] == 3


def _run_all() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except BaseException as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
