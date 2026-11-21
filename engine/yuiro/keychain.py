"""OS keychain 封装：LLM API key 持久化（一次配置、重启长期可用）。

架构约定（AGENTS.md）：API key 一律走 OS keychain（keyring），配置只存
``key_ref`` 引用，绝不落盘/提交。本模块统一读写 keyring；keyring 不可用
时降级为内存态（重启失效，并记录警告）。

服务名: yuiro-engine / 用户名: llm
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_SERVICE = "yuiro-engine"
_USERNAME = "llm"

# SiliconFlow 云端 TTS 独立 keychain 命名空间（与 LLM key 隔离，便于分别管理）
_SF_SERVICE = "yuiro-siliconflow"
_SF_USERNAME = "tts"


def save_fish_key(key: str) -> bool:
    """Fish 仅使用 OS keychain；失败不降级为明文或配置内存。"""
    try:
        import keyring

        keyring.set_password("yuiro-fish", "tts", key)
        return True
    except Exception:  # noqa: BLE001 — 不输出后端异常，避免携带凭证
        return False


def load_fish_key() -> str | None:
    try:
        import keyring

        return keyring.get_password("yuiro-fish", "tts")
    except Exception:  # noqa: BLE001
        return None


def clear_fish_key() -> bool:
    try:
        import keyring

        if keyring.get_password("yuiro-fish", "tts"):
            keyring.delete_password("yuiro-fish", "tts")
        return True
    except Exception:  # noqa: BLE001
        return False

# 联网检索（S51）：独立命名空间。设计文档明确要求 key **只走 keychain**，
# config.toml 的 [search] 段刻意不含 api_key 字段（对照 my-neuro 的明文 json 反例）。
_SEARCH_SERVICE = "yuiro-deepseek-search"
_SEARCH_USERNAME = "search"


def save_llm_key(key: str) -> bool:
    """保存 LLM API key 到 OS keychain；返回是否持久化成功。"""
    try:
        import keyring

        keyring.set_password(_SERVICE, _USERNAME, key)
        return True
    except Exception as exc:  # noqa: BLE001 — keychain 故障降级为内存态
        logger.warning("keyring 不可用，key 仅保存在内存（重启失效）: %s", exc)
        return False


def load_llm_key() -> str | None:
    """从 OS keychain 读取 LLM API key；未配置/不可用时返回 None。"""
    try:
        import keyring

        return keyring.get_password(_SERVICE, _USERNAME)
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取 keychain 失败: %s", exc)
        return None


def clear_llm_key() -> bool:
    """删除 keychain 中的 LLM API key；返回是否成功。"""
    try:
        import keyring

        keyring.delete_password(_SERVICE, _USERNAME)
        return True
    except Exception:  # noqa: BLE001 — 不存在或删除失败均视为已清除
        return False


def save_siliconflow_key(key: str) -> bool:
    """保存 SiliconFlow TTS API key 到 OS keychain。"""
    try:
        import keyring

        keyring.set_password(_SF_SERVICE, _SF_USERNAME, key)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("keyring 不可用，SiliconFlow key 仅保存在内存（重启失效）: %s", exc)
        return False


def load_siliconflow_key() -> str | None:
    """从 OS keychain 读取 SiliconFlow TTS API key；未配置/不可用时返回 None。"""
    try:
        import keyring

        return keyring.get_password(_SF_SERVICE, _SF_USERNAME)
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取 SiliconFlow keychain 失败: %s", exc)
        return None


def clear_siliconflow_key() -> bool:
    """删除 keychain 中的 SiliconFlow TTS API key。"""
    try:
        import keyring

        keyring.delete_password(_SF_SERVICE, _SF_USERNAME)
        return True
    except Exception:  # noqa: BLE001
        return False


def save_search_key(key: str) -> bool:
    """保存联网检索服务的 API key 到 OS keychain（S51）。"""
    try:
        import keyring

        keyring.set_password(_SEARCH_SERVICE, _SEARCH_USERNAME, key)
        return True
    except Exception:  # noqa: BLE001
        logger.warning("DeepSeek 搜索密钥保存失败；未降级为明文存储")
        return False


def load_search_key() -> str | None:
    """从 OS keychain 读取搜索服务 API key；未配置/不可用时返回 None。"""
    try:
        import keyring

        return keyring.get_password(_SEARCH_SERVICE, _SEARCH_USERNAME)
    except Exception:  # noqa: BLE001
        logger.warning("读取 DeepSeek 搜索安全存储失败")
        return None


def clear_search_key() -> bool:
    """删除 keychain 中的搜索服务 API key。"""
    try:
        import keyring

        if keyring.get_password(_SEARCH_SERVICE, _SEARCH_USERNAME):
            keyring.delete_password(_SEARCH_SERVICE, _SEARCH_USERNAME)
        return True
    except Exception:  # noqa: BLE001
        return False
