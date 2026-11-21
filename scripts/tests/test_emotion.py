"""M5 情感引擎验证：情绪加成/衰减/style_hint + 角色养成。"""
from __future__ import annotations

import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, "D:/Project/Yuii/desktop-pet/Yuiro/engine")

from yuiro.emotion import EMOTION_EXPRESSION_HINTS, Character, EmotionEngine

# 情绪引擎
e = EmotionEngine(decay_rate=0.02)
print("初始主情绪:", e.state.dominant())
e.boost("happy", 0.5)
print(f"boost happy+0.5 -> {e.state.dominant()} (happy={e.state.happy:.2f})")
print("style_hint:", e.style_hint()[:40])
# 模拟时间流逝衰减（120s）
e._last_decay = time.monotonic() - 120
changed = e.decay()
print("衰减 120s 后主情绪:", e.state.dominant(), "| 变化:", changed)
assert e.state.happy < 0.7  # 确实衰减了

# 角色养成
c = Character()
c.add_affinity(15)
c.add_xp(250)
print(f"角色: affinity={c.affinity_state()}, level={c.level}, xp={c.xp}")
assert c.level == 3  # 250 xp = 2 次升级 + 50 余
print("表达式映射:", EMOTION_EXPRESSION_HINTS)
print("EMOTION ENGINE TEST PASSED")
