"""Exhaustive tests for the reranker module (`cosmos_retriever.rerank`).

Covers, with fakes and no network access:

  1. RerankResult             — dataclass fields / equality / mutability
  2. Reranker.__init__        — token_counter / max_tokens invariants
  3. Reranker._truncate_results — token annotation + budget truncation boundaries
  4. Reranker.__call__        — template: _rerank -> slow-warn -> truncate
  5. BasetenReranker          — classify() plumbing + yes/no label -> P("yes") score
  6. VLLMQwen3Reranker        — /score plumbing, batching, retry/backoff
  7. ContextualReranker       — /rerank plumbing, payload/headers, error propagation
  8. Module surface           — VLLMReranker alias + a latent-config-bug guard

All HTTP is intercepted by patching `rerank.requests.post`; the Baseten client
and `get_config` are replaced with fakes. `time.sleep` is patched so retry
backoff does not actually wait.
"""
from __future__ import annotations

import types

import pytest
import requests

from cosmos_retriever import rerank
from cosmos_retriever.rerank import (
    BasetenReranker,
    ContextualReranker,
    Reranker,
    RerankResult,
    VLLMQwen3Reranker,
    VLLMReranker,
)

# ───────────────────────── shared fakes / helpers ─────────────────────────

def x_counter(s: str) -> int:
    """Deterministic token counter: each 'x' character counts as one token."""
    return s.count("x") if isinstance(s, str) else 0


class _RecordLogger:
    """Captures structlog-style calls so branch coverage can assert on them."""

    def __init__(self) -> None:
        self.warnings: list[tuple] = []
        self.errors: list[tuple] = []
        self.infos: list[tuple] = []

    def warning(self, *a, **k) -> None:
        self.warnings.append((a, k))

    def error(self, *a, **k) -> None:
        self.errors.append((a, k))

    def info(self, *a, **k) -> None:
        self.infos.append((a, k))


class _StubReranker(Reranker):
    """Concrete Reranker whose `_rerank` returns a fixed, caller-supplied list.

    Used to exercise the abstract base's template (`__call__`) and truncation in
    isolation from any scoring backend. Records what `_rerank` was invoked with.
    """

    def __init__(self, results: list[RerankResult], **kw) -> None:
        super().__init__(**kw)
        self._results = results
        self.seen: list[tuple] = []

    def _rerank(self, query, documents, instruction=None):
        self.seen.append((query, list(documents), instruction))
        # Fresh copies so truncation's in-place `.tokens` writes don't leak back.
        return [
            RerankResult(document=r.document, score=r.score, original_index=r.original_index)
            for r in self._results
        ]


def _mk(doc: str, score: float, idx: int) -> RerankResult:
    return RerankResult(document=doc, score=score, original_index=idx)


# ═════════════════════════ 1. RerankResult ═════════════════════════

def test_rerankresult_defaults_tokens_none() -> None:
    r = RerankResult(document="d", score=0.5, original_index=3)
    assert r.document == "d" and r.score == 0.5 and r.original_index == 3
    assert r.tokens is None


def test_rerankresult_equality_and_token_mutation() -> None:
    a = RerankResult(document="d", score=0.5, original_index=0)
    b = RerankResult(document="d", score=0.5, original_index=0)
    assert a == b
    a.tokens = 7  # tokens is set later by _truncate_results
    assert a != b and a.tokens == 7


# ═════════════════════════ 2. Reranker.__init__ ═════════════════════════

def test_init_max_tokens_without_counter_raises() -> None:
    with pytest.raises(ValueError, match="token_counter is required"):
        _StubReranker([], max_tokens=100)


def test_init_defaults_are_none() -> None:
    r = _StubReranker([])
    assert r.token_counter is None and r.max_tokens is None


def test_init_counter_without_max_tokens_ok() -> None:
    r = _StubReranker([], token_counter=x_counter)
    assert r.token_counter is x_counter and r.max_tokens is None


