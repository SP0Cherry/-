"""Embedding clients for the knowledge base.

Two backends: a remote OpenAI-compatible /embeddings API (``api``) and a
deterministic offline ``stub`` used by tests and local development. All
returned vectors are L2-normalized so vector distances are comparable.
"""
from __future__ import annotations

import hashlib
import math

import requests


class EmbeddingError(RuntimeError):
    """Gateway call failed for a non-config reason."""


class EmbeddingConfigError(EmbeddingError):
    """Embedding backend is not configured or credentials are rejected."""


MAX_BATCH = 64


def l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0:
        raise EmbeddingError("embedding vector has zero norm")
    return [x / norm for x in vector]


class Embedder:
    def __init__(self, dim: int):
        self.dim = dim

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_one(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    @staticmethod
    def _batches(texts: list[str]):
        for start in range(0, len(texts), MAX_BATCH):
            yield texts[start : start + MAX_BATCH]


class APIEmbedder(Embedder):
    def __init__(self, dim: int, base_url: str, api_key: str, model: str, timeout: int):
        super().__init__(dim)
        if not base_url:
            raise EmbeddingConfigError("缺少 EMBEDDING_BASE_URL")
        if not api_key:
            raise EmbeddingConfigError("缺少 EMBEDDING_API_KEY")
        self.url = base_url.rstrip("/") + "/embeddings"
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _request_once(self, texts):
        response = requests.post(
            self.url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self.model, "input": texts},
            timeout=self.timeout,
        )
        if response.status_code in (401, 403):
            raise EmbeddingConfigError(
                f"嵌入接口鉴权失败（{response.status_code}）"
            )
        response.raise_for_status()
        return response.json()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        results: list[tuple[int, list[float]]] = []
        offset = 0
        for batch in self._batches(texts):
            data = None
            last_error: Exception | None = None
            for _attempt in range(2):  # one retry
                try:
                    data = self._request_once(batch)
                    break
                except EmbeddingConfigError:
                    raise
                except requests.RequestException as error:
                    last_error = error
            if data is None:
                raise EmbeddingError(f"嵌入接口调用失败：{last_error}")
            items = sorted(data["data"], key=lambda item: item.get("index", 0))
            for item in items:
                vector = item["embedding"]
                if len(vector) != self.dim:
                    raise EmbeddingConfigError(
                        f"嵌入维度 {len(vector)} 与配置 {self.dim} 不一致"
                    )
                results.append((offset, l2_normalize(vector)))
                offset += 1
        return [vector for _idx, vector in results]


class StubEmbedder(Embedder):
    """Deterministic, normalized feature-hash embeddings; never network-bound.

    Adjacent character pairs (weight 1) and triples (weight 1.5) hash into one
    slot each, so texts sharing vocabulary have higher cosine similarity. It
    approximates, not replaces, semantic embeddings.
    """

    def _vector_for(self, text: str) -> list[float]:
        vector = [0.0] * self.dim

        def add_feature(feat: str, weight: float):
            digest = hashlib.sha256(feat.encode("utf-8")).digest()
            index = int.from_bytes(digest[:2], "big") % self.dim
            vector[index] += weight

        for ch in text:
            if not ch.isspace():
                add_feature(ch, 0.5)
        seen_pairs = set()
        for i in range(len(text) - 1):
            pair = text[i : i + 2]
            if not any(ch.isspace() for ch in pair) and pair not in seen_pairs:
                add_feature(pair, 1.0)
                seen_pairs.add(pair)
        for i in range(len(text) - 2):
            triple = text[i : i + 3]
            if not any(ch.isspace() for ch in triple):
                add_feature(triple, 1.5)
        return l2_normalize(vector)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._vector_for(text) for text in texts]


def build_embedder(config) -> Embedder:
    backend = config["EMBEDDING_BACKEND"]
    dim = config["EMBEDDING_DIM"]
    if backend == "stub":
        return StubEmbedder(dim)
    if backend != "api":
        raise EmbeddingConfigError(f"未知 EMBEDDING_BACKEND：{backend}")
    return APIEmbedder(
        dim=dim,
        base_url=config["EMBEDDING_BASE_URL"],
        api_key=config["EMBEDDING_API_KEY"],
        model=config["EMBEDDING_MODEL"],
        timeout=config["EMBEDDING_TIMEOUT"],
    )
