"""全局配置：所有外部依赖都可通过环境变量 / .env 覆盖。

设计目标：任何一项外部服务缺失（OpenAI Key、Milvus、Embedding 接口）时，
系统都能自动降级到本地实现，保证服务可启动、可演示。
"""
from __future__ import annotations

import os
import time
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_START_TIME = time.time()

BASE_DIR = Path(__file__).resolve().parents[2]  # 仓库根目录
BACKEND_DIR = BASE_DIR / "backend"
DATA_DIR = BASE_DIR / "data"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------------- 服务 ----------------
    APP_NAME: str = "智能问诊 AI 客服系统"
    APP_VERSION: str = "1.0.0"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = True
    # 前端开发服务器地址（CORS）
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080"

    # ---------------- LLM（OpenAI 兼容协议）----------------
    # 留空即进入"本地规则引擎"降级模式
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    # 对话模型
    LLM_MODEL: str = "gpt-4o-mini"
    # 意图识别 / 结构化抽取等轻量任务使用的小模型，留空则复用 LLM_MODEL
    LLM_MODEL_FAST: str = ""
    LLM_TEMPERATURE: float = 0.3
    LLM_MAX_TOKENS: int = 2048
    LLM_TIMEOUT: int = 60
    # 是否强制走规则引擎（压测 / 离线演示时很有用）
    FORCE_RULE_ENGINE: bool = False

    # ---------------- Embedding ----------------
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIM: int = 1536
    # 降级用的本地哈希向量维度
    LOCAL_EMBEDDING_DIM: int = 384
    # auto：先探测远端 /embeddings，不可用则自动降级本地；
    # openai：强制远端（失败会直接报错）；local：强制本地哈希向量
    EMBEDDING_PROVIDER: str = "auto"

    # ---------------- Milvus ----------------
    MILVUS_ENABLED: bool = True
    # 完整连接目标。留空则按 HOST:PORT 拼成 http://host:port（连 Docker standalone）；
    # 填本地文件路径（如 ./data/milvus.db）则走 Milvus Lite 嵌入式模式，无需 Docker。
    #
    # ⚠️ 字段名不能用 MILVUS_URI：pymilvus 自身在 import 时会读同名环境变量并当作
    # gRPC 地址解析，填本地路径会直接抛 "Illegal uri"。这里改名 MILVUS_TARGET 避让。
    MILVUS_TARGET: str = ""
    MILVUS_HOST: str = "127.0.0.1"
    MILVUS_PORT: str = "19530"
    MILVUS_USER: str = ""
    MILVUS_PASSWORD: str = ""
    MILVUS_DATABASE: str = "default"
    MILVUS_COLLECTION: str = "medical_kb"

    # ---------------- RAG ----------------
    TOP_K: int = 4
    SCORE_THRESHOLD: float = 0.15
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 60
    # 检索重排：是否启用关键词加权融合
    ENABLE_HYBRID_RERANK: bool = True

    # ---------------- 安全 ----------------
    # 是否允许返回具体用药建议（生产环境建议 False）
    ALLOW_MEDICATION_ADVICE: bool = False
    DISCLAIMER: str = (
        "本结果由 AI 生成，仅供参考，不能替代执业医师的面诊、检查与诊断。"
        "如症状加重或持续不缓解，请及时线下就医；出现紧急情况请立即拨打 120。"
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def fast_model(self) -> str:
        return self.LLM_MODEL_FAST or self.LLM_MODEL

    @property
    def llm_ready(self) -> bool:
        """是否具备调用真实大模型的能力。"""
        return bool(self.OPENAI_API_KEY) and not self.FORCE_RULE_ENGINE


@lru_cache
def get_settings() -> Settings:
    return Settings()


def ensure_dirs() -> None:
    for d in (DATA_DIR, KNOWLEDGE_DIR, DATA_DIR / "index", BACKEND_DIR / "logs"):
        os.makedirs(d, exist_ok=True)
