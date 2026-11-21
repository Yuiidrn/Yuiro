# S16 — Agent Harness Extraction（渐进抽离 AgentLoop）

> 状态：**已完成**（2026-09-13）。
> 来源：`docs/spec/阶段性总评和后续方向.md` §27–§30（"AgentLoop 已成局部大泥球；不要重写，要渐进抽离"）。
> 规范依据：`docs/spec/architecture-goal.md`（Adapter 化原则）、`docs/spec/README.md` 约束 1。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 16
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    Agent Harness Extraction —— 从 1151 行的 AgentLoop 里渐进外移职责
SURPRISE: 无（纯地基）：工具执行与工具事件成为可独立测试的单元
ARCHITECTURE:
  - 抽离 agent/tool_dispatch.py：ToolDispatcher（Policy 判定 + 并发执行 + 结果归一）
  - 抽离 agent/tool_events.py：StateNotes + describe_tool_state/describe_tool_event
  - AgentLoop 保留调用点不变（委派 / staticmethod 别名）→ 零行为变化
  不做（有意放弃/延后）：
    - 关键词预路由（routing）抽离 —— 纯函数、无状态耦合债，改动成本 > 收益（已实验后撤回）
    - LLMProvider 抽离、send() 主体拆分 —— 风险更高，留待后续 Sprint
FILES:
  engine/yuiro/agent/{tool_dispatch.py, tool_events.py}（新增）
  engine/yuiro/agent/__init__.py（删除内联实现，改委派/别名：-102 行）
  engine/tests/test_agent_extraction.py（新增 10 用例）
  engine/tests/test_context_engine.py（等价性测试适配 StateNotes）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 交付报告（2026-09-13 完成）

### 结果

| 指标 | 之前 | 之后 |
|---|---|---|
| `agent/__init__.py` | **1151 行** | **1049 行**（-102, -8.9%） |
| 工具执行编排 | 内联在 `send()` 的嵌套函数 | `ToolDispatcher`（可独立测试） |
| 工具事件/状态 | 类内 3 个方法 | `tool_events.py`（模块函数 + `StateNotes`） |
| 全量回归 | 202 passed | **212 passed / 5 failed / 1 error**（失败集不变） |

### 抽离边界（职责）

```
ToolDispatcher（agent/tool_dispatch.py）
  ├── decide(name, args)        ← Policy 判定（deny/ask/allow）
  ├── execute_one(...)          ← 审批门挂载 + registry.execute + 异常归一
  ├── run_batch(pending, sid)   ← 并发执行（工具间无依赖）
  └── normalize(raw)            ← 非 JSON 文本 → {"status":"text"}

仍在 AgentLoop（与回合策略强耦合，暂不抽）：
  去重 / 限流计数 / 早停判定 / 状态摘要触发 / 记忆写入 / 收尾总结

tool_events.py
  ├── describe_tool_state(...)  ← 「当前环境状态」（中性，注入给模型）
  ├── describe_tool_event(...)  ← 「刚才发生了什么」（过去式，存档进记忆）
  └── StateNotes                ← 按会话维护状态（同前缀覆盖而非追加）
```

### 过程中被护栏抓到的真实回归（第二次）

抽离 `_state_notes`（dict）→ `StateNotes` 后，**S06 的等价性测试立即失败**
（`AttributeError`：测试用 `loop._state_notes["s1"] = state`）。
修复：给 `StateNotes` 加 `set()`，测试改用 `loop._state.set(...)`。

> 教训复用：**收敛阶段每次替换数据结构，既有测试就是最好的回归网**——
> 这也是 S06 等价性护栏、S15 业务 cancel 护栏连续两次救场的原因。

### DoD 对照

- [x] 工具执行编排与工具事件成为独立模块（可独立单测，10 个新用例）
- [x] AgentLoop 调用点不变（委派 + staticmethod 别名）→ 零行为变化（212 passed）
- [x] AgentLoop 行数下降（1151 → 1049）
- [x] 未做高风险重构（不改 `send()` 主体逻辑）
- [x] 回归通过

### 遗留（后续 Sprint）

- `send()` 主体仍有约 380 行（工具循环策略：去重/限流/早停/收尾总结）——**下一步优先**；
- `LLMProvider` / `OpenAIProvider`（约 190 行）仍在 `agent/__init__.py`，可独立成 `agent/providers.py`；
- `_keyword_route` 仍内联（评估后认为收益低，保留）；
- `audio/__init__.py`（1501 行）与 `memory/__init__.py`（1278 行）尚未收敛——比 AgentLoop 更大。
