"""Provider adapter that turns texts into embedding vectors."""

from typing import Any


class OpenAIEmbedder:
    def __init__(self, client: Any, model: str):
        self._client, self._model = client, model

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [item.embedding for item in self._client.embeddings.create(model=self._model, input=texts).data]
