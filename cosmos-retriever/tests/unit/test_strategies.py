"""Exhaustive tests for `cosmos_retriever.retrieval.strategies`.

Each strategy is a thin orchestrator: resolve fields -> decide cross-partition
-> compile -> execute -> normalize. Tests isolate that wiring by faking the
schema / compiler / executor / policy and patching ``strategies.normalize_rows``
with a recorder, so every ``compile_*`` argument and every ``normalize_rows``
argument (strategy name, channels, projected_aliases, queried_text_fields) is
asserted without Cosmos. ClientSideFusion's RRF math is checked against real
RetrievedItem instances; grep's all-stopword short-circuit is verified to touch
no compiler/executor.
"""
from __future__ import annotations

import pytest

from cosmos_retriever.retrieval import strategies as strat_mod
from cosmos_retriever.retrieval.errors import (
    CrossPartitionQueryDisabled,
    UnboundedScanRejected,
)
from cosmos_retriever.retrieval.models import GrepRequest, RetrievedItem, SearchRequest
from cosmos_retriever.retrieval.strategies import (
    BoundedScanStrategy,
    ClientSideFusionStrategy,
    FullTextGrepCandidateStrategy,
    FullTextSearchStrategy,
    GrepCandidateStrategy,
    NativeHybridStrategy,
    RetrievalContext,
    SearchStrategy,
    VectorSearchStrategy,
    _resolve_cross_partition,
)

# ────────────────────────────── fakes ─────────────────────────────────────


class FakeSchema:
    def __init__(self, vec="VEC_PATH", text=("T1", "T2")):
        self.vec = vec
        self.text = list(text)
        self.vector_calls: list = []
        self.text_calls: list = []

    def resolve_vector_field(self, name):
        self.vector_calls.append(name)
        return self.vec

    def resolve_text_fields(self, names):
        self.text_calls.append(names)
        return self.text


class FakeCompiled:
    def __init__(self, aliases="ALIASES"):
        self.projected_aliases = aliases
        self.warnings: list[str] = []


class FakeCompiler:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.compiled: list[FakeCompiled] = []

    def _mk(self, method: str, kwargs: dict) -> FakeCompiled:
        c = FakeCompiled()
        self.calls.append((method, kwargs))
        self.compiled.append(c)
        return c

    def compile_hybrid(self, **kw):
        return self._mk("hybrid", kw)

    def compile_vector(self, **kw):
        return self._mk("vector", kw)

    def compile_full_text(self, **kw):
        return self._mk("full_text", kw)

    def compile_structured(self, **kw):
        return self._mk("structured", kw)


class FakeExecutor:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else [{"row": 1}]
        self.ran: list = []

    def run(self, compiled):
        self.ran.append(compiled)
        return self.rows


class FakePolicy:
    def __init__(self, cross=True, bounded=True):
        self.allow_cross_partition_search = cross
        self.allow_bounded_scan = bounded


class FakeNormalize:
    def __init__(self):
        self.calls: list[tuple] = []
        self.by_strategy: dict[str, list] = {}
        self.default: list = []

    def __call__(self, rows, **kwargs):
        self.calls.append((rows, kwargs))
        return self.by_strategy.get(kwargs.get("strategy"), self.default)


@pytest.fixture
def norm(monkeypatch) -> FakeNormalize:
    fake = FakeNormalize()
    monkeypatch.setattr(strat_mod, "normalize_rows", fake)
    return fake


def _ctx(schema=None, compiler=None, executor=None, policy=None) -> RetrievalContext:
    return RetrievalContext(
        schema=schema or FakeSchema(),
        compiler=compiler or FakeCompiler(),
        executor=executor or FakeExecutor(),
        capabilities=None,  # unused by execute
        policy=policy or FakePolicy(),
    )


def _req(**kw) -> SearchRequest:
    base = dict(query="q", limit=10)
    base.update(kw)
    return SearchRequest(**base)


# ═══════════════════════ _resolve_cross_partition ═════════════════════════


def test_cross_partition_with_key_is_false() -> None:
    assert _resolve_cross_partition("pk", FakePolicy(cross=False)) is False


def test_cross_partition_none_allowed_true() -> None:
    assert _resolve_cross_partition(None, FakePolicy(cross=True)) is True


def test_cross_partition_none_disallowed_raises() -> None:
    with pytest.raises(CrossPartitionQueryDisabled):
        _resolve_cross_partition(None, FakePolicy(cross=False))


# ═══════════════════════ base / class attributes ══════════════════════════


def test_search_strategy_is_abstract() -> None:
    with pytest.raises(TypeError):
        SearchStrategy()  # type: ignore[abstract]


def test_grep_strategy_is_abstract() -> None:
    with pytest.raises(TypeError):
        GrepCandidateStrategy()  # type: ignore[abstract]


