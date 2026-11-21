# S43 · 会话生命周期（Session ownership 补完）

**触发**：用户看日志发现 `WS /ws/control 连接建立 session=...` 不断出现
（6 个不同 session），并指出"**前端没有选择加载页协同**"。

观察准确，而且根因比表面严重。

---

## 一、根因：两层缺陷叠加

### 后端：`close()` 全项目零调用

```python
def _maybe_suspend(self, session):
    """两条通道都断开 → 挂起（保留内存，允许进程内 resume）"""
    if session.control_ws is None and session.audio_ws is None:
        session.state = SessionState.SUSPENDED   # ← 只改状态，仍留在 _sessions 里
```

意图是"保留内存以便 resume"，但**没有任何回收策略** —— `_sessions` 只增不减，
每个会话都带着 history / StateNotes / context 快照常驻内存。

### 前端：`sessionId` 只活在内存

前端**其实已经做了 resume**（断线重连带 `?session=`），但 `sessionId` 是个内存 ref ——
**页面刷新 / Vite 热更新一重载就归零**，于是新建。开发态尤其容易攒。

> 用户贴的日志来自**开发态**，热重载是"制造新会话"的主要来源；
> 但"后端不回收"是独立于环境的真缺陷 —— 生产态刷新页面同样会丢上下文。

---

## 二、实现：**回收 ≠ 丢失**

核心设计：**内存里回收，事件日志留盘，需要时复活**。
这样"内存不涨"与"会话不丢"才能兼得 —— 只做前者会丢数据，只做后者会涨内存。

| # | 改动 | 位置 |
|---|---|---|
| 1 | `sessionId` **持久化到 localStorage** | `shell/App.vue` |
| 2 | **会话列表面板**（Alt+S）：切历史会话 / 开新会话 | `shell/App.vue` |
| 3 | `sweep()` 超时回收 + `archive()` 主动归档 | `runtime/session.py` |
| 4 | `revive()` **从事件日志复活** + `list_sessions()` 一览 | `runtime/session.py` |
| 5 | `get_or_create` 改为**内存 → 磁盘复活 → 新建** | `runtime/session.py` |
| 6 | 装配顺序调整（SessionManager 需要 EventLog） | `main.py` |
| 7 | 5 分钟定时 sweep（否则回收只能手动触发 = 没做） | `main.py` lifespan |
| 8 | `GET /api/sessions` + `POST /api/sessions/archive` | `debug_api.py` |

### 两个刻意的保守选择

1. **回收只认"两条通道都断开 + 已挂起 + 超过 TTL"** —— 有连接的会话绝不能动，
   哪怕它很久没说话。**宁可漏收，不可误收。**
2. **复活后先置 `SUSPENDED`**，等 `attach_*` 真正接上再转 `ACTIVE` ——
   否则会留下一个"看起来有连接"的幽灵会话，`sweep` 永远收不掉它。

---

## 三、架构评估：距离蓝图还差什么

### 蓝图判据（`architecture-goal.md` §2）

> 决定系统能否扩展的**不是 Agent 有多聪明，而是谁拥有这些**。

| Ownership | 蓝图要求 | S43 前 | S43 后 |
|---|---|---|---|
| **Session** | SessionRuntime + **事件持久化** + create/resume/**archive** | 🟡 有运行时，无生命周期 | ✅ |
| Context | ContextEngine | ✅ | ✅ |
| Task | TaskRuntime + Task Journal | ✅ | ✅ |
| Permission | Capability View + Policy + Approval | ✅ | ✅ |
| Cancellation | `Session.cancel()` 统一入口 | ✅ | ✅ |
| Tool visibility | Capability View 动态过滤 | ✅ | ✅ |

**六项 ownership 现已全部达成。**

### 六个一等实体（§1.2）

Session ✅ · Task ✅ · Event ✅ · Intent ✅ · Artifact ✅ · Capability ✅

### 仍缺的部分（诚实清单）

| 缺口 | 蓝图出处 | 影响 | 何时做 |
|---|---|---|---|
| **InteractionMode / TaskClassifier**（CHAT/ACTION/PLAN/TASK/BACKGROUND） | §3.5 | **所有输入走同一条 Chat Turn 路径**，靠关键词预路由 + nudge 事后补救 —— 这是"指哪打哪"的**架构层原因** | 建议下一个 |
| Plugin / Skill 运行时 | §1.1 | 扩展性 | 有真实扩展需求时 |
| Sandbox / OS 层 | §1.1 | 隔离性 | v1.0 明确不做 |
| Presence / Personal Brain | 评估表 | 15% / 10% | 依赖真实使用数据 |

### 结论：**可以继续增量功能了**

五个 Runtime（Session / Event / Context / Agent / Task）与 Capability/Policy 全部就位，
新增能力只需加工具/加描述，**不必动内核** —— S33（文件事务）、S41（歌单匹配）
都是纯"加能力"且未触碰 Runtime，证明接口是稳的。

**唯一还会持续"漏水"的地方是 InteractionMode** —— 每加一种交互形态就得在提示词或
nudge 上再补一条，这正是"打地鼠"的结构性来源。S42 的 `TurnState` 解决的是
**路径内部的显式化**，而 InteractionMode 解决的是**路径之前的分流**：只有前者，
等于把一条路修得更清楚，但所有车还是必须走同一条路。

---

## 四、验证

- 新增 `tests/test_session_lifecycle.py`（14 条）：回收的保守性 / 复活还原身份与时间 /
  解析优先级 / 归档不删日志 / 一览合并内存与磁盘
- 全量回归 **500 passed / 5 failed**（失败集自 S01 未变）
- 前端 `pnpm typecheck` 通过

### 待人工验证

1. **重启引擎**（新 API 与新逻辑需要重启才生效；
   实测未重启时 `GET /api/sessions` 返回 404 —— 这正是"跑的是旧代码"的信号）
2. 重启后：`Alt+S` 打开会话列表 → 应看到历史会话（含此前积攒的那 6 个）
3. **刷新页面**（开发态直接按 F5）→ 会话 id 应保持不变（不再新建）
4. **重启引擎后再刷新** → 应看到日志 `从事件日志复活会话 xxxx`
5. 观察一段时间后日志里 `回收 N 个挂起会话` 应出现（TTL 30 分钟 + 5 分钟扫描）

---

## 五、遗留

| 项 | 说明 |
|---|---|
| `AgentLoop._history` 仍是内存 | 复活会话后**多轮原文历史会丢**（记忆/事实是持久化的，不受影响）。若需要更完整的恢复，得从 EventLog 重放 `user.message` 重建 —— 但 `history_inject` 默认关闭，收益有限，先不做 |
| 前端切会话不清引擎侧状态 | `switchSession` 只换了 id 并重连；引擎侧的 history 属于各自会话，无需清理 |
| 会话名 | 列表目前只显示 id 前 8 位与时间。可考虑用会话首句自动命名，等真实使用后再定 |
