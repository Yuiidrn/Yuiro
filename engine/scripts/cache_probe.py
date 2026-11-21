"""缓存命中探针：一次调用，回答"这个 provider 到底吃不吃前缀缓存"。

**为什么值得单独做**：S47 的上下文排序优化（稳定前缀 + 变化后缀）**只有在
provider 支持自动前缀缓存时才有收益**。而"支不支持"是**事实问题** ——
不该靠推测，也不该靠"感觉快了点"。先花两次极短请求问清楚，再决定要不要
继续在这条路上投入。

**做法**：用**逐字节完全相同**的 messages 连发两次，比较第二次的缓存命中数。

- 命中 > 0 → 支持，排序优化会**直接转化**为延迟收益；
- 命中 = 0 → **该模型不吃"前缀稳定"这套**，此时该换 provider，
  而不是继续优化注入顺序。

**⚠ 两个最容易"误判为不支持"的坑**（本脚本已避开）：
1. **前缀太短**：各家前缀缓存都有**最小长度门槛**（常见 1024 tokens 量级），
   短前缀无论怎么试都不会命中；
2. **走的是生产代码路径**：这里直接用 ``OpenAIProvider``，因此**顺带验证了
   ``stream_options`` 是否被该端点接受** —— 若被拒，usage 拿不到，
   连"有没有命中"都无从观测（脚本会明确区分这两种情况）。

成本：两次很短的请求（各带约 4k 字符的稳定前缀）。
用法：在 ``engine/`` 目录下执行 ``python scripts/cache_probe.py``
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from yuiro.agent import OpenAIProvider  # noqa: E402
from yuiro.config import load_config  # noqa: E402
from yuiro.keychain import load_llm_key  # noqa: E402

#: 用于凑长度的稳定文本（不含任何指令，避免影响回答）。
_FILLER = "这是一段用于测试前缀缓存的稳定背景文本，不承载任何指令。"
#: 前缀字符数。**必须给足** —— 低于服务端的最小缓存门槛就永远命中不了，
#: 而这正是"误判为不支持"的头号原因（中文约 1 字 ≈ 1 token）。
_MIN_PREFIX_CHARS = 4000


def _hit_tokens(usage: dict) -> int:
    """归一各家缓存命中字段（与 ``TraceContext.cache_line`` 同一口径）。"""
    u = usage or {}
    details = u.get("prompt_tokens_details") or {}
    return int(
        u.get("prompt_cache_hit_tokens")
        or details.get("cached_tokens")
        or u.get("cache_read_input_tokens")
        or 0
    )


async def _ask(provider: OpenAIProvider, prefix: str, tag: str) -> dict:
    """发一次请求并取回 usage（走生产同一条 stream_text 路径）。"""
    messages = [
        {"role": "system", "content": prefix},
        {"role": "user", "content": "请只回复两个字：收到。"},
    ]
    usage: dict = {}
    try:
        async for chunk in provider.stream_text(messages):
            if chunk.kind == "done" and chunk.usage:
                usage = chunk.usage
    except Exception as exc:  # noqa: BLE001 — 探针要把失败原因原样呈现
        print(f"[{tag}] ✗ 请求失败：{type(exc).__name__}: {str(exc)[:200]}")
        return {}
    print(f"[{tag}] usage = {usage or '（未返回）'}")
    return usage


async def main() -> int:
    cfg = load_config()
    api_key = load_llm_key() or ""
    print(f"endpoint = {cfg.llm.base_url}")
    print(f"model    = {cfg.llm.model}")
    if not api_key:
        print("✗ 未找到 LLM API key（keychain 为空）—— 请先在调试台配置并持久化。")
        return 2
    print(f"前缀长度 = {_MIN_PREFIX_CHARS} 字符\n")

    provider = OpenAIProvider(
        cfg.llm.base_url, cfg.llm.model, api_key, temperature=0.0
    )
    prefix = (_FILLER * ((_MIN_PREFIX_CHARS // len(_FILLER)) + 1))[:_MIN_PREFIX_CHARS]

    first = await _ask(provider, prefix, "第 1 次（建立缓存）")
    await asyncio.sleep(1.5)  # 给服务端落缓存留一点时间
    second = await _ask(provider, prefix, "第 2 次（预期命中）")

    if not first and not second:
        print(
            "\n✗ 两次都没拿到 usage。两种可能：\n"
            "  1) 端点不支持 stream_options（我们的代码已自动去掉它降级重试，"
            "所以对话仍正常）；\n"
            "  2) 请求本身失败（见上面的错误）。\n"
            "  → 无论哪种，都**无法从这里判断缓存**；但排序优化本身无害。"
        )
        return 1

    hit2 = _hit_tokens(second)
    prompt2 = int(second.get("prompt_tokens") or 0)
    print(f"\n缓存命中：第 1 次 = {_hit_tokens(first)} tokens，第 2 次 = {hit2} tokens")
    if hit2 > 0:
        pct = f"（{hit2 * 100 // prompt2}%）" if prompt2 else ""
        print(f"✓ 支持前缀缓存：第 2 次命中 {hit2} tokens{pct}")
        print("  → S47 的「稳定前缀 + 变化后缀」排序会**直接转化**为延迟下降。")
        return 0

    print("✗ 第 2 次仍未命中 —— **该模型不吃「前缀稳定」这套**。")
    print("  → 此时不该继续优化注入顺序，而应考虑换到支持自动前缀缓存的端点")
    print("    （DeepSeek / OpenAI 等）。")
    print("  注：若该平台的前缀缓存需要**显式声明**（部分平台的显式缓存如此），")
    print("      自动命中为 0 属预期，需要按平台文档额外传参。")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
