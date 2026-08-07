from __future__ import annotations

from cosmos_retriever.cache import BoundedTTLCache


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def test_put_get_hit_and_miss() -> None:
    c: BoundedTTLCache[str, int] = BoundedTTLCache(max_entries=4, ttl_seconds=10.0)
    assert c.get("a") is None
    c.put("a", 1)
    assert c.get("a") == 1
    s = c.stats()
    assert s.hits == 1 and s.misses == 1 and s.entries == 1


def test_ttl_expiry() -> None:
    clock = _Clock()
    c: BoundedTTLCache[str, int] = BoundedTTLCache(
        max_entries=4, ttl_seconds=10.0, time_source=clock
    )
    c.put("a", 1)
    clock.advance(9.9)
    assert c.get("a") == 1
    clock.advance(0.2)  # now past ttl
    assert c.get("a") is None
    assert c.stats().expirations == 1


def test_lru_eviction_order() -> None:
    evicted: list[tuple[str, int]] = []
    c: BoundedTTLCache[str, int] = BoundedTTLCache(
        max_entries=2, ttl_seconds=100.0, on_evict=lambda k, v: evicted.append((k, v))
    )
    c.put("a", 1)
    c.put("b", 2)
    c.get("a")  # touch a so b is now LRU
    c.put("c", 3)  # evicts b
    assert c.get("b") is None
    assert c.get("a") == 1 and c.get("c") == 3
    assert evicted == [("b", 2)]
    assert c.stats().evictions == 1


def test_put_replaces_value_and_disposes_old() -> None:
    disposed: list[int] = []
    c: BoundedTTLCache[str, int] = BoundedTTLCache(
        max_entries=4, ttl_seconds=100.0, on_evict=lambda k, v: disposed.append(v)
    )
    c.put("a", 1)
    c.put("a", 2)
    assert c.get("a") == 2
    assert disposed == [1]
    assert len(c) == 1


def test_invalidate_and_clear() -> None:
    disposed: list[int] = []
    c: BoundedTTLCache[str, int] = BoundedTTLCache(
        max_entries=4, ttl_seconds=100.0, on_evict=lambda k, v: disposed.append(v)
    )
    c.put("a", 1)
    c.put("b", 2)
    assert c.invalidate("a") is True
    assert c.invalidate("missing") is False
    c.clear()
    assert len(c) == 0
    assert sorted(disposed) == [1, 2]


def test_construction_validates_bounds() -> None:
    for kwargs in ({"max_entries": 0}, {"ttl_seconds": 0.0}, {"ttl_seconds": -1.0}):
        try:
            BoundedTTLCache(**kwargs)  # type: ignore[arg-type]
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {kwargs}")


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
