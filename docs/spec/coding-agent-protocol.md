# Yuiro Coding Agent Protocol —— 开发协议与护栏

> 本文件规定"每次接到具体任务时怎么做"：五要素、七步流程、母 Prompt、架构护栏、测试三层、报告格式。
> 目标见 [architecture-goal.md](architecture-goal.md)，优先级见 [roadmap.md](roadmap.md)。
> 本仓库 AGENTS.md 中的环境/命令/红线与本文件并行有效，冲突时以本文件为准（环境类以 AGENTS.md 为准）。

---

## 1. 开发周期：固定五层

任何任务都不要从"改代码"开始：

```
L1 Product Scenario      用户最终看到什么（体验）
L2 Observable Behavior   可观察行为（可测的现象）
L3 Architecture Increment 这次允许新增的最小架构能力
L4 Implementation        具体代码
L5 Verification          Unit + Scenario + 指标
```

❌ 错误任务："重构 Memory 系统。"
✅ Yuiro 任务："实现'Yuiro 能在三天后回忆起用户主动告诉它的事情'。"

```
Scenario → Memory Recall → Memory Runtime → 具体代码 → 三日记忆测试
```

### 1.1 每个任务固定五要素

1. **Goal**：我要什么；
2. **Scenario**：用户最终看到什么；
3. **Architecture Increment**：这次允许新增什么架构能力（写清"不新增什么"更重要）；
4. **Tests**：如何证明真的完成；
5. **Definition of Done**：什么条件下才能结束。

---

## 2. 七步执行流程

### Step 1 — Understand

```
Read: 当前架构（docs/spec/ + ARCHITECTURE.md）
      relevant files（用检索/语义工具定位，不靠猜）
      existing tests
      existing interfaces
```

### Step 2 — Plan

必须先回答：

```
What changes?
Why?
What does NOT change?
What is the smallest implementation?
是否需要新增 Event / Intent / Hook？
是否涉及 Cancellation / Generation / Lifecycle？
是否需要 Trace？
是否可以 Replay？
是否扩大 Stable Kernel？
```

### Step 3 — Implement

只修改任务需要的范围。禁止顺手重构、顺手重命名、顺手"优化"无关代码。

### Step 4 — Test

至少 `Unit + Scenario` 两层（见 §5）。新增行为必须有回归测试。

### Step 5 — Measure

涉及性能（延迟 / 内存 / token / 成功率）必须给 `before vs after`。
不允许"感觉变快了"。

### Step 6 — Review

必须回答：

```
Architecture impact:    （属于 Runtime / Intelligence / Capability / Embodiment / UI 哪层）
New abstractions:       （新增了什么抽象，为什么必须有）
Potential technical debt:
Backward compatibility: （旧行为是否保留）
```

### Step 7 — Commit / Report

一个 Scenario 尽量一个逻辑提交：

```
feat(memory): add explicit memory recall
```

而不是 `refactor: improve everything`。报告格式见 §8。

---

## 3. 修改前的判断顺序（不可跳过）

### 3.1 技术判断

```
1. 当前代码是否已经解决这个问题？
2. 能否抽象现有实现？
3. 能否通过 Adapter 接入新 Runtime？
4. 能否增量迁移？
5. 最后才考虑重写。
```

### 3.2 价值判断

每次修改前必须回答"这个修改解决的是哪一类问题"：

```
A. 功能缺失？
B. Runtime 生命周期问题？
C. 并发 / cancellation 问题？
D. 架构耦合问题？
E. 安全问题？
F. 可维护性问题？
```

如果只是为了让代码"看起来更高级"，**不要修改**。

### 3.3 第一性原则

> **"这个东西是否最终让 Yuiro 更像一个有连续生命状态的角色？"**

- 是 → 做；
- 可能以后有用 → 放 backlog；
- 只是因为"现代 Agent 都这么设计" → 暂缓；
- 只是为了架构漂亮 → **不要做**。

---

## 4. 架构护栏

### 4.1 四条 Architecture Rules（Must）