def test_init_both_set_ok() -> None:
    r = _StubReranker([], token_counter=x_counter, max_tokens=50)
    assert r.token_counter is x_counter and r.max_tokens == 50


# ═════════════════════════ 3. _truncate_results ═════════════════════════

def test_truncate_sets_tokens_on_every_result_even_without_budget() -> None:
    results = [_mk("x", 1, 0), _mk("xx", 1, 1)]
    r = _StubReranker([], token_counter=x_counter)  # no max_tokens -> no truncation
    out = r._truncate_results(results)
    assert out is results  # unchanged list
    assert [res.tokens for res in results] == [1, 2]  # tokens annotated regardless


def test_truncate_no_counter_leaves_tokens_none_and_no_truncation() -> None:
    results = [_mk("x", 1, 0), _mk("xxxx", 1, 1)]
    r = _StubReranker([])  # no counter
    out = r._truncate_results(results, max_tokens=1)
    assert out == results
    assert all(res.tokens is None for res in results)


def test_truncate_boundary_equal_is_kept() -> None:
    # tokens: 1, 2, 3 ; budget 3 -> keep [1] then [1+2=3] (== not > 3, kept), drop 3rd
    results = [_mk("x", 3, 0), _mk("xx", 2, 1), _mk("xxx", 1, 2)]
    r = _StubReranker([], token_counter=x_counter, max_tokens=3)
    out = r._truncate_results(results)
    assert [res.document for res in out] == ["x", "xx"]


def test_truncate_first_doc_over_budget_yields_empty() -> None:
    results = [_mk("xxxx", 1, 0)]  # 4 tokens
    r = _StubReranker([], token_counter=x_counter, max_tokens=3)
    assert r._truncate_results(results) == []


def test_truncate_zero_budget_keeps_nothing() -> None:
    results = [_mk("x", 1, 0)]
    r = _StubReranker([], token_counter=x_counter, max_tokens=0)
    assert r._truncate_results(results) == []


def test_truncate_all_fit_keeps_all() -> None:
    results = [_mk("x", 1, 0), _mk("x", 1, 1)]
    r = _StubReranker([], token_counter=x_counter, max_tokens=100)
    out = r._truncate_results(results)
    assert len(out) == 2


def test_truncate_call_arg_overrides_instance_max() -> None:
    results = [_mk("x", 1, 0), _mk("x", 1, 1), _mk("x", 1, 2)]
    r = _StubReranker([], token_counter=x_counter, max_tokens=100)
    # call-level budget of 2 wins over the instance's 100
    out = r._truncate_results(results, max_tokens=2)
    assert len(out) == 2


def test_truncate_instance_max_used_when_call_arg_none() -> None:
    results = [_mk("x", 1, 0), _mk("x", 1, 1), _mk("x", 1, 2)]
    r = _StubReranker([], token_counter=x_counter, max_tokens=1)
    out = r._truncate_results(results, max_tokens=None)
    assert len(out) == 1


def test_truncate_dropped_results_still_annotated(monkeypatch) -> None:
    rec = _RecordLogger()
    monkeypatch.setattr(rerank, "logger", rec)
    results = [_mk("x", 2, 0), _mk("xx", 1, 1), _mk("xxx", 1, 2)]
    r = _StubReranker([], token_counter=x_counter, max_tokens=1)
    r._truncate_results(results)
    # every original result — including the dropped ones — got tokens set
    assert [res.tokens for res in results] == [1, 2, 3]
    # and a truncation log was emitted
    assert rec.infos and rec.infos[0][1]["dropped"] == 2


# ═════════════════════════ 4. Reranker.__call__ template ═════════════════════════

def test_call_threads_instruction_and_truncates() -> None:
    base = [_mk("x", 2, 0), _mk("x", 1, 1)]
    r = _StubReranker(base, token_counter=x_counter, max_tokens=1)
    out = r("the query", ["x", "x"], instruction="inst")
    # _rerank saw the instruction and documents
    assert r.seen == [("the query", ["x", "x"], "inst")]
    # truncation applied (each doc is 1 token, budget 1 -> keep 1)
    assert len(out) == 1


