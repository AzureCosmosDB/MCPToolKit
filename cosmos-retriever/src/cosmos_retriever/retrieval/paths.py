"""Safe Cosmos property-path representation.

Configured property paths (e.g. ``/payload/body``) must never be interpolated
straight into SQL. :class:`CosmosPath` parses a path into validated segments and
renders a bracket-quoted, alias-relative expression such as
``c["payload"]["body"]`` that is safe regardless of reserved words or
non-identifier property names. Raw SQL fragments are rejected.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict

from cosmos_retriever.retrieval.errors import UnsafeCosmosPath

# A single path segment (property name). Must start with a letter/underscore and
# contain only letters, digits, underscore, space, dot or hyphen. This is
# permissive enough for realistic property names while rejecting quotes,
# brackets, and SQL metacharacters.
_ALLOWED_SEGMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_ .\-]*$")


class CosmosPath(BaseModel):
    """A validated, safely-renderable Cosmos property path."""

    model_config = ConfigDict(frozen=True)

    segments: tuple[str, ...]

    @classmethod
    def parse(cls, raw: str | CosmosPath) -> CosmosPath:
        """Parse ``/a/b/c`` into a :class:`CosmosPath`.

        Raises :class:`UnsafeCosmosPath` for empty, malformed, or dangerous
        input. Array traversal is not supported by default.
        """

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
        """Render an alias-relative, bracket-quoted SQL expression."""

        out = alias
        for seg in self.segments:
            escaped = seg.replace("\\", "\\\\").replace('"', '\\"')
            out += f'["{escaped}"]'
        return out

    def __str__(self) -> str:
        return "/" + "/".join(self.segments)


def coerce_path(value: Any) -> CosmosPath:
    """Pydantic BeforeValidator: accept a str or a :class:`CosmosPath`."""

    if isinstance(value, CosmosPath):
        return value
    return CosmosPath.parse(value)
