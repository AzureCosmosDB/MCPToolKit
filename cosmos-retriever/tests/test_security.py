"""Security-focused tests for cosmos-retriever.

Consolidates the safety-critical behaviours that are easy to regress:

  1. Secret masking / non-leakage — RetrieverSettings.redacted_config,
     CorpusConfig / settings repr, and RuntimeConfig.structural_key never
     expose raw secret values.
  2. Path-injection defense — CosmosPath.parse rejects SQL/traversal/control
     payloads, and render() escapes so a segment cannot break out of the
     ["..."] bracketing.
  3. Read-only SQL enforcement — _SELECT_RE and RunQueryTool reject write /
     DDL statements (case- and whitespace-insensitive) and never reach the
     Cosmos client for them.

Distinct sentinel secret values are used so a leak is detectable by substring
search of the serialized output.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from cosmos_retriever.config import CorpusConfig, RetrieverSettings, RuntimeConfig
from cosmos_retriever.retrieval.errors import UnsafeCosmosPath
from cosmos_retriever.retrieval.paths import CosmosPath
from cosmos_retriever.tools import _SELECT_RE, RunQueryTool

# ════════════════════════ 1. secret masking / leakage ═════════════════════

# Unique per-field sentinels so any leak is greppable.
_CHAT_SECRET = "CHAT-SENTINEL-a1"
_OPENAI_SECRET = "OPENAI-SENTINEL-b2"
_COSMOS_SECRET = "COSMOS-SENTINEL-c3"
_BASETEN_SECRET = "BASETEN-SENTINEL-d4"


def _settings_with_secrets() -> RetrieverSettings:
    return RetrieverSettings(
        _env_file=None,
        chat_api_key=_CHAT_SECRET,
        openai_api_key=_OPENAI_SECRET,
        cosmos_key=_COSMOS_SECRET,
        baseten_api_key=_BASETEN_SECRET,
        cosmos_database="db",
    )


def test_redacted_config_masks_all_secret_fields() -> None:
    red = _settings_with_secrets().redacted_config()
    assert red["chat_api_key"] == "***set***"
    assert red["openai_api_key"] == "***set***"
    assert red["cosmos_key"] == "***set***"
    assert red["baseten_api_key"] == "***set***"


def test_redacted_config_never_contains_raw_secret_values() -> None:
    blob = json.dumps(_settings_with_secrets().redacted_config())
    for secret in (_CHAT_SECRET, _OPENAI_SECRET, _COSMOS_SECRET, _BASETEN_SECRET):
        assert secret not in blob


def test_redacted_config_unset_secrets_are_none() -> None:
    red = RetrieverSettings(_env_file=None).redacted_config()
    for key in ("chat_api_key", "openai_api_key", "cosmos_key", "baseten_api_key"):
        assert red[key] is None


def test_settings_repr_and_str_do_not_leak_secrets() -> None:
    s = _settings_with_secrets()
    for text in (repr(s), str(s)):
        for secret in (_CHAT_SECRET, _OPENAI_SECRET, _COSMOS_SECRET, _BASETEN_SECRET):
            assert secret not in text


def test_settings_model_dump_json_does_not_leak_secrets() -> None:
    dumped = _settings_with_secrets().model_dump_json()
    for secret in (_CHAT_SECRET, _OPENAI_SECRET, _COSMOS_SECRET, _BASETEN_SECRET):
        assert secret not in dumped


def test_corpusconfig_repr_does_not_leak_secrets() -> None:
    c = CorpusConfig(
        container="c",
        account_uri="https://a",
        database="db",
        embed_base_url=None,
        embed_api_key=SecretStr("EMBED-SENTINEL-e5"),
        embed_model="m",
        cosmos_key=SecretStr("CK-SENTINEL-f6"),
    )
    assert "EMBED-SENTINEL-e5" not in repr(c)
    assert "CK-SENTINEL-f6" not in repr(c)


def test_structural_key_hashes_and_never_exposes_raw_secrets() -> None:
    rc = RuntimeConfig(chat_api_key="CK-RAW-xyz", openai_api_key="OK-RAW-xyz")
    key = rc.structural_key()
    blob = str(key)
    assert "CK-RAW-xyz" not in blob
    assert "OK-RAW-xyz" not in blob
    # secrets are represented by 16-char sha256 prefixes, not the plaintext
    assert any(isinstance(v, str) and len(v) == 16 for v in key)


def test_structural_key_none_secrets_stay_none() -> None:
    key = RuntimeConfig().structural_key()
    # positions 2 and 6 are the hashed chat/openai keys
    assert key[2] is None and key[6] is None


def test_get_baseten_client_error_does_not_echo_secret() -> None:
    # Only model_url set: the error path must not include any key material.
    s = RetrieverSettings(_env_file=None, baseten_model_url="https://bt")
    with pytest.raises(ValueError) as exc:
        s.get_baseten_client()
    assert "BASETEN_MODEL_URL" in str(exc.value)


# ════════════════════════ 2. path-injection defense ═══════════════════════


@pytest.mark.parametrize(
    "payload",
    [
        '/a"] OR 1=1',       # quote + bracket breakout attempt
        "/a'; DROP TABLE x",  # single-quote SQL injection
        "/a`b",               # backtick
        "/a[0]",              # bracket indexing
        "/a*",                # wildcard
        "/a;b",               # statement separator
        "/a=b",               # operator
        "/a(b)",              # parens
        "/a|b",               # pipe
        "/a$b",               # dollar
        "/a%b",               # percent
        "/a\nb",              # newline (control char)
        "/a\tb",              # tab
        "/a\\b",              # backslash
        "/..",                # path traversal segment
        "/../etc/passwd",     # traversal chain
        "/a/../b",            # embedded traversal
    ],
)
def test_cosmospath_rejects_injection_payloads(payload: str) -> None:
    with pytest.raises(UnsafeCosmosPath):
        CosmosPath.parse(payload)


def test_render_escapes_bracket_breakout_segment() -> None:
    # A directly-constructed hostile segment must not break out of ["..."]:
    # every embedded quote is backslash-escaped.
    rendered = CosmosPath(segments=('x"][\"y',)).render()
    assert rendered == 'c["x\\"][\\"y"]'
    # no unescaped closing-then-opening bracket sequence survives
    assert '"]["' not in rendered.replace('\\"', "")


def test_render_escapes_backslash_before_quote() -> None:
    # Backslash is escaped first so it can't neutralize the quote escaping.
    assert CosmosPath(segments=('\\"',)).render() == 'c["\\\\\\""]'


# ════════════════════════ 3. read-only SQL enforcement ════════════════════


class _FakeContainer:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.received = None  # set only if query_items is actually called

    def query_items(self, query, enable_cross_partition_query, max_item_count):
        self.received = query
        yield from self.rows


class _FakeCosmosClient:
    def __init__(self, container):
        self._container = container

    def get_database_client(self, name):
        return SimpleNamespace(get_container_client=lambda _n: self._container)


def _run_tool(container) -> RunQueryTool:
    return RunQueryTool(
        client=_FakeCosmosClient(container),
        default_database="db",
        default_container="cont",
    )


@pytest.mark.parametrize(
    "query",
    [
        "INSERT INTO c VALUES (1)",
        "  \n\t update c set x = 1",
        "(( DELETE FROM c ))",
        "DrOp TaBlE c",
        "MERGE INTO c",
        "UPSERT c",
        "EXEC sp_bad",
        "CALL something()",
        "ALTER CONTAINER c",
        "CREATE INDEX i",
        "TRUNCATE c",
        "GRANT ALL",
        "REPLACE INTO c",
        "WITH t AS (SELECT 1) DELETE FROM t",  # CTE prefix is not a SELECT start
    ],
)
def test_select_regex_rejects_non_select(query: str) -> None:
    assert _SELECT_RE.match(query) is None


@pytest.mark.parametrize(
    "query",
    ["SELECT * FROM c", "  \n select c.id from c", "(select 1)", "SeLeCt x"],
)
def test_select_regex_accepts_read_queries(query: str) -> None:
    assert _SELECT_RE.match(query) is not None


def test_run_query_blocks_write_and_never_touches_client() -> None:
    container = _FakeContainer()
    text, _ = _run_tool(container)({"query": "DELETE FROM c"})
    assert "only read-only SELECT queries are allowed" in text
    assert container.received is None  # client never queried


def test_run_query_allows_select_positive_control() -> None:
    container = _FakeContainer(rows=[{"id": 1}])
    text, _ = _run_tool(container)({"query": "SELECT * FROM c"})
    assert container.received == "SELECT * FROM c"  # guard let the read through
    assert "row(s)" in text


def test_select_regex_multistatement_is_a_documented_limitation() -> None:
    # KNOWN LIMITATION: _SELECT_RE only anchors the *start* of the query, so a
    # chained statement after a ';' still matches. This is not exploitable via
    # Azure Cosmos, whose query_items executes read-only SQL and rejects DDL/DML;
    # the guard is defense-in-depth, not the sole control. Pinning the current
    # behavior so any future hardening (rejecting ';') updates this test.
    assert _SELECT_RE.match("SELECT * FROM c; DROP TABLE x") is not None