def test_strategy_names_and_embedding_flags() -> None:
    assert (NativeHybridStrategy.name, NativeHybridStrategy.requires_embedding) == (
        "native_hybrid", True)
    assert (VectorSearchStrategy.name, VectorSearchStrategy.requires_embedding) == (
        "vector", True)
    assert (FullTextSearchStrategy.name, FullTextSearchStrategy.requires_embedding) == (
        "full_text", False)
    assert (ClientSideFusionStrategy.name, ClientSideFusionStrategy.requires_embedding) == (
        "client_fusion", True)
    assert ClientSideFusionStrategy._RRF_K == 60
    assert (BoundedScanStrategy.name, BoundedScanStrategy.requires_embedding) == (
        "bounded_scan", False)


# ═══════════════════════ NativeHybridStrategy ═════════════════════════════


def test_native_hybrid_execute_wiring(norm) -> None:
    schema, compiler, executor = FakeSchema(), FakeCompiler(), FakeExecutor()
    ctx = _ctx(schema, compiler, executor)
    norm.default = ["RESULT"]
    req = _req(query="find", query_vector=[0.1], vector_field="vf",
               text_fields=["a"], ignored_item_ids=["x"], limit=5)
    out = NativeHybridStrategy().execute(req, ctx)

    assert out == ["RESULT"]
    assert schema.vector_calls == ["vf"]
    assert schema.text_calls == [["a"]]
    method, kw = compiler.calls[0]
    assert method == "hybrid"
    assert kw == {
        "query": "find", "query_vector": [0.1], "limit": 5,
        "ignored_item_ids": ["x"], "filters": [], "partition_key": None,
        "cross_partition": True, "vector_path": "VEC_PATH", "text_paths": ["T1", "T2"],
    }
    _rows, nkw = norm.calls[0]
    assert nkw["strategy"] == "native_hybrid"
    assert nkw["channels"] == ["vector", "full_text"]
    assert nkw["projected_aliases"] == "ALIASES"
    assert nkw["queried_text_fields"] == ["a"]


def test_native_hybrid_none_query_vector_becomes_empty(norm) -> None:
    compiler = FakeCompiler()
    NativeHybridStrategy().execute(_req(query_vector=None), _ctx(compiler=compiler))
    assert compiler.calls[0][1]["query_vector"] == []


# ═══════════════════════ VectorSearchStrategy ═════════════════════════════


def test_vector_execute_wiring(norm) -> None:
    schema, compiler = FakeSchema(), FakeCompiler()
    ctx = _ctx(schema, compiler)
    VectorSearchStrategy().execute(_req(query_vector=[1.0], vector_field="vf"), ctx)
    assert schema.vector_calls == ["vf"]
    assert schema.text_calls == []  # vector never resolves text fields
    method, kw = compiler.calls[0]
    assert method == "vector"
    assert kw["vector_path"] == "VEC_PATH" and kw["query_vector"] == [1.0]
    nkw = norm.calls[0][1]
    assert nkw["strategy"] == "vector"
    assert nkw["channels"] == ["vector"]
    assert "queried_text_fields" not in nkw  # vector omits it


def test_vector_none_query_vector_becomes_empty(norm) -> None:
    compiler = FakeCompiler()
    VectorSearchStrategy().execute(_req(query_vector=None), _ctx(compiler=compiler))
    assert compiler.calls[0][1]["query_vector"] == []


# ═══════════════════════ FullTextSearchStrategy ═══════════════════════════


def test_full_text_execute_wiring(norm) -> None:
    schema, compiler = FakeSchema(), FakeCompiler()
    ctx = _ctx(schema, compiler)
    FullTextSearchStrategy().execute(_req(query="hello", text_fields=["body"]), ctx)
    assert schema.text_calls == [["body"]]
    method, kw = compiler.calls[0]
    assert method == "full_text"
    assert kw["query"] == "hello" and kw["text_paths"] == ["T1", "T2"]
    nkw = norm.calls[0][1]
    assert nkw["strategy"] == "full_text"
    assert nkw["channels"] == ["full_text"]
    assert nkw["queried_text_fields"] == ["body"]


def test_full_text_cross_partition_false_with_partition_key(norm) -> None:
    compiler = FakeCompiler()
    FullTextSearchStrategy().execute(_req(partition_key="pk"), _ctx(compiler=compiler))
    assert compiler.calls[0][1]["cross_partition"] is False


def test_full_text_cross_partition_disabled_raises() -> None:
    with pytest.raises(CrossPartitionQueryDisabled):
        FullTextSearchStrategy().execute(_req(), _ctx(policy=FakePolicy(cross=False)))


# ═══════════════════════ ClientSideFusionStrategy ═════════════════════════


def _fusion_ctx(norm, vector_hits, fts_hits):
    norm.by_strategy = {"vector": vector_hits, "full_text": fts_hits}
    return _ctx()


