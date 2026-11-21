# S04 — 分段流式 TTS（首句先出声）

> 状态：**已批准开工**（2026-09-11，Human 指令"继续"）。
> 性质：Wave 1 核心性能项；直接针对 S01 基线发现的最大瓶颈（TTS 3674ms，占说完→出声 48%）。
> 规范依据：`docs/spec/architecture-goal.md` §3.8（TTS epoch / 有序播放）、S01 基线结论。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 04
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    分段流式 TTS + TTSTaskManager 接线
SURPRISE: Yuiro 第一句话几乎立刻出声（不再整段憋完才开口）
USER EXPERIENCE:
  - 长回复：首句先合成先播，后续句子边合成边播、自然衔接
  - 说完 → 首句出声时间显著下降（基线 7616ms；目标 ≤50%）
  - 打断时立即停播（复用 S03 链路），未播段落全部作废
ARCHITECTURE:
  - split_sentences()（模块级公共函数，供 pipeline / provider 共用）
  - TTSTaskManager 真正接入 _speak：并发合成（限流）+ 按序交付 + epoch 取消
  - TTSTaskManager 修复：interrupt 后 wait_next 可退出（_closed）；单句合成失败不阻塞整条
  - segment_streaming 开关接线：False 时整段（回退路径，行为同旧）
FILES:
  engine/yuiro/audio/__init__.py（split_sentences / TTSTaskManager / _speak / interrupt）
  engine/yuiro/main.py（把 config.tts.segment_streaming 传给 VoicePipeline）
  engine/tests/test_tts_streaming.py（新增）
CODING AGENT:
  遵循 coding-agent-protocol：最小改动、保留整段回退路径、加测试、报告 before/after。
  禁止重写 TTSProvider 子类；禁止改变 tts:audio 事件字段语义（前端 FIFO 队列已支持多段）。
TEST:
  Unit：split_sentences（标点切分 / 短句合并 / 长句强切 / 空文本）
  Unit：TTSTaskManager（按序交付 / interrupt 后 wait_next 退出 / 单句失败跳过）
  Scenario：_speak 分句 → 首段先播 → 全段按序（Fake TTS 记录播放顺序）
  + 回归（对照基线：5 failed 集不变）
PERFORMANCE:
  before：说完→首句出声 7616ms（S01 基线；其中整段 TTS 3674ms）
  after：目标 ≤50%（首句音频 ≈ 整段 1/n）
DEFINITION OF DONE:
  - 分句流式默认开启；segment_streaming=False 回退整段（行为同旧）
  - 首段音频就绪即播放（不等待后续段）
  - 播放顺序与分句顺序一致（FIFO）
  - 打断时：wait_next 立即退出、未播段作废（不挂起、不播放）
  - 单句合成失败跳过该句、后续继续
  - trace 的 tts_first_audio 反映"首段"时刻；回归通过
HUMAN ACCEPTANCE:
  长回复（3 句以上）→ 首句几乎立即出声；打断后无残留音频
CUSTOM ASSET: （无）
NEXT UNLOCK: TTFA 达标的基础；S05 可转 AvatarIntent（前端解码 93ms 已很快）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 关键设计（已定）

1. **单路径 + 开关**：`sentences = split_sentences(reply) if segment_streaming else [reply]`，
   不为两种模式写两套代码；短回复自然退化为单段。
2. **并发限流**：TTSTaskManager 内置 `asyncio.Semaphore(max_concurrency=2)`，避免本地 TTS 服务被并发打爆；
   远端 SiliconFlow 可后续调高。
3. **失败不阻塞**：单句合成失败 → 放空段占位（wav 为空），播放侧跳过；不给 `wait_next` 留"缺号"。
4. **取消语义**：`interrupt()` → `mgr.interrupt()`（epoch++ / closed / 唤醒等待者）；
   `wait_next` 返回 `None` 表示已关闭；`_speak` 收到 None 立即退出。

## 交付报告（2026-09-11 完成）

### Changed files

**新增**：`engine/tests/test_tts_streaming.py`（8 个用例）

**修改**：

| 文件 | 改动 |
|---|---|
| `engine/yuiro/audio/__init__.py` | 新增模块级 `split_sentences()`（标点切分 + 短句合并 + 长句软切）；`TTSTaskManager` 增强（信号量限流 / 单句失败空段占位 / 文档）；`VoicePipeline` 新增 `segment_streaming` 参数 + `_tts_managers`；`_speak` 改为**分句流式**（并行合成 → 按序首段先播）；`interrupt()` 增加在途段作废（epoch++） |
| `engine/yuiro/main.py` | 装配传入 `segment_streaming=cfg.tts.segment_streaming`（死开关接线） |

### 性能对比（同文本，真实 SiliconFlow TTS）

| 路径 | 首段音频就绪 | 全部音频完成 | 说明 |
|---|---|---|---|
| 整段合成（旧） | 6780ms | 6780ms | 1174KB 一次性返回 |
| **分句流式（S04）** | **2307ms** | 5502ms | 3 段；首段 196KB |

- **首段出声时间降低 66%**（目标 ≤50%，超额达成）；
- 全部完成还略快（分段更小 + 并发合成）；
- 端到端预期：`说完→首句出声` 从 S01 基线 7616ms ≈ 降至 3.5–4s（其余为 ASR 0.75s + LLM 2.5s）。

### Tests

- 新增 **8 个**全部通过；全量回归 **89 passed**（失败集与基线一致）；
- 修复 1 个**真实回归**：既有测试断言 `tts:ready.volumes_count` → 保留该字段（分段后为各段片数之和）；
- ruff 全绿。

### DoD 对照

- [x] 分句流式默认开启；`segment_streaming=False` 回退整段（测试覆盖）
- [x] 首段就绪即播放（`wait_next` 先返回 seq=1）
- [x] 播放顺序与分句顺序一致（`test_speak_streams_in_order`）
- [x] 打断时在途段作废、不播放任何段（`test_interrupt_discards_inflight_segments`）
- [x] 单句合成失败跳过、后续继续（`test_manager_orders_and_skips_failure`）
- [x] trace 的 `tts_first_audio` 反映首段时刻（语义不变、数值显著变小）

### Human Acceptance（待人工）

长回复（3 句以上）→ **首句几乎立即出声**；打断后无残留音频。

### 风险 / 遗留

- 并发限流为 2（本地 TTS 服务保守值；SiliconFlow 等远端可后续调高）；
- `SiliconFlowProvider._split_sentences` 与其内部逐句请求暂未与公共 `split_sentences` 合并（避免无谓改动，后续统一）。
