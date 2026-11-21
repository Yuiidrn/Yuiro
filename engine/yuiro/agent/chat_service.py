"""Chat service — turn user text into an assistant reply.

M1 打通 Shell↔Engine 文本对话：先提供**可切换的响应器**，
默认用 mock（无需任何 API key 即可验证管线），
当配置了 OpenAI 兼容 LLM 的 key 时切换为真实模型。

关键词：文本对话 / mock / OpenAI 兼容 / 后端先于前端可测。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from yuiro.config import LLMConfig

# 兜底默认人设提示词：persona 未配置时使用，与 config.PersonaConfig 默认值一致。
# 独立于此模块（不 import agent 包），避免与 agent/__init__.py 的默认值形成循环依赖。
_DEFAULT_RESPONDER_PROMPT = (
    "你是一个桌面宠物 AI，名叫 Yuiro。回答要简短、亲切。"
    "回答不要带上emoji表情，但可以适当使用颜文字"
)


class ChatResponder(ABC):
    """Turn a user message into an assistant reply string."""

    @abstractmethod
    async def reply(self, user_text: str) -> str:
        ...

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Used for logging / UI hint (e.g. 'mock', 'openai-compatible')."""
        ...


class MockResponder(ChatResponder):
    """Zero-config responder — echoes a canned line so the pipeline works
    end-to-end without any API key. Good for M1 and offline dev."""

    @property
    def backend_name(self) -> str:
        return "mock"

    async def reply(self, user_text: str) -> str:
        return f"[mock] 收到你的话：『{user_text}』。配置好 LLM API key 后我可真正回答问题。"


class OpenAICompatibleResponder(ChatResponder):
    """Real LLM via any OpenAI-compatible endpoint (OpenAI/DeepSeek/Ollama...).

    Reads base_url/model from config; api_key from explicit call or environment.
    """

    def __init__(self, cfg: LLMConfig, api_key: str, system_prompt: str = "") -> None:
        self._cfg: LLMConfig = cfg
        self._api_key: str = api_key
        # 人设提示词（来自 persona 配置；为空回退内置默认），热重载时随实例重建而更新。
        self._system_prompt: str = system_prompt or _DEFAULT_RESPONDER_PROMPT
        # 懒加载 openai 客户端，避免未用时导入开销
        self._client = None

    @property
    def backend_name(self) -> str:
        return f"openai-compatible({self._cfg.base_url}, {self._cfg.model})"

    def _get_client(self):
        if self._client is None:
            import openai  # 延迟导入

            self._client = openai.AsyncOpenAI(
                base_url=self._cfg.base_url,
                api_key=self._api_key,
            )
        return self._client

    async def reply(self, user_text: str) -> str:
        client = self._get_client()
        resp = await client.chat.completions.create(
            model=self._cfg.model,
            messages=[
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_text},
            ],
        )
        return resp.choices[0].message.content or ""


def build_responder(
    cfg: LLMConfig, api_key: str | None, system_prompt: str = ""
) -> ChatResponder:
    """Factory: 优先用显式传入 api_key，其次使用环境变量。都没有时退回 mock。

    ``system_prompt``：persona 人设提示词，透传给真实 LLM 响应器（agent_loop
    未装配时的 fallback 路径同样遵循人设）。空值时回退内置默认。
    """
    _key = api_key or ""
    if not _key:
        import os

        _key = os.environ.get("YUIRO_LLM_API_KEY") or ""

    if _key:
        return OpenAICompatibleResponder(cfg, _key, system_prompt)
    return MockResponder()
