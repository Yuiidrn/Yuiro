# LLM 桌宠大脑微调方案（Mac 本地部署 + 人设定制）

> 状态：**设想 / 参考路线图**（未实施）
> 目标：参照 Neuro-sama 的个性化效果，用小权重开源模型在配置较好的 MacBook 上自建服务端，
> 经自有"人设回复 + 工具调用"语料微调，得到深度个性化的桌宠大脑。
> 关联模块：`engine/yuiro/agent/`（LLM 适配 / AgentLoop）、`engine/yuiro/memory/`（语料来源）、
> `engine/yuiro/config.py`（provider 预设）、调试台「参数配置」（base_url 热切换）。

---

## 1. 核心结论（TL;DR）

1. **引擎零改造即可接入本地模型**：`OpenAIProvider` 走标准 OpenAI 兼容协议，而
   LM Studio / Ollama / `mlx_lm.server` 均暴露 OpenAI 兼容端点（如 `http://localhost:1234/v1`）。
   微调完成后只需在调试台把 LLM `base_url` 改为 Mac 的本地地址。
2. **Mac 侧关键框架是 MLX，不是 LM Studio**：2026 年 Apple Silicon 本地 AI 主流路线已是
   苹果官方 MLX 框架（统一内存、零拷贝）。训练用 `mlx-lm` 的 LoRA/QLoRA，推理可挂 adapter 直连。
3. **基座首推 Qwen3 系列（4B/8B）**：与现有云端主链路（千问系）同家族，
   中文能力强、工具调用模板一致性最好、MLX 社区量化版齐全。
4. **微调只解决 prompt 做不好的事**：说话风格的"肌肉记忆"与工具调用的稳定模式；
   知识/记忆类内容仍由 L2/L3 记忆系统承担，不要塞进权重。
5. **Yuiro 引擎是天然的数据工厂**：L2 情景记忆已持久化成对对话，工具调用补落库后即为 SFT 语料。

---

## 2. Neuro-sama 式个性化的技术分解

Neuro-sama 的"人格"由三层叠加，微调只是其中一层：

| 层 | Neuro-sama 的做法 | 对应本项目 | 微调必要性 |
|---|---|---|---|
| 行为风格（语气/口头禅/梗） | 长期语料 + 调教 | `persona.system_prompt` + 情绪文案 | ⭐ 中：少量语料即可，prompt 已能覆盖约 70% |
| 长期记忆 / 关系 | 记住观众、.events | L2/L3 记忆（sqlite-vec + RRF） | ❌ 不需要微调，已实现 |
| 深层一致性（价值观 / 反应模式 / 工具使用习惯） | 大量私有语料训练 | 目前仅靠 prompt | ⭐⭐ 高：**微调真正的价值区** |

**定位原则**：微调目标 = 让人几句话就认出"这是你的 Yuiro"，而非"任何 AI 扮演的 Yuiro"；
纯知识靠记忆系统，不进权重。

---

## 3. 整体架构

```
┌─ Windows 主力机（Yuiro 运行时）────────────────┐
│  Yuiro 引擎 (engine:8200)                       │
│  └─ LLM base_url → http://<mac>:1234/v1        │
│     （调试台改 base_url 即可，零代码改动）       │
└──────────────────┬─────────────────────────────┘
                   │ LAN / OpenAI 兼容 API
┌─ MacBook（模型工坊）────────────────────────────┐
│  LM Studio / mlx_lm.server (:1234)              │
│  └─ Qwen3-4B(4bit) + 自训 LoRA adapter          │
│                                                 │
│  训练闭环: yuiro_memory.db 导出语料              │
│   → mlx_lm.lora (QLoRA) → 评测                  │
│   → 合并导出 GGUF(q4_k_m) → LM Studio           │
└─────────────────────────────────────────────────┘
```

注意点：
- **延迟**：局域网 RTT 可忽略；4B@4bit 在 M 系芯片首 token 约 0.3~1s，
  相比 qwen-plus 云端可能略慢，语音场景（`/ws/audio` 链路有 30s 总时限）需实测。
