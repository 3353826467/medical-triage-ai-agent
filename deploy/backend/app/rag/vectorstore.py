"""向量库抽象层：Milvus 优先，本地内存/文件持久化兜底。

生产环境：Milvus（docker-compose 一键起 standalone）
开发/演示：本地 LocalVectorStore，无需任何外部服务
"""
from __future__ import annotations

import json
import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.config import DATA_DIR, Settings, get_settings
from app.utils.text import normalize

LOCAL_INDEX_PATH = DATA_DIR / "index" / "local_vectorstore.json"


@dataclass
class Chunk:
    """知识库切片。"""

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    title: str = ""
    content: str = ""
    category: str = "通用"
    source: str = ""
    vector: list[float] = field(default_factory=list)

    @property
    def embed_text(self) -> str:
        return normalize(f"{self.title}。{self.content}")


@dataclass
class Hit:
    chunk: Chunk
    score: float


class VectorStore(ABC):
    name: str = "base"

    @abstractmethod
    async def add(self, chunks: list[Chunk]) -> int: ...

    @abstractmethod
    async def search(self, vector: list[float], top_k: int) -> list[Hit]: ...

    @abstractmethod
    async def count(self) -> int: ...

    @abstractmethod
    async def reset(self) -> None: ...


# --------------------------------------------------------------------------- #
# 本地实现
# --------------------------------------------------------------------------- #
class LocalVectorStore(VectorStore):
    """纯 Python 余弦检索，索引落盘为 JSON，重启后自动恢复。"""

    name = "local-json"

    def __init__(self, path: Path = LOCAL_INDEX_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._chunks: list[Chunk] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._chunks = [Chunk(**item) for item in raw]
        except Exception:
            self._chunks = []

    def _persist(self) -> None:
        with self._lock:
            payload = [asdict(c) for c in self._chunks]
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)

    async def add(self, chunks: list[Chunk]) -> int:
        self._chunks.extend(chunks)
        self._persist()
        return len(chunks)

    async def search(self, vector: list[float], top_k: int) -> list[Hit]:
        hits: list[Hit] = []
        for c in self._chunks:
            if len(c.vector) != len(vector):
                continue
            score = sum(a * b for a, b in zip(c.vector, vector))
            hits.append(Hit(chunk=c, score=score))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]

    async def count(self) -> int:
        return len(self._chunks)

    async def reset(self) -> None:
        self._chunks = []
        self._persist()


# --------------------------------------------------------------------------- #
# Milvus 实现
# --------------------------------------------------------------------------- #
class MilvusVectorStore(VectorStore):
    """Milvus 2.x 单机/集群，使用 MilvusClient（REST/gRPC 封装）。"""

    name = "milvus"

    def __init__(self, settings: Settings | None = None, dim: int | None = None) -> None:
        self.settings = settings or get_settings()
        self.collection = self.settings.MILVUS_COLLECTION
        # 维度必须与实际使用的 embedding 一致，否则 Milvus 会拒绝写入
        self.dim = dim or (
            self.settings.EMBEDDING_DIM if self.settings.llm_ready else self.settings.LOCAL_EMBEDDING_DIM
        )
        self._client: Any = None
        self._ready = False
        self._error = ""

    def _connect(self) -> bool:
        if self._ready:
            return True
        try:
            from pymilvus import MilvusClient  # 延迟导入，未安装也可运行
        except ImportError:
            self._error = "pymilvus 未安装"
            return False

        s = self.settings
        uri = f"http://{s.MILVUS_HOST}:{s.MILVUS_PORT}"
        try:
            kwargs: dict[str, Any] = {"uri": uri, "db_name": s.MILVUS_DATABASE}
            if s.MILVUS_USER:
                kwargs["token"] = f"{s.MILVUS_USER}:{s.MILVUS_PASSWORD}"
            client = MilvusClient(**kwargs)
            if not client.has_collection(self.collection):
                client.create_collection(
                    collection_name=self.collection,
                    dimension=self.dim,
                    metric_type="COSINE",
                    auto_id=False,
                    consistency_level="Bounded",
                )
            self._client = client
            self._ready = True
            return True
        except Exception as exc:  # noqa: BLE001
            self._error = f"{type(exc).__name__}: {exc}"
            return False

    async def add(self, chunks: list[Chunk]) -> int:
        if not self._connect():
            raise RuntimeError(f"Milvus 不可用：{self._error}")
        rows = [
            {
                "id": c.id,
                "vector": c.vector,
                "title": c.title[:512],
                "content": c.content[:4096],
                "category": c.category,
                "source": c.source,
            }
            for c in chunks
        ]
        self._client.insert(collection_name=self.collection, data=rows)
        return len(rows)

    async def search(self, vector: list[float], top_k: int) -> list[Hit]:
        if not self._connect():
            raise RuntimeError(f"Milvus 不可用：{self._error}")
        res = self._client.search(
            collection_name=self.collection,
            data=[vector],
            limit=top_k,
            output_fields=["title", "content", "category", "source"],
        )
        hits: list[Hit] = []
        for row in (res or [[]])[0]:
            entity = row.get("entity", {})
            hits.append(
                Hit(
                    chunk=Chunk(
                        id=str(row.get("id", "")),
                        title=entity.get("title", ""),
                        content=entity.get("content", ""),
                        category=entity.get("category", ""),
                        source=entity.get("source", ""),
                    ),
                    score=float(row.get("distance", 0.0)),
                )
            )
        return hits

    async def count(self) -> int:
        if not self._connect():
            return 0
        try:
            return int(self._client.get_collection_stats(self.collection)["row_count"])
        except Exception:  # noqa: BLE001
            return 0

    async def reset(self) -> None:
        if not self._connect():
            return
        if self._client.has_collection(self.collection):
            self._client.drop_collection(self.collection)
        self._ready = False
        self._client = None


def build_vectorstore(settings: Settings | None = None, dim: int | None = None) -> VectorStore:
    settings = settings or get_settings()
    if settings.MILVUS_ENABLED:
        store = MilvusVectorStore(settings, dim=dim)
        # 同步探测：连不上就降级，保证服务永远可启动
        try:
            if store._connect():  # noqa: SLF001
                return store
        except Exception:  # noqa: BLE001
            pass
    return LocalVectorStore()
