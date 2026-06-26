"""Shared pytest fixtures.

We deliberately avoid the project's :class:`RetrieverSettings` here — none of
the unit tests should touch real Cosmos or OpenAI. The :func:`stub_settings_env`
fixture (auto-applied) populates the required env vars with placeholder values
so that any import-time validation succeeds without secrets.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def stub_settings_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Provide harmless defaults for required env vars across the test session."""

    monkeypatch.setenv("ACCOUNT_URI", "https://stub.documents.azure.com:443/")
    monkeypatch.setenv("COSMOS_DATABASE", "test-db")
    monkeypatch.setenv("COSMOS_CORPUS_CONTAINER", "test-container")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-stub")
    monkeypatch.setenv("VLLM_BASE_URL", "http://test-vllm:8000")
    monkeypatch.setenv("VLLM_MODEL_NAME", "harness-1")
    yield
