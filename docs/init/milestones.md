# 里程碑路线图（历史记录 + 新主线指引）

> **效力说明（2026-09 起）**：本文件是 M0–M6 的**历史里程碑记录**。
> 项目主线已切换为 `docs/spec/roadmap.md` 的 Wave 序列（Harness Foundation → Speech → Avatar →
> Context → Memory → Task → Security → Presence → Plugin/Skill），M5/M6 的剩余内容已被吸收进
> 新主线的对应 Wave；后续不再按 M 编号推进。

## 新主线速览（2026-09 起）

| Wave | 架构增量 | 用户可见惊喜 | 工程指标 |
|---|---|---|---|
| 0 | Session / Event Log / Generation / Cancellation / Trace | 打断可靠、故障可查 | Interrupt→Audio Stop latency |
| 1 | SpeechRuntime + TTSTaskManager 接线 | "反应好快"、"打断立刻闭嘴" | TTFA / TTFT / E2E |
| 2 | AvatarRuntime + AvatarIntent | 表情随回答变化 | Intent→Animation latency |
| 3 | ContextEngine | 长对话不崩、更懂上下文 | context 占用 / 注入命中率 |
| 4 | Memory Lifecycle | "它居然记得"、"它了解我" | Recall / Consistency |
| 5 | Task / Plan / Artifact | "它能帮我做完一件事" | Task success rate |
| 6 | Security Runtime | "它做事我放心" | 越界拦截率 |
| 7 | Presence / Background | "它住在桌面上" | Intervention quality |
| 8 | Subagent / Skill / Plugin | 能力可扩展 | 插件健康率 |

详见 `docs/spec/roadmap.md`（含建议 Sprint 序列与前六步）。

## 旧里程碑 → 新主线映射

| 旧里程碑 | 状态 | 新主线定位 |
|---|---|---|
| M0 架构骨架 | 已完成 | 前置条件 |
| M1 可运行骨架 | 已完成 | Era 0 的文本链路基础（Wave 0 补 Session/Event） |
| M2 声控 | 已完成 | Era 0 基础；**Barge-in 未达标** → Wave 1 |
| M3 记忆 | 已完成 | Era 2 的 retrieval 基础；**Lifecycle 缺失** → Wave 4 |
| M4 AI 动手 | 已完成 | Era 4 的 Tool/SystemDaemon 基础；**Session/Task/Cancellation 缺失** → Wave 0/5 |
| M5 情感/主动/养成 | 轻量实现 | 情感 → Wave 2；主动 → Wave 7 |
| M6 打磨 + 研究 | 未完成 | 吸收进各 Wave 的 Showcase Test 与发布节奏 |

---

## 历史里程碑原始记录（M0–M6）

### M0 — 架构骨架 + 模型/接口定义（已完成）
- [x] README / ARCHITECTURE / docs（model-selection、system-daemon、research-experiments）
- [x] engine 目录 + 配置 + 模块接口定义
- [x] system-daemon 目录 + 能力清单 + MCP 协议
- [x] shell (Electron+Vue3) 目录 + 事件总线契约
- [x] 完成全部模块接口签名、pyproject/package.json 依赖清单
- 验收：目录完整、接口文档齐全、能按文档无歧义开发每模块。

### M1 — 可运行骨架（已完成）
- Electron 透明桌宠窗口 + 托盘 + Vue3 空壳渲染 Live2D。
- FastAPI 起服务 + WS 控制通道 + shared-secret 鉴权。
- 文本对话：Shell→Engine→LLM→回显（无语音）。
- 验收：`npm run dev` + `uv run main.py` 能显示桌宠并文字聊天。

### M2 — 声控（已完成）
- AudioWorklet 采音 + VAD（silero/FSMN） + ASR（faster-whisper / SenseVoice） + TTS。
- 打断（记忆编辑） + 口型（wLipSync 或 RMS）。
- 验收：对着麦克风说话能触发对话并同步口型。
- 注：打断仅覆盖 TTS 播放阶段；全链路取消属 Wave 1。

### M3 — 记忆（已完成）
- sqlite-vec 三层 + BGE-M3 + RRF 检索 + 自动注入。
- 验收：跨会话记住用户偏好。
- 注：为检索基础；Memory Lifecycle（Episode/Consolidation/Relationship）属 Wave 4。

### M4 — AI 动手（核心，已完成）
- SystemDaemon (C++) 起 + MCP 暴露系统工具。
- 审批队列 + 原生对话框 + dry-run + audit。
- 工具辅助长板：docstring→schema、TodoTool 模型-视图、Skill 热加载（stub）、双语言插件桥（stub）。
- 网易云音乐接入（ncm-cli + mpv）。
- 验收：语音"帮我打开记事本/生成文件"能经审批后执行。
- 注：Task/Plan/Session/Cancellation 属 Wave 0/5。

### M5 — 情感 / 主动 / 养成（轻量实现已起步）
- 情绪衰减(EmotionEngine) + 亲密度/经验(Character) → 驱动表情 `emotion:set`。
- 主动互动(proactive)：定时观察 + LLM 决策避免打扰 + 摄像头/截图随附。
- 验收：宠物有情绪变化、随亲密度成长，且能分寸拿捏地主动打招呼。
- 注：情感 → Wave 2（AvatarIntent）；主动 → Wave 7（Presence/Attention Policy）。

### M6 — 打磨 + 研究
- 实验 1/2/3/4 对照测评脚本 + 结果（口型/记忆/系统操作安全/情绪养成）。
- 性能基准、打包发布（NSIS/dmg）。
- 注：被吸收进 `docs/spec/coding-agent-protocol.md` 的三层测试（Unit/Scenario/Showcase）与各 Wave 验收。

---

## 迭代节奏（历史）

每个里程碑一个 git tag；每模块独立 PR；重要决策写进 ARCHITECTURE 变更日志。
→ 新主线节奏改为：**两周一个 Sprint，一个主要惊喜 + 一个架构增量 + 一个工程指标**（见 `docs/spec/roadmap.md` §5）。