def test_client_fusion_rrf_ranking_and_metadata(norm) -> None:
    vhits = [RetrievedItem(item_id="a", text="va"),
             RetrievedItem(item_id="b", text="vb_vector")]
    fhits = [RetrievedItem(item_id="b", text="vb_fts"),
             RetrievedItem(item_id="c", text="vc")]
    out = ClientSideFusionStrategy().execute(_req(limit=10), _fusion_ctx(norm, vhits, fhits))

    assert [r.item_id for r in out] == ["b", "a", "c"]  # b highest (in both)
    assert [r.rank for r in out] == [0, 1, 2]
    assert all(r.retrieval_strategy == "client_fusion" for r in out)
    assert out[0].retrieval_channels == ["vector", "full_text"]
    assert out[1].retrieval_channels == ["vector"]
    assert out[2].retrieval_channels == ["full_text"]
    # setdefault keeps the first (vector) instance for the shared id
    assert out[0].text == "vb_vector"
    # RRF scores: b = 1/61 + 1/60, a = 1/60, c = 1/61
    assert out[0].raw_scores["rrf"] == pytest.approx(1 / 61 + 1 / 60)
    assert out[1].raw_scores["rrf"] == pytest.approx(1 / 60)
    assert out[2].raw_scores["rrf"] == pytest.approx(1 / 61)


def test_client_fusion_truncates_to_limit(norm) -> None:
    vhits = [RetrievedItem(item_id="a"), RetrievedItem(item_id="b")]
    fhits = [RetrievedItem(item_id="b"), RetrievedItem(item_id="c")]
    out = ClientSideFusionStrategy().execute(_req(limit=2), _fusion_ctx(norm, vhits, fhits))
    assert [r.item_id for r in out] == ["b", "a"]


def test_client_fusion_empty_inputs(norm) -> None:
    assert ClientSideFusionStrategy().execute(_req(), _fusion_ctx(norm, [], [])) == []


# ═══════════════════════ BoundedScanStrategy ══════════════════════════════


def test_bounded_scan_disabled_raises() -> None:
    with pytest.raises(UnboundedScanRejected):
        BoundedScanStrategy().execute(_req(), _ctx(policy=FakePolicy(bounded=False)))


def test_bounded_scan_execute_wiring(norm) -> None:
    compiler, executor = FakeCompiler(), FakeExecutor()
    ctx = _ctx(compiler=compiler, executor=executor)
    BoundedScanStrategy().execute(_req(limit=7, ignored_item_ids=["z"]), ctx)
    method, kw = compiler.calls[0]
    assert method == "structured"
    assert kw == {
        "limit": 7, "filters": [], "ignored_item_ids": ["z"],
        "partition_key": None, "cross_partition": True,
    }
    assert compiler.compiled[0].warnings == ["bounded scan active"]
    nkw = norm.calls[0][1]
    assert nkw["strategy"] == "bounded_scan"
    assert "channels" not in nkw
    assert "queried_text_fields" not in nkw


# ═══════════════════════ FullTextGrepCandidateStrategy ════════════════════


def test_grep_all_stopword_pattern_short_circuits(norm) -> None:
    compiler, executor = FakeCompiler(), FakeExecutor()
    ctx = _ctx(compiler=compiler, executor=executor)
    out = FullTextGrepCandidateStrategy().candidates(GrepRequest(pattern="the and of"), ctx)
    assert out == []
    assert compiler.calls == []  # never compiled
    assert executor.ran == []  # never executed


def test_grep_empty_pattern_short_circuits(norm) -> None:
    compiler = FakeCompiler()
    out = FullTextGrepCandidateStrategy().candidates(
        GrepRequest(pattern="!!! ???"), _ctx(compiler=compiler)
    )
    assert out == []
    assert compiler.calls == []


def test_grep_execute_wiring_with_field(norm) -> None:
    schema, compiler = FakeSchema(), FakeCompiler()
    ctx = _ctx(schema, compiler)
    norm.default = ["G"]
    req = GrepRequest(pattern="machine learning", text_field="body", candidate_limit=25)
    out = FullTextGrepCandidateStrategy().candidates(req, ctx)

    assert out == ["G"]
    assert schema.text_calls == [["body"]]
    method, kw = compiler.calls[0]
    assert method == "full_text"
    assert kw["query"] == "machine learning"
    assert kw["limit"] == 25
    assert kw["ignored_item_ids"] == []  # grep never carries ignored ids
    assert kw["strategy"] == "grep_full_text"
    nkw = norm.calls[0][1]
    assert nkw["strategy"] == "grep_full_text"
    assert nkw["channels"] == ["full_text"]
    assert nkw["queried_text_fields"] == ["body"]


def test_grep_without_field_resolves_none(norm) -> None:
    schema, compiler = FakeSchema(), FakeCompiler()
    FullTextGrepCandidateStrategy().candidates(
        GrepRequest(pattern="hello world"), _ctx(schema, compiler)
    )
    assert schema.text_calls == [None]
    assert norm.calls[0][1]["queried_text_fields"] is None
