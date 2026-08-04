from __future__ import annotations

import openai


class QueryEmbedder:

    def __init__(
        self,
        client: openai.OpenAI,
        model: str,
        query_instruction: str | None = None,
        dimensions: int | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._instruction = query_instruction
        self._dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        if self._instruction:
            text = f"Instruct: {self._instruction}\nQuery: {text}"
        kwargs: dict[str, object] = {}
        if self._dimensions is not None:
            kwargs["dimensions"] = self._dimensions
        resp = self._client.embeddings.create(
            model=self._model, input=[text], encoding_format="float", **kwargs
        )
        return resp.data[0].embedding