def test_call_passes_call_level_max_tokens() -> None:
    base = [_mk("x", 2, 0), _mk("x", 1, 1), _mk("x", 1, 2)]
    r = _StubReranker(base, token_counter=x_counter)  # no instance max
    out = r("q", ["x", "x", "x"], max_tokens=2)
    assert len(out) == 2


def test_call_slow_warning_branch(monkeypatch) -> None:
    rec = _RecordLogger()
    monkeypatch.setattr(rerank, "logger", rec)
    # perf_counter is called twice in __call__: start, then end. 0 -> 2.0s = 2000ms > 1500ms.
    seq = iter([0.0, 2.0])
    monkeypatch.setattr(rerank.time, "perf_counter", lambda: next(seq))
    r = _StubReranker([_mk("d", 1.0, 0)])
    out = r("q", ["d"])
    assert len(out) == 1
    assert rec.warnings and "slow" in rec.warnings[0][0][0].lower()


def test_call_no_warning_when_fast(monkeypatch) -> None:
    rec = _RecordLogger()
    monkeypatch.setattr(rerank, "logger", rec)
    seq = iter([0.0, 0.1])  # 100ms
    monkeypatch.setattr(rerank.time, "perf_counter", lambda: next(seq))
    r = _StubReranker([_mk("d", 1.0, 0)])
    r("q", ["d"])
    assert rec.warnings == []


# ═════════════════════════ 5. BasetenReranker ═════════════════════════

def _group(*pairs):
    """Build one document's classify group: [(label, score), ...]."""
    return [types.SimpleNamespace(label=lbl, score=score) for lbl, score in pairs]


class FakeBasetenClient:
    def __init__(self, data) -> None:
        self._data = data
        self.calls: list[dict] = []

    def classify(self, **kwargs):
        self.calls.append(kwargs)
        return types.SimpleNamespace(data=self._data)


def test_baseten_class_constants() -> None:
    assert "yes" in BasetenReranker.PREFIX and "no" in BasetenReranker.PREFIX
    assert BasetenReranker.SUFFIX.startswith("<|im_end|>")
    assert "assistant" in BasetenReranker.SUFFIX and "<think>" in BasetenReranker.SUFFIX
    assert BasetenReranker.DEFAULT_INSTRUCTION


def test_baseten_defaults() -> None:
    r = BasetenReranker(client=FakeBasetenClient([]))
    assert r.batch_size == 16 and r.max_concurrent_requests == 256 and r.timeout_s == 360


def test_baseten_uses_config_client_when_none(monkeypatch) -> None:
    sentinel = FakeBasetenClient([])
    fake_cfg = types.SimpleNamespace(get_baseten_client=lambda: sentinel)
    monkeypatch.setattr(rerank, "get_config", lambda: fake_cfg)
    r = BasetenReranker(client=None)
    assert r.client is sentinel


def test_baseten_format_input_default_instruction_exact() -> None:
    r = BasetenReranker(client=FakeBasetenClient([]))
    out = r._format_input(None, "Q?", "DOC")
    expected = (
        f"{BasetenReranker.PREFIX}<Instruct>: {BasetenReranker.DEFAULT_INSTRUCTION}\n"
        f"<Query>: Q?\n<Document>: DOC{BasetenReranker.SUFFIX}"
    )
    assert out == expected


def test_baseten_format_input_custom_instruction() -> None:
    r = BasetenReranker(client=FakeBasetenClient([]))
    out = r._format_input("CUSTOM", "Q", "D")
    assert "<Instruct>: CUSTOM" in out and "<Query>: Q" in out and "<Document>: D" in out


