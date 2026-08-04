
from __future__ import annotations

from enum import StrEnum


class ProviderFormat(StrEnum):

    """Tool-call wire format a tool schema is serialized into.

    Selected by the caller — each ``run_*`` agent loop passes the value matching
    the configured ``INFERENCE_BACKEND`` — and is *not* auto-detected from model
    responses: ``OPENAI`` is the ``/responses`` function format,
    ``OPENAI_HARMONY`` the ``/chat/completions`` Harmony format, and
    ``ANTHROPIC`` the Anthropic tool format.
    """

    OPENAI = "openai"
    OPENAI_HARMONY = "openai_harmony"
    ANTHROPIC = "anthropic"


__all__ = ["ProviderFormat"]
