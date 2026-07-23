from __future__ import annotations

import os
import threading
from typing import Protocol, runtime_checkable

from azure.cosmos import CosmosClient
from azure.identity import AzureCliCredential, DefaultAzureCredential


@runtime_checkable
class CredentialProvider(Protocol):
    def credential(self) -> object: ...


class DefaultCredentialProvider:
    def credential(self) -> object:
        opt_in = os.environ.get("COSMOS_USE_DEFAULT_CREDENTIAL", "").strip().lower()
        if opt_in in {"1", "true", "yes"}:
            return DefaultAzureCredential()
        return AzureCliCredential()


class CosmosAccountConnection:
    def __init__(
        self,
        endpoint: str,
        credential_provider: CredentialProvider | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._provider = credential_provider or DefaultCredentialProvider()
        self._client: CosmosClient | None = None
        self._lock = threading.Lock()

    @property
    def endpoint(self) -> str:
        return self._endpoint

    def client(self) -> CosmosClient:
        if self._client is None:
            with self._lock:
                if self._client is None:
                    self._client = CosmosClient(self._endpoint, self._provider.credential())
        return self._client

    def close(self) -> None:
        with self._lock:
            self._client = None
