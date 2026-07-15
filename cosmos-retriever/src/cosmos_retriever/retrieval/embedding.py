from __future__ import annotations

import openai


class QueryEmbedder:

    def __init__(
        self,
        client: openai.OpenAI,
        model: str,
        query_instruction: str | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._instruction = query_instruction

    def embed(self, text: str) -> list[float]:
        if self._instruction:
            text = f"Instruct: {self._instruction}\nQuery: {text}"
        resp = self._client.embeddings.create(
            model=self._model, input=[text], encoding_format="float"
        )
        return resp.data[0].embedding
