# 主流 Agent 产品的上下文管理与记忆策略调研

> 调研时间：2026-08。目的：为 Yuiro 记忆系统与上下文工程的后续演进提供业界参照。
> 方法：官方文档/博客 + 社区逆向分析 + 开源代码（Letta）交叉验证。文中区分【透露】（官方或逆向确认）与【推测】（合理推断）。
> 关联文档：`docs/memory-system.md`（本项目记忆系统现状）。

---

## 一、总览：两大范式已经收敛

2025–2026 年，行业从「朴素 RAG（生成前预检索 + 全量历史塞上下文）」转向两条互补路线的组合：

| 范式 | 解决的问题 | 代表做法 |
|---|---|---|
| **上下文工程**（Context Engineering） | 单会话内「模型能看到什么」 | 压缩（compaction）、append-only、todo 复述、文件系统外存 |
| **记忆系统**（Memory as Tools） | 跨会话「Agent 记住什么」 | 画像注入、检索工具化、自我编辑记忆块、写入冲突消解 |

三个关键趋势：

1. **检索从"框架替模型做"变成"模型自己调工具做"**（agentic retrieval）——检索成为 Agent 的工具之一，由 LLM 决定是否、何时、检索什么。
2. **记忆从"只读向量库"变成"LLM 可读写的有状态组件"**——写入侧出现冲突消解（新增/更新/删除决策）。
3. **记忆操作与主对话链路解耦**——后台空闲期异步整理，避免阻塞响应。

---

## 二、产品拆解

### 2.1 ChatGPT（OpenAI）—— 逆向工程最充分

【透露】（prompt probing 逆向 + GDPR 导出论文 arXiv:2602.01450）

**上下文结构**（按 system prompt 排列顺序）：

```
System Instructions（行为规则 + 工具定义）
Session Metadata（设备/时区/订阅等级，会话结束不保留）
Model Editable Context —— Saved Memories（带时间戳的短事实列表，用户可见可删）
User Knowledge Memories —— 隐式画像（数百次对话提炼，几段~十几段，用户不可见不可编辑）
Topic Highlights（跨对话高层主题摘要）
Recent Conversations（最近约 40 个对话的摘要：时间戳+标题+用户消息）
Interaction Metadata（行为统计：平均对话深度、模型使用占比、近 50 条消息主题分布）
Personal Context Tooling（检索工具定义）
当前对话消息
```

**记忆策略**：

- **写入**：内部 `bio` 工具——模型自行判断值得记的事实后调用保存。论文统计（80 名用户 GDPR 导出，2050 条）：**96% 条目由系统主动创建**，仅 4% 用户显式要求；28% 含 GDPR 个人数据，52% 含心理画像类信息。
- **隐式画像更新**：【推测】后台定期任务批量重算（观察到画像两天不变、第三天突变），频率未公开。
- **检索**：2026-01 起加入「搜索 past chats」能力。规则（从 system prompt 提取）：
  - 检索是**默认行为**：含回指表达（"那个/之前/我们讨论过"）、进行中的项目、个性化建议均触发；仅完全自包含的知识问答不触发。
  - 检索工具**看不到当前对话**，需先把问题改写为自包含查询。
  - 数据源不限于对话历史，还包括偏好、项目上下文、已连接外部工具。
  - **静默失败**：指令明确"不要声称有记忆限制"，检索失败不告知用户。

**架构哲学**【推测但有据】：数亿周活用户下，2025 年中之前根本不做实时检索（延迟/成本不现实），赌「模型聪明 + 上下文变大变便宜」；先预计算画像注入，后补按需检索——**预计算优先、实时检索兜底**的两层混合。

### 2.2 Claude（Anthropic）—— 分层注入 + 分层压缩

【透露】（官方文档 + harness 泄漏代码分析）

**Claude Code 记忆层级**（每次会话开始载入，均为"提醒的便签"而非"约束的法律"）：

| 层级 | 谁写 | 载入量 |
|---|---|---|
| Managed Policy（企业级） | 管理员 | 全量 |
| User（`~/.claude/CLAUDE.md`） | 用户 | 全量 |
| Project（`./CLAUDE.md`，随仓库共享） | 用户 | 全量 |
| Local（`CLAUDE.local.md`） | 用户 | 全量 |
| Auto Memory（`MEMORY.md`） | Claude 自动累积 | **前 200 行 / 25KB** |