def test_baseten_empty_documents_no_client_call() -> None:
    client = FakeBasetenClient([])
    r = BasetenReranker(client=client)
    assert r._rerank("q", []) == []
    assert client.calls == []


def test_baseten_classify_called_with_expected_kwargs() -> None:
    client = FakeBasetenClient([_group(("yes", 0.9), ("no", 0.1))])
    r = BasetenReranker(client=client, batch_size=8, max_concurrent_requests=4, timeout_s=12)
    r._rerank("q", ["d0"], instruction="inst")
    (kwargs,) = client.calls
    assert kwargs["truncate"] is True
    assert kwargs["batch_size"] == 8
    assert kwargs["max_concurrent_requests"] == 4
    assert kwargs["timeout_s"] == 12
    assert len(kwargs["inputs"]) == 1
    assert "<Instruct>: inst" in kwargs["inputs"][0]


def test_baseten_takes_yes_probability() -> None:
    client = FakeBasetenClient([_group(("no", 0.2), ("yes", 0.8))])
    r = BasetenReranker(client=client)
    out = r._rerank("q", ["d0"])
    assert out[0].score == 0.8  # picks the "yes" entry regardless of position


def test_baseten_missing_yes_scores_zero() -> None:
    client = FakeBasetenClient([_group(("no", 0.7))])
    r = BasetenReranker(client=client)
    out = r._rerank("q", ["d0"])
    assert out[0].score == 0.0


def test_baseten_empty_group_scores_zero() -> None:
    client = FakeBasetenClient([[]])
    r = BasetenReranker(client=client)
    out = r._rerank("q", ["d0"])
    assert out[0].score == 0.0


def test_baseten_breaks_on_first_yes() -> None:
    # Two "yes" entries; the loop breaks on the first one it sees.
    client = FakeBasetenClient([_group(("yes", 0.55), ("yes", 0.99))])
    r = BasetenReranker(client=client)
    out = r._rerank("q", ["d0"])
    assert out[0].score == 0.55


def test_baseten_sorts_descending_and_preserves_original_index() -> None:
    client = FakeBasetenClient(
        [
            _group(("yes", 0.1)),  # d0
            _group(("yes", 0.9)),  # d1
            _group(("yes", 0.5)),  # d2
        ]
    )
    r = BasetenReranker(client=client)
    out = r._rerank("q", ["d0", "d1", "d2"])
    assert [x.document for x in out] == ["d1", "d2", "d0"]
    assert [x.original_index for x in out] == [1, 2, 0]
    assert [x.score for x in out] == [0.9, 0.5, 0.1]


def test_baseten_tie_scores_stable_order() -> None:
    client = FakeBasetenClient([_group(("yes", 0.5)), _group(("yes", 0.5))])
    r = BasetenReranker(client=client)
    out = r._rerank("q", ["d0", "d1"])
    # stable sort keeps original relative order on ties
    assert [x.original_index for x in out] == [0, 1]


def test_baseten_call_end_to_end_with_truncation() -> None:
    client = FakeBasetenClient([_group(("yes", 0.2)), _group(("yes", 0.9))])
    r = BasetenReranker(client=client, token_counter=x_counter, max_tokens=1)
    out = r("q", ["x", "x"])  # both 1 token; budget 1 -> keep top-1 after sort
    assert len(out) == 1 and out[0].score == 0.9 and out[0].tokens == 1


# ═════════════════════════ 6. VLLMQwen3Reranker ═════════════════════════

class FakeHTTPResponse:
    def __init__(self, payload=None, raise_exc: Exception | None = None) -> None:
        self._payload = payload
        self._raise = raise_exc

    def raise_for_status(self) -> None:
        if self._raise is not None:
            raise self._raise

    def json(self):
        return self._payload


def test_vllm_alias_is_qwen3() -> None:
    assert VLLMReranker is VLLMQwen3Reranker


