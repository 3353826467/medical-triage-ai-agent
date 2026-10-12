"""RAG 流水线：切分 → 向量化 → 入库 → 检索（含关键词混合重排）。"""
from __future__ import annotations

import asyncio
import logging
import math
from collections import Counter

from app.config import Settings, get_settings
from app.rag.embeddings import Embeddings, HashingEmbeddings, build_embeddings
from app.rag.knowledge import KnowledgeDoc, load_knowledge_docs
from app.rag.vectorstore import Chunk, Hit, LocalVectorStore, VectorStore, build_vectorstore

logger = logging.getLogger("medical-agent")
from app.schemas import Evidence
from app.utils.text import chunk_text, normalize, tokenize, truncate


class RAGEngine:
    """统一的检索入口，内部屏蔽 Milvus / 本地实现的差异。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.embeddings: Embeddings = build_embeddings(self.settings)
        # 向量库维度必须跟着实际 embedding 走（远端不可用时会自动降级到本地维度）
        self.store: VectorStore = build_vectorstore(self.settings, dim=self.embeddings.dim)
        self._docs: list[KnowledgeDoc] = []
        self._df: Counter[str] = Counter()
        self._lock = asyncio.Lock()
        self._indexed = False

    # ---------------------------- 入库 ---------------------------- #
    def _build_chunks(self, docs: list[KnowledgeDoc]) -> list[Chunk]:
        chunks: list[Chunk] = []
        for doc in docs:
            text = f"{doc.title}\n{doc.content}"
            pieces = chunk_text(text, self.settings.CHUNK_SIZE, self.settings.CHUNK_OVERLAP)
            for idx, piece in enumerate(pieces):
                chunks.append(
                    Chunk(
                        title=doc.title if idx == 0 else f"{doc.title}（续 {idx + 1}）",
                        content=piece,
                        category=doc.category,
                        source=doc.source,
                    )
                )
        return chunks

    async def index(self, docs: list[KnowledgeDoc] | None = None, rebuild: bool = False) -> int:
        async with self._lock:
            docs = docs if docs is not None else load_knowledge_docs()
            self._docs = docs
            chunks = self._build_chunks(docs)

            # 本地哈希向量需要语料统计 IDF
            if isinstance(self.embeddings, HashingEmbeddings):
                self.embeddings.fit([c.embed_text for c in chunks])
            for c in chunks:
                self._df.update(set(tokenize(c.embed_text)))

            if rebuild:
                await self.store.reset()
                self.store = build_vectorstore(self.settings, dim=self.embeddings.dim)

            try:
                vectors = await self.embeddings.aembed_documents([c.embed_text for c in chunks])
            except Exception as exc:  # noqa: BLE001  远端 embedding 中途不可用
                logger.warning("远端 embedding 调用失败，降级本地哈希向量并重灌索引：%s", exc)
                self.embeddings = HashingEmbeddings(dim=self.settings.LOCAL_EMBEDDING_DIM)
                self.embeddings.fit([c.embed_text for c in chunks])
                vectors = await self.embeddings.aembed_documents([c.embed_text for c in chunks])
                self.store = LocalVectorStore()
                await self.store.reset()
            for c, v in zip(chunks, vectors):
                c.vector = v
            await self.store.add(chunks)
            self._indexed = True
            return len(chunks)

    async def bootstrap(self) -> None:
        """启动引导：有索引就复用，没有就导入内置知识库。"""
        if await self.store.count() == 0:
            await self.index()
        else:
            if not self._docs:
                self._docs = load_knowledge_docs()
            self._indexed = True

    async def ensure_indexed(self) -> None:
        """懒加载：首次请求或空库时自动导入内置知识库。"""
        if self._indexed:
            return
        if not self._docs:
            # 复用已有索引时也要加载原文，供计数与关键词兜底检索使用
            self._docs = load_knowledge_docs()
            for doc in self._docs:
                for piece in chunk_text(
                    f"{doc.title}\n{doc.content}",
                    self.settings.CHUNK_SIZE,
                    self.settings.CHUNK_OVERLAP,
                ):
                    self._df.update(set(tokenize(piece)))
        if await self.store.count() > 0:
            self._indexed = True
            return
        await self.index()

    # ---------------------------- 检索 ---------------------------- #
    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        if len(a) != len(b):
            return 0.0
        return sum(x * y for x, y in zip(a, b))

    def _keyword_score(self, query_tokens: list[str], text_tokens: set[str]) -> float:
        if not query_tokens:
            return 0.0
        hit = sum(1.0 for t in query_tokens if t in text_tokens)
        return hit / (len(query_tokens) + 3.0)  # 平滑，避免短查询过拟合

    async def retrieve(self, query: str, top_k: int | None = None) -> list[Evidence]:
        await self.ensure_indexed()
        top_k = top_k or self.settings.TOP_K
        q_vec = await self.embeddings.aembed_query(normalize(query))
        q_tokens = tokenize(query)

        try:
            hits: list[Hit] = await self.store.search(q_vec, top_k * 3)
        except Exception:  # noqa: BLE001  # 向量库异常时退回关键词检索
            hits = []

        if not hits:
            # 兜底：直接用内置文档做关键词打分
            for doc in self._docs:
                text = f"{doc.title} {doc.content}"
                text_tokens = set(tokenize(text))
                score = self._keyword_score(q_tokens, text_tokens)
                if score > 0:
                    hits.append(Hit(chunk=Chunk(title=doc.title, content=doc.content,
                                                 category=doc.category, source=doc.source),
                                    score=score))
            hits.sort(key=lambda h: h.score, reverse=True)
            hits = hits[:top_k]

        if self.settings.ENABLE_HYBRID_RERANK:
            for h in hits:
                text_tokens = set(tokenize(f"{h.chunk.title} {h.chunk.content}"))
                h.score = 0.72 * h.score + 0.28 * self._keyword_score(q_tokens, text_tokens)

        hits = [h for h in hits if h.score >= self.settings.SCORE_THRESHOLD]
        hits.sort(key=lambda h: h.score, reverse=True)

        return [
            Evidence(
                source=h.chunk.source,
                title=h.chunk.title,
                score=round(float(h.score), 4),
                snippet=truncate(h.chunk.content.replace("\n", " "), 180),
            )
            for h in hits[:top_k]
        ]

    def build_context(self, evidence: list[Evidence]) -> str:
        if not evidence:
            return ""
        lines = ["【知识库参考片段】"]
        for i, e in enumerate(evidence, 1):
            lines.append(f"[{i}] 《{e.title}》（来源：{e.source}）\n{e.snippet}")
        return "\n".join(lines)

    # ---------------------------- 诊断信息 ---------------------------- #
    def describe(self) -> dict[str, object]:
        return {
            "vector_backend": self.store.name,
            "embedding_backend": self.embeddings.name,
            "dimension": self.embeddings.dim,
            "indexed": self._indexed,
        }


_engine: RAGEngine | None = None


def get_rag_engine() -> RAGEngine:
    global _engine
    if _engine is None:
        _engine = RAGEngine()
    return _engine
