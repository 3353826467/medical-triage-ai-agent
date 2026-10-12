"""智能问诊 AI 客服系统 —— FastAPI 应用入口。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import BASE_DIR, ensure_dirs, get_settings
from app.llm.provider import get_chat_backend
from app.rag.pipeline import get_rag_engine
from app.routers import chat, faq, health, knowledge, report, session, triage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
logger = logging.getLogger("medical-agent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    ensure_dirs()
    logger.info("启动 %s v%s", settings.APP_NAME, settings.APP_VERSION)

    # 引导知识库：首次启动建索引，之后直接复用
    engine = get_rag_engine()
    try:
        await engine.bootstrap()
        logger.info(
            "知识库就绪：%s 个文档 / 向量后端 %s",
            len(engine._docs),  # noqa: SLF001
            engine.store.name,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("知识库初始化失败，将以纯关键词兜底运行：%s", exc)

    backend = get_chat_backend(settings)
    if backend.available:
        logger.info("大模型引擎：%s（model=%s）", backend.name, settings.LLM_MODEL)
    else:
        logger.warning("未检测到可用的大模型配置，已启用本地规则引擎（离线可演示）")
    yield
    logger.info("服务已停止")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "面向医疗行业的智能问诊与客服系统：症状咨询、智能分诊、报告解读、常见问题解答。"
            "基于 LangChain + OpenAI 兼容协议 + Milvus + FastAPI + Vue3。"
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for r in (health.router, chat.router, triage.router, report.router,
              faq.router, knowledge.router, session.router):
        app.include_router(r)

    @app.get("/api", summary="服务信息")
    async def root() -> JSONResponse:
        return JSONResponse(
            {
                "name": settings.APP_NAME,
                "version": settings.APP_VERSION,
                "docs": "/docs",
                "health": "/api/v1/health",
                "runtime": "/api/v1/runtime",
            }
        )

    # ------------------------------------------------------------------ #
    # 生产态：把前端构建产物挂在根路径，实现「单端口同时提供页面 + API」。
    # 必须放在所有 API 路由注册之后，否则会拦截 /api/v1/*。
    # ------------------------------------------------------------------ #
    static_dir = _resolve_static_dir()
    if static_dir is not None:
        app.mount(
            "/",
            StaticFiles(directory=str(static_dir), html=True),
            name="spa",
        )
        logger.info("已挂载前端静态资源：%s（单端口模式）", static_dir)
    else:
        logger.warning("未找到前端构建产物，仅提供 API（先执行 npm run build）")

    return app


def _resolve_static_dir() -> "Path | None":
    """定位前端构建产物。

    优先级：环境变量 STATIC_DIR > <根>/webroot（部署包） > <根>/frontend/dist（本地开发）。
    """
    import os
    from pathlib import Path

    candidates: list[Path] = []
    env_dir = os.getenv("STATIC_DIR")
    if env_dir:
        candidates.append(Path(env_dir))
    candidates.extend([BASE_DIR / "webroot", BASE_DIR / "frontend" / "dist"])

    for c in candidates:
        if (c / "index.html").is_file():
            return c
    return None


app = create_app()


if __name__ == "__main__":
    import uvicorn

    s = get_settings()
    uvicorn.run("app.main:app", host=s.HOST, port=s.PORT, reload=s.DEBUG)
