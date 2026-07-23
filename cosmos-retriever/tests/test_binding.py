from __future__ import annotations

from cosmos_retriever.retrieval.binding import (
    capabilities_from_metadata,
    schema_from_metadata,
)
from cosmos_retriever.retrieval.discovery.models import ContainerMetadata, VectorIndexInfo
from cosmos_retriever.retrieval.errors import InvalidCorpusSchema
from cosmos_retriever.retrieval.schema import DunderChunkCodec
from cosmos_retriever.retrieval.schema_override import SchemaOverride

_CHUNKED_OVERRIDE = SchemaOverride(
    document_id_path="/docid",
    chunk_id_path="/id",
    chunk_order_path="/chunk_idx",
    use_dunder_codec=True,
)


def _meta(*, fts: list[str] | None = None, vec: bool = False) -> ContainerMetadata:
    vectors = []
    if vec:
        vectors = [
            VectorIndexInfo(
                path="/embedding", dimensions=2560, distance_function="cosine", indexed=True
            )
        ]
    return ContainerMetadata(
        database="db", container="c", fetched_at=0.0,
        partition_key_paths=["/docid"], full_text_paths=fts or [], vector_fields=vectors,
    )


def test_hybrid_metadata_builds_hybrid_schema_and_caps() -> None:
    m = _meta(fts=["/text"], vec=True)
    caps = capabilities_from_metadata(m)
    assert caps.native_hybrid_supported and caps.vector_supported and caps.full_text_supported
    s = schema_from_metadata(m)
    assert [str(p) for p in s.text_paths] == ["/text"]
    assert s.vector_fields[0].dimensions == 2560
    # capability dims must match schema dims so the planner's vector check passes
    assert caps.vector_fields[0].dimensions == s.vector_fields[0].dimensions


def test_text_only_metadata() -> None:
    m = _meta(fts=["/text"], vec=False)
    caps = capabilities_from_metadata(m)
    assert caps.full_text_supported and not caps.vector_supported
    s = schema_from_metadata(m)
    assert s.vector_fields == []
    assert [str(p) for p in s.text_paths] == ["/text"]


def test_vector_only_metadata_has_no_text_and_is_valid() -> None:
    m = _meta(fts=None, vec=True)
    caps = capabilities_from_metadata(m)
    assert caps.vector_supported and not caps.full_text_supported
    s = schema_from_metadata(m)  # must not raise despite no text field
    assert s.text_paths == []
    assert s.resolve_text_fields(None) == []
    assert s.vector_fields[0].dimensions == 2560


def test_structured_metadata_cannot_build_search_schema() -> None:
    m = _meta(fts=None, vec=False)
    try:
        schema_from_metadata(m)
    except InvalidCorpusSchema:
        return
    raise AssertionError("expected InvalidCorpusSchema for a container with no text or vector")


def test_no_override_is_item_document_mode() -> None:
    s = schema_from_metadata(_meta(fts=["/text"], vec=True))
    assert s.document_id_path is None
    assert s.is_item_document_mode is True  # graceful: each item is its own document


def test_legacy_override_enables_chunk_reconstruction() -> None:
    s = schema_from_metadata(_meta(fts=["/text"], vec=True), _CHUNKED_OVERRIDE)
    assert str(s.document_id_path) == "/docid"
    assert str(s.chunk_order_path) == "/chunk_idx"
    assert s.is_item_document_mode is False
    assert isinstance(s.identity_codec, DunderChunkCodec)


def test_multiple_text_fields_require_explicit_choice() -> None:
    from cosmos_retriever.retrieval.errors import UnknownField

    s = schema_from_metadata(_meta(fts=["/content", "/title"], vec=True))
    # No default: with >1 text field the caller must name the field(s).
    try:
        s.resolve_text_fields(None)
    except UnknownField:
        pass
    else:
        raise AssertionError("expected UnknownField when no text field is specified")
    # Explicit choices resolve normally.
    assert [str(p) for p in s.resolve_text_fields(["content"])] == ["/content"]
    assert [str(p) for p in s.resolve_text_fields(["content", "title"])] == [
        "/content",
        "/title",
    ]


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
