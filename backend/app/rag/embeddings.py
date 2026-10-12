"""Embedding 层：优先 OpenAI 兼容接口，无 Key 时降级为本地哈希向量。

本地方案采用「字符 uni/bi-gram 哈希 + IDF 加权 + L2 归一化」，
在医疗短文本（症状词、指标名）上的召回质量接近词袋模型，且完全离线可用。
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
from abc import ABC, abstractmethod
from collections import Counter
from functools import lru_cache
from typing import Iterable

import httpx

from app.config import Settings, get_settings
from app.utils.text import normalize, tokenize

logger = logging.getLogger("medical-agent")


class Embeddings(ABC):
    name: str = "base"
    dim: int = 0

    @abstractmethod
    async def aembed_documents(self, texts: list[str]) -> list[list[float]]: ...

    @abstractmethod
    async def aembed_query(self, text: str) -> list[float]: ...


# --------------------------------------------------------------------------- #
# 本地降级实现
# --------------------------------------------------------------------------- #
class HashingEmbeddings(Embeddings):
    """零依赖本地向量：uni/bi-gram 哈希 + 子线性 TF + 平滑 IDF + L2 归一化。"""

    name = "local-hashing"

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim
        self._doc_freq: Counter[str] = Counter()
        self._doc_count = 0
        self._fitted = False

    def _features(self, text: str) -> list[str]:
        toks = tokenize(text)
        feats = list(toks)
        # 额外加入英文小写原串，提升 LDL-C 之类指标名的区分度
        for raw in re.findall(r"[A-Za-z][A-Za-z0-9\-]{1,}", normalize(text).lower()):
            feats.append(raw)
        return feats

    def _index(self, feature: str) -> int:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=4).digest()
        return int.from_bytes(digest, "big") % self.dim

    def _raw_vector(self, text: str) -> dict[int, float]:
        counts: Counter[int] = Counter()
        for feat in self._features(text):
            counts[self._index(feat)] += 1.0
        return {k: 1.0 + math.log(v) for k, v in counts.items()}

    def fit(self, corpus: Iterable[str]) -> None:
        """用知识库语料统计 IDF（可选，未 fit 时退化为纯 TF）。"""
        self._doc_freq.clear()
        self._doc_count = 0
        for doc in corpus:
            self._doc_count += 1
            for feat in set(self._features(doc)):
                self._doc_freq[feat] += 1
        self._fitted = self._doc_count > 0

    def _idf(self, feature: str) -> float:
        if not self._fitted:
            return 1.0
        df = self._doc_freq.get(feature, 0)
        return math.log((1.0 + self._doc_count) / (1.0 + df)) + 1.0

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for feat in self._features(text):
            vec[self._index(feat)] += self._idf(feat)
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    async def aembed_query(self, text: str) -> list[float]:
        return self._embed(text)


# --------------------------------------------------------------------------- #
# OpenAI 兼容实现
# --------------------------------------------------------------------------- #
class OpenAICompatEmbeddings(Embeddings):
    name = "openai-embeddings"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.dim = self.settings.EMBEDDING_DIM

    def _url(self) -> str:
        return f"{self.settings.OPENAI_BASE_URL.rstrip('/')}/embeddings"

    async def _post(self, texts: list[str]) -> list[list[float]]:
        payload = {"model": self.settings.EMBEDDING_MODEL, "input": texts}
        headers = {
            "Authorization": f"Bearer {self.settings.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.settings.LLM_TIMEOUT) as client:
            resp = await client.post(self._url(), json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        return [item["embedding"] for item in data["data"]]

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        batch = 64
        for i in range(0, len(texts), batch):
            out.extend(await self._post(texts[i : i + batch]))
        return out

    async def aembed_query(self, text: str) -> list[float]:
        vecs = await self._post([text])
        return vecs[0]


@lru_cache(maxsize=8)
def _remote_embeddings_available(base_url: str, model: str, api_key: str, timeout: int) -> bool:
    """探测远端是否真的提供 /embeddings。

    很多 OpenAI 兼容端点（DeepSeek、多数国内对话模型）只提供 chat/completions，
    没有 embedding 接口。若不做探测，启动时建索引会直接 404 失败。
    探测结果按 (base_url, model) 缓存，进程内只探一次。
    """
    url = f"{base_url.rstrip('/')}/embeddings"
    try:
        resp = httpx.post(
            url,
            json={"model": model, "input": ["维度探测"]},
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
        if resp.status_code >= 400:
            return False
        data = resp.json()
        return bool((data.get("data") or [{}])[0].get("embedding"))
    except Exception:  # noqa: BLE001
        return False


def build_embeddings(settings: Settings | None = None) -> Embeddings:
    settings = settings or get_settings()

    if settings.EMBEDDING_PROVIDER == "local" or not settings.llm_ready:
        return HashingEmbeddings(dim=settings.LOCAL_EMBEDDING_DIM)

    if settings.EMBEDDING_PROVIDER == "auto" and not _remote_embeddings_available(
        settings.OPENAI_BASE_URL, settings.EMBEDDING_MODEL, settings.OPENAI_API_KEY,
        min(settings.LLM_TIMEOUT, 15),
    ):
        logger.warning(
            "远端 %s 未提供可用的 /embeddings 接口，已自动降级为本地哈希向量",
            settings.OPENAI_BASE_URL,
        )
        return HashingEmbeddings(dim=settings.LOCAL_EMBEDDING_DIM)

    return OpenAICompatEmbeddings(settings)
