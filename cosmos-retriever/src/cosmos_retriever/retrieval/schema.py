 
from __future__ import annotations

from typing import Annotated, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, BeforeValidator, model_validator

from cosmos_retriever.retrieval.errors import InvalidCorpusSchema, UnknownField
from cosmos_retriever.retrieval.paths import CosmosPath, coerce_path

PathField = Annotated[CosmosPath, BeforeValidator(coerce_path)]


class VectorFieldConfig(BaseModel):
    path: PathField
    name: str | None = None
    description: str | None = None
    embedding_model: str | None = None
    dimensions: int
    distance_function: Literal["cosine", "dotproduct", "euclidean"] = "cosine"
    data_type: str = "float32"


@runtime_checkable
class ChunkIdentityCodec(Protocol):

    def to_document_id(self, raw_id: str) -> str: ...


class LegacyDunderCodec:

    def to_document_id(self, raw_id: str) -> str:
        if isinstance(raw_id, str) and "__" in raw_id:
            return raw_id.split("__", 1)[0]
        return raw_id


class CorpusSchema(BaseModel):
    item_id_path: PathField
    text_paths: list[PathField]
    primary_text_path: PathField
    vector_fields: list[VectorFieldConfig] = []
    document_id_path: PathField | None = None
    chunk_id_path: PathField | None = None
    chunk_order_path: PathField | None = None
    title_path: PathField | None = None
    source_path: PathField | None = None
    partition_key_paths: list[PathField] = []
    metadata_paths: dict[str, PathField] = {}
    text_field_descriptions: dict[str, str] = {}
    model_config = {"arbitrary_types_allowed": True}

    identity_codec: ChunkIdentityCodec | None = None

    @model_validator(mode="after")
    def _check(self) -> CorpusSchema:
        errors: list[str] = []
        primary = str(self.primary_text_path)
        if primary not in {str(p) for p in self.text_paths}:
            errors.append("primary_text_path must be one of text_paths")
        for v in self.vector_fields:
            if v.dimensions <= 0:
                errors.append(f"vector field {v.path} has non-positive dimensions")
        if errors:
            raise InvalidCorpusSchema("; ".join(errors))
        return self

    @property
    def is_item_document_mode(self) -> bool:

        return self.document_id_path is None

    @property
    def partition_key_is_document_id(self) -> bool:

        if self.document_id_path is None or len(self.partition_key_paths) != 1:
            return False
        return str(self.partition_key_paths[0]) == str(self.document_id_path)

    @staticmethod
    def _seg_name(path: CosmosPath) -> str:
        return path.segments[-1]

    def text_field_map(self) -> dict[str, CosmosPath]:

        out: dict[str, CosmosPath] = {}
        for p in self.text_paths:
            name = self._seg_name(p)
            if name in out and str(out[name]) != str(p):
                name = str(p)
            out[name] = p
        return out

    def vector_field_map(self) -> dict[str, CosmosPath]:

        out: dict[str, CosmosPath] = {}
        for i, vf in enumerate(self.vector_fields):
            name = vf.name or self._seg_name(vf.path)
            if name in out:
                name = f"{name}_{i}"
            out[name] = vf.path
        return out

    def primary_text_field_name(self) -> str:
        for name, p in self.text_field_map().items():
            if str(p) == str(self.primary_text_path):
                return name
        return self._seg_name(self.primary_text_path)

    def resolve_text_fields(self, names: list[str] | None) -> list[CosmosPath]:
        if not names:
            return [self.primary_text_path]
        m = self.text_field_map()
        paths: list[CosmosPath] = []
        for n in names:
            if n not in m:
                raise UnknownField(
                    f"unknown text field {n!r}; available: {sorted(m)}"
                )
            paths.append(m[n])
        return paths

    def resolve_vector_config(self, name: str | None) -> VectorFieldConfig:
        if not self.vector_fields:
            raise UnknownField("no vector fields are configured")
        if name is None:
            return self.vector_fields[0]
        for i, vf in enumerate(self.vector_fields):
            vname = vf.name or self._seg_name(vf.path)
            if vname == name or f"{vname}_{i}" == name:
                return vf
        available = sorted(self.vector_field_map())
        raise UnknownField(f"unknown vector field {name!r}; available: {available}")

    def resolve_vector_field(self, name: str | None) -> CosmosPath:
        return self.resolve_vector_config(name).path

    def agent_field_summary(self) -> str:

        tm = self.text_field_map()
        vm = self.vector_field_map()
        lines: list[str] = []
        tparts = []
        for n, p in tm.items():
            d = self.text_field_descriptions.get(n) or self.text_field_descriptions.get(str(p))
            tparts.append(f"'{n}'" + (f" — {d}" if d else ""))
        lines.append("Text fields (keyword / BM25): " + ", ".join(tparts))
        if vm:
            vparts = []
            for n, p in vm.items():
                cfg = next((v for v in self.vector_fields if str(v.path) == str(p)), None)
                d = cfg.description if cfg else None
                vparts.append(f"'{n}'" + (f" — {d}" if d else ""))
            lines.append("Vector fields (semantic): " + ", ".join(vparts))
        default_v = next(iter(vm), None)
        default = f"hybrid over text='{self.primary_text_field_name()}'"
        if default_v:
            default += f" + vector='{default_v}'"
        lines.append(f"Default when unspecified: {default}.")
        return "\n".join(lines)