- 层级间**拼接而非覆盖**；向上（父目录）急加载、子目录惰性加载；`@import` 递归导入最大 4 跳。
- **Compaction 分层**：Snip → Microcompact → Context Collapse → Session Memory → Full Compact；支持在配置中写 `Compact instructions` 自定义**压缩时的保留优先级**。
- 消费版 Claude 的会话记忆走 **tool-based retrieval**（`conversation_search` / `recent_chats`），与 ChatGPT 相反：**白板起步**，模型自行判断是否检索，过程界面可见。
- 需要确定性强制时用 **Hooks**（脚本事件触发）而非记忆——「记忆不约束行为」是刻意设计。

### 2.3 Manus —— 上下文工程六原则（官方博客完整透露）

出处：官方博客《Context Engineering for AI Agents: Lessons from Building Manus》（2025-07）。

1. **围绕 KV-cache 设计**：KV-cache 命中率是生产 Agent 最重要指标（Manus input:output 高达 **100:1**）。prompt 前缀严格稳定（无时间戳等动态元素）、上下文 **append-only**、确定性 serialization、显式标记 cache breakpoints。
2. **Mask，而非移除**：动态增删 tool 定义会打爆 KV-cache；保留全部工具定义，用 logit masking 控制可用性。
3. **文件系统作为外部记忆**：上下文里只存 URL/路径引用不留全文，实现"无损压缩"。
4. **用 todo 复述操纵注意力**：长任务维护 `todo.md` 反复"背诵"目标，对抗 lost-in-the-middle。
5. **保留错误信息**：不清理失败操作与堆栈，让模型从错误中学习。
6. **避免被 few-shot 带偏**：统一示例导致过度模仿，引入结构化变体（不同措辞/serialization/微噪声）保持多样性。

### 2.4 Letta（MemGPT）—— 记忆架构的"操作系统派"（开源可查源码）

出处：MemGPT 论文《Towards LLMs as Operating Systems》（arXiv:2310.08560）+ letta-ai/letta 仓库。

**三层记忆**（类比 OS：LLM=CPU，上下文窗口=RAM，外部存储=硬盘）：

| 层级 | 类比 | 实现 | 常驻上下文？ |
|---|---|---|---|
| Core Memory | RAM | persona/human 两个可编辑 Block（各 2000 字符上限），渲染进 system prompt | 是 |
| Recall Memory | 聊天日志 | 消息历史库，`conversation_search` 工具访问，支持日期/角色过滤 + 混合检索 | 否 |
| Archival Memory | 硬盘 | 向量 passage（Chroma/Qdrant/pgvector），**RRF 融合**向量+全文 | 否 |

**关键机制**：

- **自我编辑**：`core_memory_replace` / `memory_rethink` / `memory_apply_patch` 等工具直接改写自己的 prompt；带 read_only 保护、old_str 唯一性校验。
- **换页**：超阈值时旧消息驱逐 → 独立"临时摘要 Agent"压缩 → 摘要插入索引 1（紧随系统消息）。
- **Sleep-time Agent**（2025 创新）：后台 Agent 在会话空闲期整理压缩记忆，主 Agent 专注对话。
- 与标准 RAG 的本质区别：**主动式**（LLM 决定检索）、**读写**（可自我更新）、**有状态**（身份跨会话持久）。

### 2.5 Mem0 —— 写入冲突消解的流水线派

【透露】（开源框架 + 论文）

两阶段 LLM 流水线：

1. **提取阶段**：从对话增量中抽取候选记忆事实。
2. **更新阶段**：LLM 将每条候选与现有记忆比对，输出 `ADD / UPDATE / DELETE / NOOP` 决策。

检索为向量 + 图（可选 Neo4j）+ 关键词混合。**核心价值不在检索而在写入时的冲突消解**——从源头解决"记忆里存了过时事实"。

### 2.6 Cursor / Windsurf —— IDE 类的双轨制

- **Cursor**：文件式 Rules（人工、常驻）+ 代码库 embedding 检索 + 对话内 Memories（自动生成摘要，语义检索按需注入）。
- **Windsurf Cascade**：**Memories（自动生成）** 与 **Rules（手动三级：全局/工作区/系统）** 双轨，与 Claude 的 Auto Memory / CLAUDE.md 是同一思路的产品化表达。

---

## 三、检索增强：透露与推测汇总

