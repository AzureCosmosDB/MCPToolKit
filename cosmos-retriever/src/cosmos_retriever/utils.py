"""Provider-format enum used by tool serialisation.

Two formats are used, one per backend:

* :pyattr:`ProviderFormat.OPENAI` — the flat OpenAI ``/responses`` function
  shape, used by the responses backend.
* :pyattr:`ProviderFormat.OPENAI_HARMONY` — the OpenAI ``/chat/completions``
  function-tool shape, used by the chat backend.
"""

from __future__ import annotations

from enum import StrEnum


class ProviderFormat(StrEnum):
    """Supported provider formats."""

    OPENAI = "openai"
    OPENAI_HARMONY = "openai_harmony"


__all__ = ["ProviderFormat"]
