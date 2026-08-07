"""Exhaustive tests for `cosmos_retriever.retrieval.paths`.

Covers CosmosPath.parse (validation + segment rules), render (alias +
escaping), __str__ / round-trip, frozen-model semantics (immutability,
equality, hashability), and coerce_path.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from cosmos_retriever.retrieval.errors import UnsafeCosmosPath
from cosmos_retriever.retrieval.paths import CosmosPath, coerce_path

# ═══════════════════════════ parse: identity ══════════════════════════════


def test_parse_returns_same_instance_for_cosmospath() -> None:
    p = CosmosPath.parse("/id")
    assert CosmosPath.parse(p) is p


# ═══════════════════════════ parse: type errors ═══════════════════════════


@pytest.mark.parametrize("bad", [123, None, ["/a"], b"/a", 1.5, {"a": 1}])
def test_parse_non_string_raises(bad) -> None:
    with pytest.raises(UnsafeCosmosPath, match="must be a string"):
        CosmosPath.parse(bad)


def test_parse_error_includes_type_name() -> None:
    with pytest.raises(UnsafeCosmosPath, match="got int"):
        CosmosPath.parse(5)


# ═══════════════════════════ parse: structural rules ══════════════════════


@pytest.mark.parametrize("raw", ["id", "abc", "c/d", ""])
def test_parse_requires_leading_slash(raw: str) -> None:
    with pytest.raises(UnsafeCosmosPath, match="must start with '/'"):
        CosmosPath.parse(raw)


def test_parse_bare_slash_is_empty() -> None:
    with pytest.raises(UnsafeCosmosPath, match="empty or has a trailing"):
        CosmosPath.parse("/")


@pytest.mark.parametrize("raw", ["/a/", "/id/", "/a/b/"])
def test_parse_rejects_trailing_slash(raw: str) -> None:
    with pytest.raises(UnsafeCosmosPath, match="empty or has a trailing"):
        CosmosPath.parse(raw)


def test_parse_rejects_empty_middle_segment() -> None:
    with pytest.raises(UnsafeCosmosPath, match="unsafe path segment"):
        CosmosPath.parse("/a//b")


# ═══════════════════════════ parse: segment charset ═══════════════════════


@pytest.mark.parametrize(
    "raw,segments",
    [
        ("/id", ("id",)),
        ("/a/b/c", ("a", "b", "c")),
        ("/_id", ("_id",)),
        ("/A_b.c-d e", ("A_b.c-d e",)),  # underscore, dot, hyphen, space allowed
        ("/a1", ("a1",)),
        ("/Z", ("Z",)),
    ],
)
def test_parse_accepts_valid_paths(raw: str, segments: tuple) -> None:
    assert CosmosPath.parse(raw).segments == segments


@pytest.mark.parametrize(
    "raw",
    [
        "/1abc",   # leading digit
        "/ abc",   # leading space
        "/.hidden",  # leading dot
        "/-x",     # leading hyphen
        "/a@b",    # illegal symbol
        "/caf\u00e9",  # non-ASCII letter
        "/a/1b",   # bad segment in the middle
        "/a#",     # illegal symbol
    ],
)
def test_parse_rejects_bad_segments(raw: str) -> None:
    with pytest.raises(UnsafeCosmosPath, match="unsafe path segment"):
        CosmosPath.parse(raw)


# ═══════════════════════════════ render ═══════════════════════════════════


def test_render_default_alias() -> None:
    assert CosmosPath.parse("/a/b").render() == 'c["a"]["b"]'


def test_render_custom_alias() -> None:
    assert CosmosPath.parse("/a/b").render("x") == 'x["a"]["b"]'


def test_render_single_segment() -> None:
    assert CosmosPath.parse("/id").render() == 'c["id"]'


def test_render_escapes_quote_and_backslash() -> None:
    # Segments with quotes/backslashes can't come from parse, but render must
    # still escape them safely when a CosmosPath is built directly.
    assert CosmosPath(segments=('a"b',)).render() == 'c["a\\"b"]'
    assert CosmosPath(segments=("a\\b",)).render() == 'c["a\\\\b"]'
    assert CosmosPath(segments=('\\"',)).render() == 'c["\\\\\\""]'


# ═══════════════════════════════ __str__ / round-trip ═════════════════════


def test_str_reconstructs_path() -> None:
    assert str(CosmosPath.parse("/a/b/c")) == "/a/b/c"
    assert str(CosmosPath.parse("/id")) == "/id"


def test_parse_str_round_trip() -> None:
    p = CosmosPath.parse("/a/b.c/d e")
    assert CosmosPath.parse(str(p)) == p


# ═══════════════════════════════ model semantics ══════════════════════════


def test_frozen_cannot_mutate() -> None:
    p = CosmosPath.parse("/a")
    with pytest.raises(ValidationError):
        p.segments = ("b",)  # type: ignore[misc]


def test_equality_by_value() -> None:
    assert CosmosPath.parse("/a/b") == CosmosPath(segments=("a", "b"))
    assert CosmosPath.parse("/a") != CosmosPath.parse("/b")


def test_hashable_usable_in_set() -> None:
    s = {CosmosPath.parse("/a"), CosmosPath(segments=("a",)), CosmosPath.parse("/b")}
    assert len(s) == 2  # first two are equal -> collapse


# ═══════════════════════════════ coerce_path ══════════════════════════════


def test_coerce_path_returns_same_cosmospath() -> None:
    p = CosmosPath.parse("/a")
    assert coerce_path(p) is p


def test_coerce_path_parses_string() -> None:
    assert coerce_path("/a/b").segments == ("a", "b")


def test_coerce_path_invalid_raises() -> None:
    with pytest.raises(UnsafeCosmosPath):
        coerce_path("no-leading-slash")