1. **业务代码不得直接依赖具体 LLM Provider**：`Agent → LLM Interface → Provider`，不是 `Agent → OpenAIProvider`；
2. **业务代码不得直接控制 Live2D**：`Agent → Performance/Avatar Intent → Avatar Runtime → Live2D`；
3. **取消必须具有传播语义**：`Task Cancel → Agent Cancel → LLM Cancel → TTS Cancel → Avatar Cancel`；
4. **Memory 是独立能力**：Agent 可以使用 Memory，但 Memory 逻辑不得散落在 AgentLoop 里。

### 4.2 通用刹车（每个任务开始前默念）

```
Before modifying code:
1. Inspect the existing implementation.
2. Identify the smallest safe change.
3. Do not introduce abstractions without a concrete use case.
4. Do not rewrite working subsystems unless explicitly requested.
5. Preserve backward compatibility whenever practical.
6. Run relevant tests before and after modification.
7. Report architectural impact.
```

尤其第 4 条：**Do not rewrite working subsystems unless explicitly requested.**

### 4.3 禁止事项（12 条工程护栏）

1. 不要为局部问题重写整个架构；
2. 未经明确批准不引入新框架；
3. 不复制既有抽象；
4. 不把 Agent 逻辑耦合到 Live2D 实现；
5. 不把 Agent 逻辑耦合到具体 LLM Provider；
6. 不把长期记忆逻辑放进 AgentLoop；
7. 不把模型人格逻辑放进 Memory 层；
8. 不把长期事实知识存进模型权重；
9. 不添加无 lifecycle / cancellation 处理的后台自主行为；
10. 不添加无测试场景的功能；
11. 不因为新架构更干净就删除既有行为；
12. 非必要不大范围重命名代码。

### 4.4 Harness 时代新增护栏

13. **Event ≠ Hook ≠ Intent**：不把三种东西混成一个 EventBus；
14. **Context 是稀缺资源**：不把工具 / Skill / 记忆全文无差别塞进 prompt；大结果走 Artifact Store + 摘要；
15. **Capability ≠ Architecture**：不要因为参照系有 subagent / plugin / background 就优先做它们；
    优先复制控制结构（Session / Context / Task / Permission / Cancellation ownership）；
16. **不随意 spawn Subagent**：Subagent 挂 TaskRuntime，只在 context 太大 / 可并行 / 需不同能力权限 / 需独立验证时使用；
17. **不引入 DSH 式 "Everything is Plugin"**；内核语义（Session / Generation / Cancellation / Event schema / Security policy）不可插件化；
18. **不照搬 coding agent 的产品语义**（Git worktree / Build 角色 / CLI 交互），必须转换成 Desktop Task / Transaction 语义。

---

## 5. 测试体系：三层

```
Unit Test        工程正确
Scenario Test    行为正确
Showcase Test    真的惊艳
```

### 5.1 Unit

```
Memory retrieval / Tool parser / Cancellation / Event dispatch
```

### 5.2 Scenario

```
Barge-in / Memory recall / Tool failure / Task recovery
```

Scenario 是"Yuiro 的人格行为测试"，落盘为剧本：

```
scenarios/memory/three_day_recall.yaml
scenarios/voice/barge_in.yaml
scenarios/agent/tool_failure.yaml
scenarios/avatar/emotion.yaml
scenarios/showcase/...
```

### 5.3 Showcase（最有意思的一层）

自动运行整个故事：

```
Scenario: three_day_memory_001
Day 1：告诉 Yuiro 一件事情
Day 3：重新询问
Expected: Yuiro remembers X
Actual:   Yuiro remembered X ✓
```

配合 Trace / Replay 形成开发闭环：

```
Interaction → Trace → Save → Replay（新 Runtime / 新 LLM）→ Compare
```

### 5.4 必须覆盖的 Race Conditions

```
LLM response arrives while user starts speaking
TTS segment 2 arrives after interrupt
Tool returns after Agent cancellation
Memory consolidation finishes after session reset
Avatar animation callback after generation invalidation
Approval approved after task cancelled
```

全部要求：**NOT corrupt current state**。

---

## 6. 通用母 Prompt（英文模板，可直接用于任务开头）