def test_vllm_class_constants_and_defaults() -> None:
    r = VLLMQwen3Reranker(base_url="http://host:1/")
    assert r.model == "Qwen/Qwen3-Reranker-8B"
    assert r.batch_size == 32 and r.timeout_s == 360
    assert "yes" in r.PREFIX and r.SUFFIX.startswith("<|im_end|>")


def test_vllm_base_url_trailing_slash_stripped() -> None:
    r = VLLMQwen3Reranker(base_url="http://host:8011///")
    assert r.base_url == "http://host:8011"


def test_vllm_base_url_env_fallback(monkeypatch) -> None:
    monkeypatch.setenv("VLLM_RERANKER_URL", "http://env-host:9/")
    r = VLLMQwen3Reranker(base_url=None)
    assert r.base_url == "http://env-host:9"


def test_vllm_base_url_hard_default(monkeypatch) -> None:
    monkeypatch.delenv("VLLM_RERANKER_URL", raising=False)
    r = VLLMQwen3Reranker(base_url=None)
    assert r.base_url == "http://127.0.0.1:8011"


def test_vllm_empty_documents_no_http(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(rerank.requests, "post", lambda *a, **k: called.append(1))
    r = VLLMQwen3Reranker(base_url="http://h:1")
    assert r._rerank("q", []) == []
    assert called == []


def test_vllm_payload_and_endpoint(monkeypatch) -> None:
    captured = {}

    def fake_post(url, json=None, timeout=None):  # noqa: A002
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeHTTPResponse({"data": [{"score": 0.5}]})

    monkeypatch.setattr(rerank.requests, "post", fake_post)
    r = VLLMQwen3Reranker(base_url="http://h:8011", timeout_s=42)
    r._rerank("Q", ["DOC"], instruction="INST")
    assert captured["url"] == "http://h:8011/score"
    assert captured["timeout"] == 42
    body = captured["json"]
    assert body["model"] == "Qwen/Qwen3-Reranker-8B"
    assert body["truncate_prompt_tokens"] == -1
    assert "<Instruct>: INST" in body["text_1"] and "<Query>: Q" in body["text_1"]
    assert body["text_2"] == [f"<Document>: DOC{VLLMQwen3Reranker.SUFFIX}"]


def test_vllm_default_instruction_used(monkeypatch) -> None:
    captured = {}

    def fake_post(url, json=None, timeout=None):  # noqa: A002
        captured["json"] = json
        return FakeHTTPResponse({"data": [{"score": 0.1}]})

    monkeypatch.setattr(rerank.requests, "post", fake_post)
    r = VLLMQwen3Reranker(base_url="http://h:1")
    r._rerank("Q", ["D"])
    assert VLLMQwen3Reranker.DEFAULT_INSTRUCTION in captured["json"]["text_1"]


def test_vllm_batches_split_into_multiple_posts(monkeypatch) -> None:
    posts: list[list[str]] = []

    def fake_post(url, json=None, timeout=None):  # noqa: A002
        docs = json["text_2"]
        posts.append(docs)
        return FakeHTTPResponse({"data": [{"score": 0.0} for _ in docs]})

    monkeypatch.setattr(rerank.requests, "post", fake_post)
    r = VLLMQwen3Reranker(base_url="http://h:1", batch_size=2)
    r._rerank("q", ["a", "b", "c"])  # 3 docs, batch 2 -> 2 posts (2 + 1)
    assert len(posts) == 2
    assert len(posts[0]) == 2 and len(posts[1]) == 1


def test_vllm_scores_accumulate_in_order_and_coerce_float(monkeypatch) -> None:
    def fake_post(url, json=None, timeout=None):  # noqa: A002
        docs = json["text_2"]
        # return integer scores to verify float() coercion
        return FakeHTTPResponse({"data": [{"score": i} for i in range(len(docs))]})

    monkeypatch.setattr(rerank.requests, "post", fake_post)
    r = VLLMQwen3Reranker(base_url="http://h:1", batch_size=10)
    out = r._rerank("q", ["a", "b", "c"])
    assert all(isinstance(x.score, float) for x in out)
    # scores were 0,1,2 -> sorted desc: c(2), b(1), a(0)
    assert [x.document for x in out] == ["c", "b", "a"]
    assert [x.original_index for x in out] == [2, 1, 0]


def test_vllm_retries_then_succeeds(monkeypatch) -> None:
    rec = _RecordLogger()
    monkeypatch.setattr(rerank, "logger", rec)
    sleeps: list[float] = []
    monkeypatch.setattr(rerank.time, "sleep", lambda s: sleeps.append(s))

    calls = {"n": 0}

    def flaky_post(url, json=None, timeout=None):  # noqa: A002
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.exceptions.ConnectionError("boom")
        return FakeHTTPResponse({"data": [{"score": 0.7}]})

    monkeypatch.setattr(rerank.requests, "post", flaky_post)
    r = VLLMQwen3Reranker(base_url="http://h:1")
    out = r._rerank("q", ["d"])
    assert out[0].score == 0.7
    assert calls["n"] == 2  # one failure, one success
    assert sleeps == [1]  # backoff 2**0 before the retry
    assert rec.warnings  # retry warning logged


def test_vllm_all_retries_fail_raises(monkeypatch) -> None:
    rec = _RecordLogger()
    monkeypatch.setattr(rerank, "logger", rec)
    monkeypatch.setattr(rerank.time, "sleep", lambda s: None)

    def always_fail(url, json=None, timeout=None):  # noqa: A002
        raise requests.exceptions.Timeout("nope")

    monkeypatch.setattr(rerank.requests, "post", always_fail)
    r = VLLMQwen3Reranker(base_url="http://h:1")
    with pytest.raises(requests.exceptions.Timeout):
        r._rerank("q", ["d"])
    assert rec.errors  # failure logged after exhausting retries


def test_vllm_call_end_to_end_with_truncation(monkeypatch) -> None:
    def fake_post(url, json=None, timeout=None):  # noqa: A002
        docs = json["text_2"]
        return FakeHTTPResponse({"data": [{"score": 0.9} for _ in docs]})

    monkeypatch.setattr(rerank.requests, "post", fake_post)
    r = VLLMQwen3Reranker(base_url="http://h:1", token_counter=x_counter, max_tokens=1)
    out = r("q", ["x", "x"])
    assert len(out) == 1 and out[0].tokens == 1


# ═════════════════════════ 7. ContextualReranker ═════════════════════════

def test_contextual_class_constants() -> None:
    assert ContextualReranker.API_URL.endswith("/v1/rerank")
    assert ContextualReranker.DEFAULT_MODEL
    assert ContextualReranker.DEFAULT_INSTRUCTION


def test_contextual_defaults() -> None:
    r = ContextualReranker(api_key="k")
    assert r.model == ContextualReranker.DEFAULT_MODEL
    assert r.top_n is None and r.timeout_s == 60


def test_contextual_custom_model_and_top_n() -> None:
    r = ContextualReranker(api_key="k", model="m", top_n=3)
    assert r.model == "m" and r.top_n == 3


def test_contextual_api_key_from_config(monkeypatch) -> None:
    fake_cfg = types.SimpleNamespace(
        contextual_api_key=types.SimpleNamespace(get_secret_value=lambda: "cfg-key")
    )
    monkeypatch.setattr(rerank, "get_config", lambda: fake_cfg)
    r = ContextualReranker(api_key=None)
    assert r.api_key == "cfg-key"


def test_contextual_empty_documents_no_http(monkeypatch) -> None:
    called = []
    monkeypatch.setattr(rerank.requests, "post", lambda *a, **k: called.append(1))
    r = ContextualReranker(api_key="k")
    assert r._rerank("q", []) == []
    assert called == []


def test_contextual_payload_headers_and_endpoint(monkeypatch) -> None:
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        captured.update(url=url, json=json, headers=headers, timeout=timeout)
        return FakeHTTPResponse({"results": []})

    monkeypatch.setattr(rerank.requests, "post", fake_post)
    r = ContextualReranker(api_key="secret", model="m", top_n=2, timeout_s=15)
    r._rerank("Q", ["a", "b"], instruction="INST")
    assert captured["url"] == ContextualReranker.API_URL
    assert captured["timeout"] == 15
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert captured["headers"]["Content-Type"] == "application/json"
    body = captured["json"]
    assert body["query"] == "Q"
    assert body["documents"] == ["a", "b"]
    assert body["model"] == "m"
    assert body["top_n"] == 2
    assert body["instruction"] == "INST"


def test_contextual_default_instruction_when_none(monkeypatch) -> None:
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        captured["json"] = json
        return FakeHTTPResponse({"results": []})

    monkeypatch.setattr(rerank.requests, "post", fake_post)
    r = ContextualReranker(api_key="k")
    r._rerank("q", ["a"])
    assert captured["json"]["instruction"] == ContextualReranker.DEFAULT_INSTRUCTION


def test_contextual_top_n_omitted_when_none(monkeypatch) -> None:
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        captured["json"] = json
        return FakeHTTPResponse({"results": []})

    monkeypatch.setattr(rerank.requests, "post", fake_post)
    r = ContextualReranker(api_key="k")  # top_n None
    r._rerank("q", ["a"])
    assert "top_n" not in captured["json"]


def test_contextual_parses_and_sorts_results(monkeypatch) -> None:
    payload = {
        "results": [
            {"index": 0, "relevance_score": 0.2},
            {"index": 2, "relevance_score": 0.9},
            {"index": 1, "relevance_score": 0.5},
        ]
    }
    monkeypatch.setattr(
        rerank.requests, "post",
        lambda *a, **k: FakeHTTPResponse(payload),
    )
    r = ContextualReranker(api_key="k")
    out = r._rerank("q", ["d0", "d1", "d2"])
    assert [x.document for x in out] == ["d2", "d1", "d0"]
    assert [x.original_index for x in out] == [2, 1, 0]
    assert [x.score for x in out] == [0.9, 0.5, 0.2]


def test_contextual_missing_results_key_returns_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        rerank.requests, "post",
        lambda *a, **k: FakeHTTPResponse({}),  # no "results"
    )
    r = ContextualReranker(api_key="k")
    assert r._rerank("q", ["a"]) == []


