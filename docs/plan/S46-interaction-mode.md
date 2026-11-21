# S46 · InteractionMode（蓝图最后一个结构性缺口）

**背景**：`architecture-goal.md` §3.5 的原话是「**不能把所有输入当成同一种 Chat Turn**」。
在此之前，所有输入都走同一条 `AgentLoop.send()` 路径，靠关键词预路由和 nudge 事后补救 ——
这是"新增一种交互形态就得再补一条规则"的结构性原因，也是"打地鼠"的最后一块土壤。

---

## 一、spec 要求的五种形态

```
CHAT       简单问题
ACTION     简单工具操作（"打开网易云音乐"）→ Immediate Action
PLAN       复杂敏感任务 → Plan → Approval → Task
TASK       多步执行（"整理毕业设计资料"）→ Long-running Task
BACKGROUND 独立耗时任务 → 后台执行 + 进度通知
```

---

## 二、本 Sprint 的范围：**刻意保守**

分类错误会让输入**走错路径**。最危险的方向是"把真正想操作的用户判成 CHAT" ——
那等于**削减了能力**。所以本次遵守两条原则：

1. **不确定 → 倾向 CHAT**（CHAT 不改路径、工具照常可见，误判不削减能力）；
2. **分类只用于加速与约束，绝不用于削减能力** —— 所有模式都保留完整工具可见性，
   **唯一例外是 ACTION 的收尾轮**（那时它已经执行完了，不需要再动工具）。

| 形态 | 本次是否改变行为 | 说明 |
|---|---|---|
| **ACTION** | ✅ **是**（唯一） | 收尾轮**不再暴露工具**（Immediate Action） |
| CHAT | ❌ 否 | 路径照旧；分类只用于观测 |
| PLAN | ❌ 否 | 沿用现有 approval 门 |
| TASK | ❌ 否 | 沿用 TaskRuntime 驱动 |
| BACKGROUND | ❌ 否 | **尚未实现**，仅识别与记录 |

---

## 三、ACTION 落地了什么：「立即执行」

### 问题

预路由命中的是**极明确的单步指令**（"下一首"/"暂停"/"打开记事本"），
但它**仍走完整的多轮循环**。实测日志：

```
第 1 轮：netease_play {'keyword': 'LIFE'} → {"status":"ok","played":true,…}
第 2 轮：netease_play {'keyword': 'LIFE'} → {"status":"done","note":"该操作已完成，无需重复执行"}
```

模型在工具**已经成功**之后，**又调了一次去"确认"** ——
白烧一轮 token，让用户多等一次。（去重机制是闭环的、不会死循环，但这一轮纯属浪费。）

### 修复

ACTION 的**收尾轮**（`immediate and tool_ran`）调用 LLM 时传 `tools=None`：

```python
_closing = immediate and tool_ran
stream = self._llm.stream_text(
    messages,
    tools=None if _closing else tool_schemas,
    tool_choice="auto",
)
```

**用 `tools=None` 而不是 `tool_choice="none"`**：后者要求 `tools` 必须存在，
前者直接不发工具表 —— 兼容性更好（见 `OpenAIProvider.stream_text`：`if tools:` 才加）。

**效果**：ACTION 回合固定为「预路由执行 → 收尾转述」两次调用，**结构上不可能重复调用**。

---

## 四、为什么这是"架构"而不是又一个补丁

| 维度 | 打补丁 | 本改造 |
|---|---|---|
| 手段 | 再写一条提示词/再加一个 nudge | **让"输入类型"成为显式概念**（可观测、可单测） |
| 重复调用 | 靠提示词劝它别重复 | **收尾轮不给工具，结构上做不到** |
| 新增形态 | 在 `send()` 里加分支 | 加一个枚举值 + 一个 `describe()` |

**从"劝模型别这么做"变成"让模型做不到"，是这一层的本质区别。**

---

## 五、验证

- `tests/test_interaction_mode.py`：分类的**两条安全性质**
  （不确定→CHAT、预路由→ACTION 优先）+ 两条**行为断言**：
  - `test_action_closing_round_hides_tools` —— ACTION 只调一次 LLM 且**不带工具**
  - `test_chat_keeps_tools_visible` —— CHAT **保留工具可见性**（不削减能力）
- 全量回归 **522 passed / 5 failed**（失败集自 S01 未变）

## 六、遗留

| 项 | 说明 |
|---|---|
| CHAT 的路径分化 | 现在与其它形态同路径（`describe()` 里如实标注"暂未分化"）。可考虑：CHAT 时收紧工具表以省 token —— 但要先有"误判率"数据 |
| BACKGROUND | 未实现。需要"后台任务 + 进度通知"，属于新能力而非路径调整 |
| PLAN / TASK 的显式化 | 现已识别，但走的仍是既有机制（approval 门 / TaskRuntime）。后续可让它们真正读 `InteractionMode` 而不是各自判断 |
| 分类准确率 | 目前判据是**结构性用词**（多步词 / 计划词），未用 LLM 分类 —— 因为误判代价不对称，宁可保守 |

> **至此，蓝图 `architecture-goal.md` §2 的六项 ownership 与 §3.5 的 InteractionMode 均已落地**
> （后者为"识别 + ACTION 路径分化"的最小可用形态）。剩余未做项集中在
> Plugin/Skill 运行时、Sandbox/OS 层、Presence/Personal Brain —— 均属"需要真实需求或数据驱动"。