```
You are the primary implementation engineer for the Yuiro project.

Yuiro is evolving incrementally toward an embodied personal agent harness:
- General Agent Harness (Session / Event / Context / Task / Capability / Cancellation)
- Realtime Embodiment Runtime (Voice / Live2D / Emotion / Presence)
- Long-term Relationship Memory
- Safe Desktop Capabilities (SystemDaemon + Policy + Approval + Sandbox)

Your role:
- inspect the existing codebase
- implement the requested scenario
- preserve existing working behavior
- introduce only the minimum architecture required
- write regression tests
- measure performance when applicable
- document meaningful architectural changes

The human owner is responsible for:
- product direction / experience design / personality
- visual & aesthetic decisions / final acceptance / prioritization

Do NOT perform broad rewrites unless explicitly requested.

Development principle:
PRODUCT SCENARIO → OBSERVABLE BEHAVIOR → MINIMUM ARCHITECTURE INCREMENT
→ IMPLEMENTATION → TEST → MEASURE → REVIEW

Before coding:
1. Inspect the relevant existing implementation.
2. Identify existing abstractions that can be reused.
3. Identify the smallest safe change.
4. Explicitly list files you expect to modify.

During coding:
1. Preserve provider interfaces where practical.
2. Preserve existing behavior.
3. Avoid speculative abstractions.
4. Keep cancellation and lifecycle semantics explicit.
5. Keep external integrations behind adapters/interfaces.

After coding:
1. Run relevant tests.
2. Add regression tests for the new behavior.
3. Report changed files.
4. Report architecture impact.
5. Report remaining risks.
6. Report before/after performance if relevant.

Definition of Done is determined by:
- user-visible behavior
- automated tests
- architectural correctness
- performance / regression criteria
```

### 6.1 禁止事项 Prompt（附在母 Prompt 之后）

```
YUIRO ENGINEERING GUARDRAILS

Do NOT:
1. Rewrite the entire architecture to solve a local problem.
2. Introduce a new framework without explicit approval.
3. Duplicate an existing abstraction.
4. Couple Agent logic directly to Live2D implementation.
5. Couple Agent logic directly to a specific LLM provider.
6. Put long-term memory logic inside the AgentLoop.
7. Put model-personality logic inside the Memory layer.
8. Store long-term factual knowledge in model weights.
9. Add background autonomy without explicit lifecycle/cancellation handling.
10. Add a feature without a testable scenario.
11. Remove existing behavior merely because a new architecture is cleaner.
12. Rename large portions of the codebase without necessity.
13. Merge Event / Hook / Intent into one bus.
14. Spawn subagents without TaskRuntime ownership.
15. Dump full tool results / skills / memory into the LLM context.
```

---

## 7. 报告与验收

### 7.1 每次交付必须报告

```
changed files
architecture impact
remaining risks
before/after metrics（若涉及性能）
tests added（Unit / Scenario）
```

### 7.2 Human 验收（不要只看 pytest passed）

1. 选择 Surprise → 2. 定义体验 → 3. 确定优先级 → 4. 审核 Agent Plan → 5. 观察实现
→ 6. **坐在桌前真的和 Yuiro 说话（运行 Showcase）** → 7. 决定下一步。

### 7.3 每次修改的最终判据

```
如果：Architecture sophistication ↑ 而 Experience ↓ → 失败
如果：Experience ↑ 且 Architecture ↑ 且 Reliability ↑ → 优秀 Sprint
```

四条曲线应同时向上：`Experience / Intelligence / Embodiment / Reliability`。

---

## 8. 提交策略

- 一个 Scenario 尽量一个逻辑提交；提交信息用 `feat|fix|refactor(scope): summary`；
- 提交前跑：引擎 `pytest tests/ -q`（在 `engine/` 内，用 venv2）、壳层 `pnpm typecheck`、
  C++ 变更 `cmake --build build --target yuiro_tests` + 运行 `yuiro_tests.exe`；
- 涉及运行时行为的改动，必须附上 `vlog` 阶段日志（沿用仓库「链路日志分阶段定位」红线）；
- 未经用户明确要求，不执行 commit / push。