- **可用性**：桌宠要说话 Mac 就得在线。调试台已有 provider 预设机制，
  云端 / 本地可一键切换作为兜底。

---

## 4. Mac 端技术选型

### 4.1 训练侧

| 方案 | 适合谁 | 说明 |
|---|---|---|
| **mlx-lm + LoRA/QLoRA**（推荐） | 本项目 | 苹果官方 `mlx_lm.lora` 一条命令训练；M 系列 24G 统一内存实测可训 4B 全 LoRA、8B QLoRA |
| FineTune Studio | 想要 GUI | Electron + React 的 Mac 微调工具，底层即 mlx-lm |
| LLaMA-Factory / Unsloth | 功能最全 | 为 NVIDIA 优化；Mac 上走 MLX 更顺 |

训练参数起点（`mlx_lm.lora`）：`--rank 16~32`、`--iters 1000~2000`、4bit QLoRA 基座。
先用 0.6B 模型跑通全流程，再换 4B/8B。

### 4.2 推理侧

| 方案 | 优劣 |
|---|---|
| **LM Studio** | 最省心：GUI + OpenAI 兼容 API，支持 GGUF 与 MLX 格式 |
| **mlx_lm.server** | 训练完直接 `--adapter-path` 挂 LoRA 起服务，**免导出、迭代最快**（开发期首选） |
| Ollama（v0.30+） | 已内置 MLX 引擎；Modelfile 打包便于分发 |

**建议**：开发期用 `mlx_lm.server` 直接挂 adapter（改完即测）；
稳定期把 adapter 合并进基座、导出 GGUF（`save_pretrained_gguf`，推荐 `q4_k_m`）丢进 LM Studio。

---

## 5. 基座模型选型

| 候选 | 大小 | 理由 |
|---|---|---|
| **Qwen3-4B / 8B**（首推） | 4B/8B | 与云端主链路（千问系）同家族，风格与工具调用格式一致性最好；中文强；`mlx-community/Qwen3-4B-4bit` 等量化版齐全 |
| GLM-4.7-Flash | 小 | 中文好，MLX 有 4bit/8bit 版 |
| Llama 4 8B | 8B | 通用性强，但中文个性化语料效率不如 Qwen |
| Qwen3-0.6B / 1.7B | 极小 | **流程验证用**：M2 24G 训练飞快，先跑通再升级 |

选型原则：与云端正牌（Qwen）同家族，微调出的"工具调用习惯"迁移最顺。

---

## 6. 数据集构建（Yuiro = 天然数据工厂）

### 6.1 语料来源

1. **L2 情景记忆**（`data/yuiro_memory.db` 的 `messages` 表）：
   已按 `用户: xxx\n助手: xxx` 成对持久化，导出即 SFT 语料；
2. **工具调用日志**（`AgentLoop.send` 中的 `tool_call` / `tool_result`，目前仅 vlog）：
   **需补落库**，积累工具调用样本；
3. **手写理想回复**：对同一用户输入写"Neuro-sama 式"理想回答——人格定制的黄金语料，
   50~200 条即有效果。

### 6.2 格式要点

- **人设对话**：标准 chat 格式；system 用 `persona.system_prompt`，保持训练/推理一致；
- **工具调用**：必须用**基座原生 tool-call 模板**（Qwen3 有自己的 `<tool_call>` 标记），
  不要自创 JSON 格式，否则推理时与 `OpenAIProvider` 的增量解析对不上；
- **规模**：纯风格 LoRA 约 500~2000 条；每类工具 30~50 条高质量样本；
- **防灾难性遗忘**：掺 10~20% 通用中文对话，避免模型"只会说梗"。

### 6.3 评测维度

- 工具调用格式合法率 / 参数正确率（对 `ToolRegistry` 真实回放）；
- 风格盲测：与 baseline（纯 prompt）对比辨识度；
- 通用能力回归：掺入的通用测试题不塌方。

---

## 7. 引擎侧配套改动（实施时）