| 技术 | 使用者 | 状态 |
|---|---|---|
| 检索工具化（agentic retrieval） | ChatGPT、Claude、Letta | **确认**，已成共识 |
| 检索前 query 自包含改写 | ChatGPT（prompt 逆向） | **确认** |
| RRF 混合检索（向量+FTS） | Letta | **确认**（开源代码） |
| 检索失败静默 | ChatGPT | **确认**；Claude 侧透明可见 tool call |
| 预计算画像注入 vs 白板+自检索 | ChatGPT / Claude 各占一派 | **确认**，两流派并存 |
| 写入冲突消解（ADD/UPDATE/DELETE） | Mem0 | **确认**；ChatGPT 画像更新机制【推测】为后台批处理 |
| 后台/sleep-time 记忆整理 | Letta（开源） | **确认**；OpenAI 疑似同源思路【推测】 |
| 子代理上下文隔离 | Claude Code/Agent SDK、Manus | **确认** |
| 压缩保留优先级声明 | Claude Code（Compact instructions） | **确认** |
| 记忆基准评测（LoCoMo、MemBench 等） | 学术侧 | 研究阶段，产品方未公布自家分数 |

**综合判断**：记忆系统正分化为「**写入治理**」（何时记、记什么、怎么去重冲突）与「**读取编排**」（何时检索、检索什么、失败怎么办）两个独立子系统；对话粒度的摘要检索（ChatGPT 的 Recent Conversations）是比逐条 message 检索更经济的中间态；「静默失败」在 ChatGPT 上已引发用户投诉，对陪伴型 Agent 而言**透明 + 失败兜底话术**更合理。

---

## 四、对 Yuiro 的对照与借鉴

结合 `docs/memory-system.md` 的现状（L2 情景 + L3 事实/知识库、Retriever 四信号 RRF、`memory_prompt` 防御声明、md5 降级、记忆污染红线）：

### 4.1 已对齐的部分

- **RRF 多信号融合**：与 Letta 的混合检索方向一致，且已扩展到四信号（向量/FTS/新近度/显著性），领先多数产品的两路融合。
- **"记忆不约束当前行为、系统操作必须调工具"声明**：与 Claude「记忆是便签不是法律」及 ChatGPT 的记忆设计哲学同构，业界共识。
- **检索式注入 top_k 而非全量历史**：与主流一致。

### 4.2 缺失 / 待落地（按优先级）

1. **写入侧冲突消解（最高优先级）**：当前 `memory_writer` 每轮无脑写 L2，历史失败记录（如"要求系统操作→纯文字回复"）会经检索回灌并误导后续行为（记忆污染红线）。借鉴 Mem0：写入前让轻量 LLM 判断「是否值得记 + 与已有记忆是否冲突」，输出 ADD/UPDATE/SKIP，从源头拦截污染，比 `memory_prompt` 防御更根本。
2. **压缩保留优先级声明**：借鉴 Claude Code `Compact instructions`——压缩时声明「优先保留用户性格/偏好/未完成事项，可丢弃工具调用原文」。
3. **双通道记忆（bio 式）**：短事实列表（显式、可见、可删、前端可视化"它记得我什么"）+ 后台低频画像提炼分层。桌宠场景下可视记忆天然契合陪伴产品的信任建设。
4. **Sleep-time 后台整理**：桌宠有天然空闲期，后台整理记忆（去重、合并、时效衰减）比每轮同步写更省且不卡聊天链路——与「记忆检索超时卡死聊天」的教训一致：**记忆操作永远不阻塞主循环**。
5. **上下文工程细节**：Agent 长任务场景可借鉴 Manus 的 append-only + KV-cache 命中率意识、todo 复述对抗注意力衰减、保留错误信息让模型自纠。

---

## 五、参考资料

- Manus：Context Engineering for AI Agents: Lessons from Building Manus（官方博客，2025-07）
- MemGPT 论文：Towards LLMs as Operating Systems（arXiv:2310.08560）；letta-ai/letta 源码
- ChatGPT 记忆逆向：zebang.li《拆解 ChatGPT 在 2026 年的记忆机制》；GDPR 导出论文（arXiv:2602.01450）；OpenAI Memory FAQ
- Claude Code：Anthropic 官方文档（Memory / Compact / Hooks）；社区 harness 逆向分析
- Mem0：开源框架文档与论文
- 生成式智能体：Generative Agents: Interactive Simulacra of Human Behavior（arXiv:2304.03442）
