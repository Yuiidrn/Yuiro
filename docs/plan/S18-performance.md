# S18 — Performance（Agent → Performance Intent → 表演）

> 状态：**进行中**（2026-09-13）。
> 来源：`docs/spec/roadmap.md` Era 1 Perform + `docs/spec/阶段性总评和后续方向.md` §32
> （"用户说我成功了，Yuiro 突然庆祝" = `Agent → Performance Intent → AvatarRuntime → Celebrate`，
> **而不是**往 Agent 里写 `if success: celebrate`）。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 18
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    Performance —— 它会表演（不只是表情跟着变）
SURPRISE: 你说"搞定了"，它自己庆祝；任务跑完，它也庆祝
ARCHITECTURE:
  Agent / Event ──语义名──▶ PerformanceResolver ──▶ AvatarIntent(expression+motion)
                                                        │
                                                        ▼
                                          AvatarRuntime ──▶ avatar:intent ──▶ Live2D
  关键约束（spec）：
   1. 不把 LLM 输出绑到具体 motion（解析器 + 配置决定用哪个资源）；
   2. 不在 Agent 里写 if success（表演由事件或 LLM 语义触发）。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 设计

| 层 | 职责 | 文件 |
|---|---|---|
| 表演库 + Resolver | 语义名 → `Performance`（expression 经 `expression_map`、motion 经 `motion_map`） | `avatar/performance.py` |
| 执行 | `AvatarRuntime.perform(session_id, name)` → `AvatarIntent(ACTION)` 广播；到期自动允许情绪回落 | `avatar/runtime.py` |
| 语义触发 | LLM 调 `avatar_perform` 工具（"用户报喜 → celebrate"） | `tools/avatar_tool.py` |
| 事件触发 | `TaskRuntime` 的 `task.completed` → `perform("celebrate")`（main.py 订阅） | `main.py` |
| Gallery | `GET /debug/avatar/performances` + `POST /debug/avatar/perform/{name}` | `debug_api.py` |
| 配置 | `[persona.motion_map]`（情绪/表演名 → 动作组；留空则只演表情） | `config.py` / toml |

## 顺带修复的两个真问题（测试暴露）

1. **ACTION 永久压制 EMOTION**：`_apply` 只比优先级、不看时效，一旦 ACTION 生效，
   后续情绪表情会被静默拦截（S05 引入，因当时无 ACTION 调用方而未暴露）。
   → 一次性意图带 `duration_ms`，到期即不再压制；`push_action` 同样改为一次性。
2. **TaskRuntime 事件从未发布**：`AgentEvent` 的 `session_id` 为必填，`_emit` 漏传 →
   `TypeError` 被 `except Exception: pass` 吞掉（S08 引入，事件静默失效）。
   → 由 `_active` 反查会话并传入；两者均已加回归护栏。

## 交付报告（2026-09-13 完成）

### Changed files

**新增**：`engine/yuiro/avatar/performance.py`、`engine/yuiro/tools/avatar_tool.py`、`engine/tests/test_performance.py`（12 个用例）

**修改**：

| 文件 | 改动 |
|---|---|
| `engine/yuiro/avatar/runtime.py` | `perform()`（命名表演）+ `performances()` + `update_motion_map()`；**一次性意图到期仲裁**（`duration_ms` + `_current_at`）；`push_action` 改为一次性；`state()` 增加 performances/performed |
| `engine/yuiro/avatar/__init__.py` | 导出 `Performance` / `PerformanceResolver` / `DEFAULT_PERFORMANCE_MS` |
| `engine/yuiro/config.py` + `config.toml` + `config.example.toml` | 新增 `motion_map`（情绪/表演名 → 动作组）；表情映射注释更新为"已确认" |
| `engine/yuiro/agent/__init__.py` | `build_agent_loop(avatar_getter=...)` → 注册 `AvatarPerformTool`（延迟绑定） |
| `engine/yuiro/main.py` | avatar 装配带 `motion_map`；`TaskRuntime(events=events)`；**订阅 `task.completed` → `perform("celebrate")`** |
| `engine/yuiro/task/runtime.py` | `_emit` 补必填 `session_id`（反查 `_active`）——修复"事件从未发布" |
| `engine/yuiro/debug_api.py` | 热重载同步 `motion_map`；`GET /avatar/performances` + `POST /avatar/perform/{name}`（Performance Gallery） |

