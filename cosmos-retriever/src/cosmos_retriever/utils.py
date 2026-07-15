
from __future__ import annotations

from enum import StrEnum


class ProviderFormat(StrEnum):

    OPENAI = "openai"
    OPENAI_HARMONY = "openai_harmony"


__all__ = ["ProviderFormat"]