def test_contextual_request_exception_propagates(monkeypatch) -> None:
    rec = _RecordLogger()
    monkeypatch.setattr(rerank, "logger", rec)

    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("down")

    monkeypatch.setattr(rerank.requests, "post", boom)
    r = ContextualReranker(api_key="k")
    with pytest.raises(requests.exceptions.ConnectionError):
        r._rerank("q", ["a"])
    assert rec.errors  # contextual_rerank_failed logged


def test_contextual_raise_for_status_error_propagates(monkeypatch) -> None:
    err = requests.exceptions.HTTPError("500")
    monkeypatch.setattr(
        rerank.requests, "post",
        lambda *a, **k: FakeHTTPResponse({"results": []}, raise_exc=err),
    )
    r = ContextualReranker(api_key="k")
    with pytest.raises(requests.exceptions.HTTPError):
        r._rerank("q", ["a"])


# ═════════════════════════ 8. Module surface / latent-bug guard ═════════════════════════

def test_contextual_api_key_field_absent_from_settings() -> None:
    """Guards a latent bug: ContextualReranker(api_key=None) reads
    `config.contextual_api_key`, but RetrieverSettings does not define that field,
    so the no-arg path raises AttributeError at runtime. If this assertion starts
    failing, the field was added and the config fallback now works."""
    from cosmos_retriever.config import RetrieverSettings

    assert "contextual_api_key" not in RetrieverSettings.model_fields
