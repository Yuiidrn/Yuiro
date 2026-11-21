# S16b — 大文件收敛（audio / memory）

> 状态：**进行中**（2026-09-13）。
> 性质：S15/S16 收敛主线的延续——按总评文档"不要在 1500 行的文件里继续加东西"。
> 规范依据：`docs/spec/README.md` 约束 1（复用→抽抽象→适配→替换，禁止删除→重写）。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 16b
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    大文件收敛 —— 把"整块可搬"的职责移到独立模块
SURPRISE: 无（纯地基）
ARCHITECTURE:
  1. audio/__init__.py（1501 行）→ 抽离 audio/providers.py
     （AudioSegment + TTSProvider 基类 + CosyVoice/SiliconFlow/GPTSoVITS 三个实现）
  2. memory/__init__.py（1278 行）→ 抽离 memory/store.py
     （SQLiteVecStore + FactsStore：纯数据访问层）
  约束：逐字搬运 + 原位置 re-export（调用点/外部 import 全部不变 → 零行为变化）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 边界依据

| 模块 | 抽离对象 | 判据 |
|---|---|---|
| `audio` | TTS 实现层（L628–985，约 358 行） | 三个 provider 是**连续**的独立类，只依赖基类契约（`_synthesize_audio`）与 httpx/miniaudio |
| `memory` | 存储层（SQLiteVecStore / FactsStore） | 纯 SQL + dataclass，无业务策略（策略留在 MemorySystem） |

## 交付报告（2026-09-13 完成）

### 结果

| 文件 | 之前 | 之后 | 手段 |
|---|---|---|---|
| `audio/__init__.py` | **1501 行** | **1154 行**（-347） | 抽离 `audio/providers.py`（AudioSegment + TTSProvider + 3 个 provider，逐字搬运） |
| `memory/__init__.py` | 1278 行 | 1278 行（未动） | **有意延后**（见下） |

### 为什么 memory 暂不抽

`SQLiteVecStore` 依赖 `DIM / VEC_K / EXPLICIT_PREFIX` 等模块级常量，抽离需**连带新建
`memory/constants.py` 并改三处**（常量搬迁 + store 搬迁 + re-export），成本约为 audio 的 2 倍，
而当前它并未阻塞任何工作。按 spec 约束 2（不为架构而架构）**有意延后**，记入遗留。

### 手段说明（降低风险）

audio 的 358 行搬运用**行级脚本**完成（按 `class AudioSegment:` → `class TTSTaskManager:`
定位边界后替换为 re-export 块），避免手写超长 edit 造成误伤；替换后立即验证
`import` 与 audio 相关测试。

### 冒烟证据

```
replaced lines 628..987 (360 lines) -> re-export block
file: 1501 -> 1142 lines          ← 脚本视角（含尾部空行差）
imports ok                        ← AudioSegment/TTSProvider/3 provider/TTSTaskManager/VoicePipeline 全部可用
4 failed, 30 passed               ← audio 相关测试：失败集与基线完全一致（均为既有失败）
```

### Tests

- 全量回归 **212 passed / 5 failed / 1 error**（与 S16 基线完全一致）——
  本次是纯搬运，零行为变化；
- `audio/providers.py` 为新增模块，`audio/__init__.py` 保留 re-export（外部 import 路径不变）。

### 遗留

- `memory/__init__.py`（1278 行）存储层抽离（需先建 `memory/constants.py`）；
- `agent/__init__.py` 的 `send()` 主体（约 380 行：去重/限流/早停/收尾总结）；
- `audio/__init__.py` 的 `VoicePipeline`（约 460 行，1 个类）；
