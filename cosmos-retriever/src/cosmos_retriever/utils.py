"""Provider-format enum used by trajectory + tool serialisation.

The retriever only ever talks to two formats:

* :pyattr:`ProviderFormat.OPENAI` — OpenAI Chat Completions JSON, used for
  cross-format readability/serialisation in tests.
* :pyattr:`ProviderFormat.OPENAI_HARMONY` — OpenAI-Harmony token format, the
  in-context format the trained model was optimised for and the only format
  used at runtime against vLLM.

Other formats (Anthropic, Moonshot, OpenAI Responses) lived in upstream
Harness-1 to support teacher generation and evaluation; they are intentionally
excluded here.
"""

from __future__ import annotations

from enum import StrEnum


class ProviderFormat(StrEnum):
    """Supported provider formats."""

    OPENAI = "openai"
    OPENAI_HARMONY = "openai_harmony"


__all__ = ["ProviderFormat"]
