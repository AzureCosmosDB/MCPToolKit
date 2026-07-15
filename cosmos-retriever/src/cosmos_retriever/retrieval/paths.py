
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict

from cosmos_retriever.retrieval.errors import UnsafeCosmosPath

_ALLOWED_SEGMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_ .\-]*$")


class CosmosPath(BaseModel):

    model_config = ConfigDict(frozen=True)

    segments: tuple[str, ...]

    @classmethod
    def parse(cls, raw: str | CosmosPath) -> CosmosPath:

        if isinstance(raw, CosmosPath):
            return raw
        if not isinstance(raw, str):
            raise UnsafeCosmosPath(f"path must be a string, got {type(raw).__name__}")
        if not raw.startswith("/"):
            raise UnsafeCosmosPath(f"path must start with '/': {raw!r}")
        if len(raw) < 2 or raw.endswith("/"):
            raise UnsafeCosmosPath(f"path is empty or has a trailing '/': {raw!r}")

        segments = raw[1:].split("/")
        for seg in segments:
            if seg == "" or not _ALLOWED_SEGMENT.fullmatch(seg):
                raise UnsafeCosmosPath(f"unsafe path segment {seg!r} in {raw!r}")
        return cls(segments=tuple(segments))

    def render(self, alias: str = "c") -> str:

        out = alias
        for seg in self.segments:
            escaped = seg.replace("\\", "\\\\").replace('"', '\\"')
            out += f'["{escaped}"]'
        return out

    def __str__(self) -> str:
        return "/" + "/".join(self.segments)


def coerce_path(value: Any) -> CosmosPath:

    if isinstance(value, CosmosPath):
        return value
    return CosmosPath.parse(value)