| # | 改动 | 位置 | 说明 |
|---|---|---|---|
| 1 | 工具调用落库 | `engine/yuiro/agent/__init__.py`（AgentLoop.send 的 tool_call/tool_result 分支） | 目前只 vlog；落库到 memory.db 新表或独立日志，供语料导出 |
| 2 | `lmstudio` provider 预设 | `engine/yuiro/config.py` 的 `LLM_PROVIDER_PRESETS` | 加一行 `("http://localhost:1234/v1", <model>)`；调试台即可下拉选择 |
| 3 | 语料导出脚本 | `scripts/` 新增 | 从 yuiro_memory.db 导出 chat JSONL + 工具调用样本 |
| 4 | （可选）本地/云端一键切换 | 调试台 | 已有 provider 预设 + 热重载，基本零成本 |

> 适配器注意：本地小模型可能不支持 `tools` 参数的完整语义，`OpenAIProvider.stream_text`
> 的工具调用增量解析已有兜底（arguments 解析失败落 `_raw`），必要时增加"格式纠错重试"。

---

## 8. 分阶段路线图

| 阶段 | 内容 | 成本 | 产出 |
|---|---|---|---|
| **0. Baseline（现在可做）** | 不微调：把 `persona.system_prompt` 写狠 + 记忆注入风格少样本 | 零 | 评估"prompt 上限"，作为微调对照 |
| **1. 数据积累** | 工具调用落库 + 持续对话积累 L2 语料 | 小改动 | 语料资产（无论是否微调都值得） |
| **2. 流程验证** | Mac 上 Qwen3-0.6B + ~500 条语料跑通 `mlx_lm.lora`；`lmstudio` 预设接入；改 base_url 验证 | 中 | 端到端闭环 + 显存/延迟实测数据 |
| **3. 正式训练** | Qwen3-4B/8B 正经训练 + 评测（工具成功率 / 风格盲测） | 大 | 可用的个性化大脑 |
| **4. 稳定部署** | 合并 adapter → GGUF(q4_k_m) → LM Studio 常驻 | 小 | 日常使用的最终形态 |

---

## 9. 风险与坦率提醒

1. **工具调用可靠性是最大的坑**：7B 级微调模型的工具调用格式错误率明显高于 qwen-plus 云端。
   缓解：`AgentLoop` 已有异常兜底（`result = {"error": ...}` 不阻断），再加格式纠错重试；
2. **风格 ≠ 魅力**：Neuro-sama 的核心魅力很大部分来自实时性、记忆与内容编排，而非模型本身——
   本项目的记忆系统 + 情绪引擎 + 主动互动已在这条路上，微调只是最后一块拼图；
3. **数据隐私**：L2 记忆含私人对话，导出语料注意脱敏/留在本地训练（Mac 本地训练恰好满足）；
4. **版权**：确认所用基座模型许可证允许微调与部署（Qwen3 / GLM 系均为宽松许可）；
5. **镜像约定**：Mac 侧下载 HF 模型同样优先走国内可达镜像
   （`HF_ENDPOINT=https://hf-mirror.com` 或 ModelScope），遵守仓库"镜像优先"硬约定。

---

## 10. 参考（2026-08 检索）

- MLX（Apple 官方框架，专为 Apple Silicon 统一内存优化）：`github.com/ml-explore/mlx`，训练用 `mlx-lm`；
- `mlx_lm.lora` QLoRA 微调 + `mlx_lm.chat --adapter-path` 即测，中文社区已有 Qwen3-0.6B/4B 完整教程；
- FineTune Studio：Electron + React 的 Mac 微调 GUI（底层 mlx-lm，`mlx_lm.server` 提供服务）；
- Ollama v0.30+：llama.cpp 增强 + Apple Silicon MLX 引擎，开启 GGUF 与自有微调模型本地化；
- LLaMA-Factory / ms-swift / Unsloth：通用微调框架对比（NVIDIA 向，Mac 备选）；
- LM Studio / llama.cpp / Ollama 均提供 OpenAI 兼容端点，与 `OpenAIProvider` 直接兼容。