### 冒烟证据

```
LIBRARY: ['angry','bored','celebrate','comfort','excited','greet','happy','idle','sad','surprise','thinking']
PERFORM celebrate: {priority: 3, emotion: 'excited', expression: 'expression4', motion: 'TapBody', duration_ms: 2600}
EMOTION blocked during action: False            ← 表演期间正确拦截
EMOTION after expiry: True -> expression2       ← 到期后正确回落（修复 1）
[event] [sess-1] task.created / task.updated / task.completed   ← 事件真的发出（修复 2）
EVENT: task.completed | session: sess-1
AFTER TASK: {source: 'system', expression: 'expression4', motion: 'TapBody'}   ← 事件驱动庆祝
STATE: {'sessions': 2, 'performances': 11, 'performed': 2, ...}
```

### 两个真问题（本次修复，均已加回归护栏）

1. **ACTION 永久压制 EMOTION**（S05 遗留）：`_apply` 只比优先级不看时效 → 一次性表演
   会永久拦截后续情绪表情。现按 `duration_ms` 判定到期。
2. **TaskRuntime 事件从未发布**（S08 遗留）：`AgentEvent.session_id` 必填而 `_emit` 漏传 →
   `TypeError` 被 `except: pass` 吞掉。现已由 `_active` 反查会话。

> 这两个问题都属于"**静默失败**"类——不冒烟就永远发现不了（前者表现为"表情突然不跟情绪变了"，
> 后者表现为"事件日志里从没有 task.* 事件"）。S18 的冒烟脚本正是为此而写。

### Tests

- 新增 **12 个**全部通过；全量回归 **229 passed / 5 failed / 1 error**（失败集与基线一致）；
- `avatar/`、`tools/avatar_tool.py`、测试文件 ruff 零告警；前端 `pnpm typecheck` 通过。

### DoD 对照

- [x] 表演库（11 个语义名）经 Resolver 解析为 expression + motion（**配置驱动**，未硬编码到 Agent）
- [x] `AvatarRuntime.perform` 广播 `avatar:intent`（ACTION 优先级 + 时长）
- [x] LLM 语义触发（`avatar_perform` 工具）；事件触发（`task.completed` → celebrate）
- [x] 一次性表演到期后情绪可回落（回归护栏）
- [x] Performance Gallery 后端就绪（列表 + 点击即表演）
- [x] 人设热重载同步 `motion_map`；回归通过

### Human Acceptance（待人工）

1. 说「**我终于把那个 bug 修好了！**」→ 预期它调 `avatar_perform(celebrate)` 并做动作（日志 `[表演] celebrate → …`）；
2. 说「**帮我一步步整理下载文件夹**」并把任务推进到完成 → 预期自动庆祝（日志 `[任务完成]` 紧跟 `[表演]`）；
3. 访问 `GET /debug/avatar/performances` 看表演库；`POST /debug/avatar/perform/greet` 现场触发一次；
4. 若某个表演的动作不合适：在 `config.toml` 的 `[persona.motion_map]` 调（如 `celebrate = "TapBody"`）。

### 风险 / 遗留

- **前端 Performance Gallery UI** 未做（后端 API 已就绪，可用 curl / 调试台）；
- 动作语义（13 个 TapBody）未逐一确认 → 表演的动作部分目前是"先动起来"，待你 Alt+M 确认后
  在 `motion_map` 精调（**这是本次唯一需要你输入的地方**）；
- 未做 Gaze（视线跟随）与 Voice style 的表演联动（spec 的表演包还包含这两项，属后续 Wave）；
- 表演与语音节奏的时序对齐（说话中不做大动作）未做，当前靠优先级天然错开。
