"""嵌入器体检：配置 → 文件 → 加载 → 推理 → **语义有效性**。

**为什么"能加载"不等于"能用"**：``Embedder`` 在权重缺失或子进程未就绪时，
会**静默降级到 md5 向量** —— 那种向量是确定性的随机值，它同样能算出余弦相似度、
同样不报错、维度也一样。所以：

- "加载成功"✓ 毫无意义；
- "相似度能算出来"✓ 毫无意义；
- **唯一的判据是：语义相近的句子对，相似度必须显著高于不相近的** ——
  这恰恰是 md5 做不到、BGE-M3 做得到的（脚本会并排打印两者做对照）。

用法：
    python scripts/verify_embedder.py            # 体检配置里的模型
    python scripts/verify_embedder.py --baseline # 额外跑一次 md5 对照
"""
from __future__ import annotations

import asyncio
import math
import sys

#: (句子 A, 句子 B, 语义上是否相近)
CASES: list[tuple[str, str, bool]] = [
    ("我想睡觉了，好困啊", "助眠轻音乐", True),
    ("我想睡觉了，好困啊", "重金属摇滚现场", False),
    ("在图书馆复习考试", "自习室专注学习歌单", True),
    ("在图书馆复习考试", "夜店蹦迪电音", False),
    ("今天心情特别好", "阳光明媚的清晨", True),
    ("今天心情特别好", "他把人打了", False),
]


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


async def _score(model: str | None, label: str) -> float:
    """跑一遍对照用例，返回「相近组均值 − 不相近组均值」。"""
    from yuiro.memory import Embedder

    emb = Embedder(model)
    if model is None:
        print(f"\n--- {label}（md5 降级向量）---")
    else:
        ready = await emb.wait_ready(120.0)
        print(f"\n--- {label} ---")
        print(f"加载：{'就绪' if ready else '未就绪'}（{getattr(emb, '_ready_reason', '')}）")
        if not ready:
            return float("nan")

    highs: list[float] = []
    lows: list[float] = []
    for a, b, close in CASES:
        va, vb = await emb.embed(a), await emb.embed(b)
        s = _cos(va, vb)
        (highs if close else lows).append(s)
        print(f"  {s:+.3f}  {'相近' if close else '无关'}  「{a}」 ↔ 「{b}」")

    diff = sum(highs) / len(highs) - sum(lows) / len(lows)
    print(f"  相近组均值 {sum(highs)/len(highs):+.3f}｜无关组均值 {sum(lows)/len(lows):+.3f}"
          f"｜**差值 {diff:+.3f}**")
    return diff


async def main() -> int:
    from yuiro.config import load_config

    cfg = load_config()
    model = cfg.memory.embedder
    print(f"[memory].embedder = {model!r}")

    # 文件层
    if model and model != "md5":
        from yuiro.main import _probe_embedder_files

        _probe_embedder_files(str(model))

    diff = await _score(None if model == "md5" else model, f"当前配置：{model}")
    if math.isnan(diff):
        print("\n结论：模型**没起来** —— 语义检索处于不可用状态。")
        return 1

    # 对照：同样用例换成 md5，差值应接近 0（证明这个测试真的能分辨）
    base = float("nan")
    if "--baseline" in sys.argv and model != "md5":
        base = await _score(None, "对照组")

    print("\n=== 结论 ===")
    if diff > 0.10:
        print(f"语义可用 ✓（相近组明显更高，差值 {diff:+.3f}）")
        if not math.isnan(base):
            print(f"对照 md5 差值 {base:+.3f} → 本测试确实能分辨真假语义")
        return 0
    print(f"⚠ 差值仅 {diff:+.3f} —— 语义能力**未生效**（可能仍在降级）")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
