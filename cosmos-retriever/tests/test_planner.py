"""Exhaustive tests for `cosmos_retriever.retrieval.planner`.

RetrievalPlanner only *decides*: it inspects schema + capabilities (+ policy)
and returns a strategy class. Tests fake the schema and capabilities to drive
_vector_ok / _fts_ok through every branch, and drive plan_search by overriding
those two helpers on the instance so the mode/auto cascade is checked in
isolation. No Cosmos / network.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from cosmos_retriever.retrieval.capabilities import SupportLevel
from cosmos_retriever.retrieval.errors import UnsupportedRetrievalCapability
from cosmos_retriever.retrieval.models import GrepRequest, SearchRequest
from cosmos_retriever.retrieval.planner import RetrievalPlanner
from cosmos_retriever.retrieval.strategies import (
    BoundedScanStrategy,
    ClientSideFusionStrategy,
    FullTextGrepCandidateStrategy,
    FullTextSearchStrategy,
    NativeHybridStrategy,
    VectorSearchStrategy,
)

# ────────────────────────────── fakes ─────────────────────────────────────


class FakeField:
    def __init__(self, path="P", dimensions=128):
        self.path = path
        self.dimensions = dimensions


class FakeCap:
    def __init__(self, support=SupportLevel.INDEXED, dimensions=128):
        self.support = support
        self.dimensions = dimensions


class FakeSchema:
    def __init__(self, vector_fields=("v",), text_paths=("t",),
                 field=None, resolve_vec_error=False,
                 resolve_text_error=False, text_paths_resolved=None):
        self.vector_fields = list(vector_fields)
        self.text_paths = list(text_paths)
        self._field = field if field is not None else FakeField()
        self._resolve_vec_error = resolve_vec_error
        self._resolve_text_error = resolve_text_error
        self._text_paths_resolved = text_paths_resolved or ["tp1"]
        self.vector_calls: list = []
        self.text_calls: list = []

    def resolve_vector_config(self, name):
        self.vector_calls.append(name)
        if self._resolve_vec_error:
            raise ValueError("bad vector field")
        return self._field

    def resolve_text_fields(self, names):
        self.text_calls.append(names)
        if self._resolve_text_error:
            raise ValueError("bad text field")
        return self._text_paths_resolved


class FakeCapabilities:
    def __init__(self, vector_supported=True, full_text_supported=True,
                 native_hybrid_supported=False, cap=None, fts_paths=None):
        self.vector_supported = vector_supported
        self.full_text_supported = full_text_supported
        self.native_hybrid_supported = native_hybrid_supported
        self._cap = cap if cap is not None else FakeCap()
        self._fts_paths = fts_paths  # None -> every path has FTS; else a set

    def vector_capability_for(self, path):
        return self._cap

    def has_full_text_path(self, path):
        if self._fts_paths is None:
            return True
        return path in self._fts_paths


def _planner(schema=None, caps=None, bounded=False):
    return RetrievalPlanner(
        schema or FakeSchema(),
        caps or FakeCapabilities(),
        SimpleNamespace(allow_bounded_scan=bounded),
    )


def _req(**kw) -> SearchRequest:
    base = dict(query="q")
    base.update(kw)
    return SearchRequest(**base)


# ═══════════════════════════════ _vector_ok ═══════════════════════════════


def test_vector_ok_false_when_no_vector_fields() -> None:
    p = _planner(FakeSchema(vector_fields=()))
    assert p._vector_ok(_req()) is False


def test_vector_ok_false_when_capability_disabled() -> None:
    p = _planner(caps=FakeCapabilities(vector_supported=False))
    assert p._vector_ok(_req()) is False


def test_vector_ok_false_when_resolve_raises() -> None:
    p = _planner(FakeSchema(resolve_vec_error=True))
    assert p._vector_ok(_req()) is False


def test_vector_ok_false_when_cap_missing() -> None:
    p = _planner()
    p.capabilities.vector_capability_for = lambda path: None
    assert p._vector_ok(_req()) is False


@pytest.mark.parametrize("support", [SupportLevel.UNSUPPORTED, SupportLevel.UNKNOWN])
def test_vector_ok_false_for_weak_support(support) -> None:
    p = _planner(caps=FakeCapabilities(cap=FakeCap(support=support)))
    assert p._vector_ok(_req()) is False


def test_vector_ok_false_on_dimension_mismatch() -> None:
    schema = FakeSchema(field=FakeField(dimensions=128))
    caps = FakeCapabilities(cap=FakeCap(dimensions=256))
    assert _planner(schema, caps)._vector_ok(_req()) is False


def test_vector_ok_true_when_all_aligned() -> None:
    schema = FakeSchema(field=FakeField(path="P", dimensions=128))
    caps = FakeCapabilities(cap=FakeCap(support=SupportLevel.INDEXED, dimensions=128))
    assert _planner(schema, caps)._vector_ok(_req()) is True


def test_vector_ok_forwards_requested_field_name() -> None:
    schema = FakeSchema()
    _planner(schema)._vector_ok(_req(vector_field="myvec"))
    assert schema.vector_calls == ["myvec"]


def test_vector_ok_none_request_uses_none_name() -> None:
    schema = FakeSchema()
    _planner(schema)._vector_ok(None)
    assert schema.vector_calls == [None]


# ═══════════════════════════════ _fts_ok ══════════════════════════════════


def test_fts_ok_false_when_capability_disabled() -> None:
    p = _planner(caps=FakeCapabilities(full_text_supported=False))
    assert p._fts_ok(_req()) is False


def test_fts_ok_no_names_true_if_any_text_path_has_fts() -> None:
    schema = FakeSchema(text_paths=("a", "b"))
    caps = FakeCapabilities(fts_paths={"b"})
    assert _planner(schema, caps)._fts_ok(_req()) is True


def test_fts_ok_no_names_false_if_no_text_path_has_fts() -> None:
    schema = FakeSchema(text_paths=("a", "b"))
    caps = FakeCapabilities(fts_paths=set())
    assert _planner(schema, caps)._fts_ok(_req()) is False


def test_fts_ok_no_names_false_when_no_text_paths() -> None:
    assert _planner(FakeSchema(text_paths=()))._fts_ok(_req()) is False


def test_fts_ok_named_fields_resolve_error_false() -> None:
    p = _planner(FakeSchema(resolve_text_error=True))
    assert p._fts_ok(_req(text_fields=["x"])) is False


def test_fts_ok_named_fields_all_have_fts_true() -> None:
    schema = FakeSchema(text_paths_resolved=["p1", "p2"])
    caps = FakeCapabilities(fts_paths={"p1", "p2"})
    assert _planner(schema, caps)._fts_ok(_req(text_fields=["a", "b"])) is True


def test_fts_ok_named_fields_missing_one_false() -> None:
    schema = FakeSchema(text_paths_resolved=["p1", "p2"])
    caps = FakeCapabilities(fts_paths={"p1"})  # p2 lacks FTS
    assert _planner(schema, caps)._fts_ok(_req(text_fields=["a", "b"])) is False


# ═══════════════════════════════ plan_search: explicit modes ══════════════


def _p(vector_ok, fts_ok, native=False, bounded=False):
    p = _planner(caps=FakeCapabilities(native_hybrid_supported=native), bounded=bounded)
    p._vector_ok = lambda req=None: vector_ok  # type: ignore[assignment]
    p._fts_ok = lambda req=None: fts_ok  # type: ignore[assignment]
    return p


def test_plan_search_vector_mode_ok() -> None:
    assert isinstance(_p(True, False).plan_search(_req(mode="vector")), VectorSearchStrategy)


def test_plan_search_vector_mode_unavailable_raises() -> None:
    with pytest.raises(UnsupportedRetrievalCapability):
        _p(False, True).plan_search(_req(mode="vector"))


def test_plan_search_text_mode_ok() -> None:
    assert isinstance(_p(False, True).plan_search(_req(mode="text")), FullTextSearchStrategy)


def test_plan_search_text_mode_unavailable_raises() -> None:
    with pytest.raises(UnsupportedRetrievalCapability):
        _p(True, False).plan_search(_req(mode="text"))


def test_plan_search_hybrid_native() -> None:
    assert isinstance(
        _p(True, True, native=True).plan_search(_req(mode="hybrid")), NativeHybridStrategy)


def test_plan_search_hybrid_client_fusion_when_no_native() -> None:
    assert isinstance(
        _p(True, True, native=False).plan_search(_req(mode="hybrid")), ClientSideFusionStrategy)


@pytest.mark.parametrize("v,f", [(True, False), (False, True), (False, False)])
def test_plan_search_hybrid_missing_side_raises(v: bool, f: bool) -> None:
    with pytest.raises(UnsupportedRetrievalCapability):
        _p(v, f).plan_search(_req(mode="hybrid"))


# ═══════════════════════════════ plan_search: auto cascade ════════════════


def test_auto_prefers_native_hybrid() -> None:
    assert isinstance(_p(True, True, native=True).plan_search(_req()), NativeHybridStrategy)


def test_auto_client_fusion_when_no_native() -> None:
    assert isinstance(_p(True, True, native=False).plan_search(_req()), ClientSideFusionStrategy)


def test_auto_vector_only() -> None:
    assert isinstance(_p(True, False).plan_search(_req()), VectorSearchStrategy)


def test_auto_full_text_only() -> None:
    assert isinstance(_p(False, True).plan_search(_req()), FullTextSearchStrategy)


def test_auto_bounded_scan_when_nothing_and_allowed() -> None:
    assert isinstance(_p(False, False, bounded=True).plan_search(_req()), BoundedScanStrategy)


def test_auto_raises_when_nothing_and_scan_disallowed() -> None:
    with pytest.raises(UnsupportedRetrievalCapability):
        _p(False, False, bounded=False).plan_search(_req())


# ═══════════════════════════════ plan_grep ════════════════════════════════


def test_plan_grep_returns_full_text_candidate() -> None:
    p = _planner(caps=FakeCapabilities(full_text_supported=True))
    assert isinstance(p.plan_grep(GrepRequest(pattern="x")), FullTextGrepCandidateStrategy)


def test_plan_grep_raises_without_full_text() -> None:
    p = _planner(caps=FakeCapabilities(full_text_supported=False))
    with pytest.raises(UnsupportedRetrievalCapability):
        p.plan_grep(GrepRequest(pattern="x"))
