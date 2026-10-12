"""LLM 接入层：LangChain ChatOpenAI（兼容任意 OpenAI 协议端点）。

支持的服务：OpenAI / DeepSeek / 通义千问兼容模式 / 智谱 / Moonshot / 本地 vLLM、Ollama 等，
只要暴露 OpenAI 风格的 /v1/chat/completions 即可，改 `OPENAI_BASE_URL` 一行切换。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from app.config import Settings, get_settings

Message = dict[str, str]  # {"role": "system"|"user"|"assistant", "content": str}


class ChatBackend(ABC):
    name: str = "base"
    available: bool = False

    @abstractmethod
    async def ainvoke(self, messages: list[Message], **kwargs: Any) -> str: ...

    @abstractmethod
    async def astream(self, messages: list[Message], **kwargs: Any) -> AsyncIterator[str]: ...

    async def ajson(self, messages: list[Message], **kwargs: Any) -> dict | None:
        """要求模型输出 JSON 对象，失败返回 None。"""
        from app.utils.text import extract_json_object

        raw = await self.ainvoke(messages, **kwargs)
        return extract_json_object(raw)


class NullChatBackend(ChatBackend):
    """无 API Key 时的占位实现：直接触发各链路的规则降级逻辑。"""

    name = "rule-engine"
    available = False

    async def ainvoke(self, messages: list[Message], **kwargs: Any) -> str:
        return ""

    async def astream(self, messages: list[Message], **kwargs: Any) -> AsyncIterator[str]:
        if False:  # pragma: no cover - 保持生成器签名
            yield ""
        return


class LangChainChatBackend(ChatBackend):
    """基于 LangChain 的 OpenAI 兼容聊天后端。"""

    name = "langchain-openai"
    available = True

    def __init__(self, settings: Settings | None = None, model: str | None = None) -> None:
        from langchain_openai import ChatOpenAI  # 延迟导入，避免无依赖时启动失败

        s = settings or get_settings()
        self.settings = s
        self._llm = ChatOpenAI(
            model=model or s.LLM_MODEL,
            api_key=s.OPENAI_API_KEY,  # type: ignore[arg-type]
            base_url=s.OPENAI_BASE_URL,
            temperature=s.LLM_TEMPERATURE,
            max_tokens=s.LLM_MAX_TOKENS,
            timeout=s.LLM_TIMEOUT,
            max_retries=2,
        )
        self._fast = (
            self._llm
            if not s.LLM_MODEL_FAST
            else ChatOpenAI(
                model=s.fast_model,
                api_key=s.OPENAI_API_KEY,  # type: ignore[arg-type]
                base_url=s.OPENAI_BASE_URL,
                temperature=0.0,
                max_tokens=1024,
                timeout=s.LLM_TIMEOUT,
                max_retries=2,
            )
        )

    def _lc_messages(self, messages: list[Message]) -> list[tuple[str, str]]:
        return [(m["role"], m["content"]) for m in messages]

    async def ainvoke(self, messages: list[Message], fast: bool = False, **kwargs: Any) -> str:
        llm = self._fast if fast else self._llm
        resp = await llm.ainvoke(self._lc_messages(messages), **kwargs)
        return getattr(resp, "content", "") or ""

    async def astream(self, messages: list[Message], fast: bool = False, **kwargs: Any) -> AsyncIterator[str]:
        llm = self._fast if fast else self._llm
        async for chunk in llm.astream(self._lc_messages(messages), **kwargs):
            content = getattr(chunk, "content", "")
            if content:
                yield content if isinstance(content, str) else str(content)

    async def ajson(self, messages: list[Message], fast: bool = True, **kwargs: Any) -> dict | None:
        from app.utils.text import extract_json_object

        llm = self._fast if fast else self._llm
        try:
            bound = llm.bind(response_format={"type": "json_object"})
            resp = await bound.ainvoke(self._lc_messages(messages))
            data = extract_json_object(getattr(resp, "content", "") or "")
            if data:
                return data
        except Exception:  # noqa: BLE001  部分模型不支持 json_object，退回普通输出
            pass
        return await super().ajson(messages, **kwargs)


_backend: ChatBackend | None = None


def get_chat_backend(settings: Settings | None = None) -> ChatBackend:
    """返回全局聊天后端；无 Key 或强制降级时返回 Null 实现。"""
    global _backend
    if _backend is None:
        s = settings or get_settings()
        if s.llm_ready:
            try:
                _backend = LangChainChatBackend(s)
            except Exception:  # noqa: BLE001
                _backend = NullChatBackend()
        else:
            _backend = NullChatBackend()
    return _backend


def engine_name() -> str:
    return get_chat_backend().name
