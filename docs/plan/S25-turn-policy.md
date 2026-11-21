# S25 — `AgentLoop.send()` 回合策略抽离

> 状态：**已完成**（2026-09-13）。
> 收敛主线里**风险最高**的一块：`send()` 主体 ~380 行（去重 / 限流 / 早停 / 状态摘要 / 收尾总结）。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 25
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    回合策略抽离（TurnPolicy）—— 把"实测结论"变成可独立运行的护栏
SURPRISE: 无（纯地基；但引入 11 个针对实测坑位的回归护栏）
ARCHITECTURE:
  AgentLoop.send ──委派──▶ TurnPolicy（成功去重 / 失败限流 / 无进展早停）
                            │
                            └─ 每轮对话一个实例（状态与 AgentLoop 会话状态无关）
  边界：权限/并发/归一 → ToolDispatcher(S16)；状态摘要 → StateNotes(S16)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 抽离的三条实测结论（原文注释随代码一起搬运）

| 规则 | 由来（原注释） |
|---|---|
| **成功去重** `done` | "实测『打开网易云疑云』→ 纠正后仍反复 open 3 次" |
| **失败限流** `skipped` | "app_open 成功后 LLM 仍反复 app_focus 找不存在的窗口" |
| **无进展早停** | "实测 todo update 空转 6 轮" |

其中**最易被后人改坏的一条**：跳过（`skipped`）的轮次**不清除失败计数** ——
否则计数被反复清零、永远达不阈值、无限重试。已用专门用例锁死。

## 交付报告（2026-09-13 完成）

### Changed files

| 文件 | 改动 |
|---|---|
| `engine/yuiro/agent/turn_policy.py` | **新增**：`TurnPolicy`（key_for / skip_reason / skip_result / skip_trace / begin_round / note_result / progress_made） |
| `engine/yuiro/agent/__init__.py` | `send()` 内 4 处策略逻辑改为委派（`turn = TurnPolicy()`）；新增 import |
| `engine/tests/test_turn_policy.py` | **新增** 11 个用例 |

### 结果（诚实的收益评估）

- `agent/__init__.py` 净减 **约 19 行**（4 处替换 -45 行 + 注释/import +26 行）；
- **真正的收益不是行数，而是可测试性**：三条靠实测发现的行为约束（此前只存在于
  一个 380 行长函数的注释里）现在有 **11 个独立护栏用例**，改动时能立刻发现问题；
- 行数收益有限的原因：`send()` 的复杂度主要在**回合流程本身**（LLM 流式、
  工具轮编排、收尾总结），而那部分与状态机强耦合，**不应为减行而硬拆**。

### Tests

- 新增 **11 个**全部通过；
- `test_agent_chat_reply.py`（send 行为护栏，34 个）+ `test_agent_extraction.py` 全绿；
- 全量回归见下（与基线逐项一致 → 抽离零行为变化）。

### DoD 对照

- [x] 回合策略独立成模块，可单独构造与测试（无 IO）
- [x] 三条实测约束逐条搬运（含"skipped 不清计数"这一反直觉点，有专门用例）
- [x] `send()` 行为零变化（`test_agent_chat_reply` 全绿 + 全量回归失败集未变）
- [x] 跳过结果文案 / 轨迹标注逐字保留（LLM 侧可见文案不变）

### 风险 / 遗留

- `send()` 主体仍有 ~360 行（LLM 流式 + 工具轮 + 收尾总结）；**进一步拆分风险高于收益**，
  暂不继续（如需再做，应先为"回合流程"建立端到端 scenario 护栏，而非从行数出发）；
- 收尾总结（`tool_ran and not assistant_text`）未抽离（与 `send` 的控制流强耦合）。
