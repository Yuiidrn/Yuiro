# S10 — 系统工具 Python 化 + SystemDaemon 降级为可选后端

> 状态：**已批准开工**（2026-09-12，Human 决策：采用"降级为可选后端"方案）。
> 性质：Capability & Execution 层重构（spec §4 CAPABILITY）+ spec 约束 9 的表述修订。
> 背景：C++ daemon 的"低延迟"论据不成立；"安全边界"价值未兑现（`policy.cpp` 仅 1.73 KB，
> 真正审批在 Python 侧）；规模失衡（40 KB C++ 源码 ↔ 1405 个构建文件）。
> 规范依据：`docs/spec/README.md` 约束 9、`docs/spec/architecture-goal.md` §3.x。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 10
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    系统工具 Python 化 —— 执行后端可切换（native 默认 / daemon 可选）
SURPRISE: 系统能力不再依赖 C++ 工具链；行为一致、可测试、可调试
USER EXPERIENCE:
  - 用户无感（工具名/参数/文案与原来一致）
  - 开发者收益：6 个系统工具可在 CI 里测试；无需 cmake/编译器即可用"动手"能力
ARCHITECTURE:
  - 新增 native/ 包：ops.py（Windows API + 标准库实现）+ backend.py（NativeBackend）
  - 统一后端协议：NativeBackend 与 SystemDaemonClient 同签名 call(tool, args, dry_run)
    → SystemActionResult（既有 dataclass，零改动复用）
  - SystemActionTool 支持 backend 注入（daemon= 兼容保留）
  - [systemd].backend = "native" | "daemon"（默认 native）；file_roots 可配置
  行为对齐：中文应用别名表 / 三级窗口查找 / dry-run 文案 / 文件路径边界 / 状态语义
  不做：不用 WinRT（now_playing/list_sessions 走 PowerShell 桥，尽力而为）；
        不扩大文件权限（默认与 daemon 一致：仅 engine 目录，可用 file_roots 放宽）
FILES:
  engine/yuiro/native/{__init__.py, ops.py, backend.py}（新增）
  engine/yuiro/tools/system_tool.py（backend 注入）
  engine/yuiro/config.py（backend / file_roots）
  engine/config.toml + config.example.toml（[systemd] 新字段）
  engine/yuiro/main.py（lifespan 按 backend 装配）+ debug_api.py
  engine/yuiro/agent/__init__.py（build_agent_loop 透传 backend）
  engine/tests/test_native_backend.py（新增）
  docs/spec/README.md（约束 9 修订）+ ARCHITECTURE.md + AGENTS.md + README.md
CODING AGENT:
  遵循 coding-agent-protocol：行为对齐优先（文案/参数/状态语义与 C++ 一致）；
  daemon 不删（降级为可选）；测试不得产生真实副作用（用 dry-run + 临时目录）。
TEST:
  Unit：别名解析 / dry-run 文案逐条 / 路径边界（含穿越尝试）/ 文件读写往返 /
        未知 action 报错 / backend 协议（call 签名与 SystemActionResult）/
        AgentLoop 装配（native 注入后 6 工具可见）/ 回归（既有护栏不破）
DEFINITION OF DONE:
  - NativeBackend 覆盖 6 个工具；dry-run 与错误文案与 C++ 对齐
  - 文件路径边界默认与 daemon 一致，可通过 file_roots 放宽
  - [systemd].backend 可切换；daemon 路径保留可用（不删代码）
  - spec 约束 9 与 ARCHITECTURE/AGENTS/README 同步修订
  - 回归通过（5 failed + 1 error 基线不变）
HUMAN ACCEPTANCE:
  ① 不启动 daemon（或把 backend 设为 native）→ 说"打开记事本"能打开；
  ② 说"下一首"能切歌；③ 让它在 engine 目录外写文件 → 被拒绝并说明原因
NEXT UNLOCK: S11 Capability 层（Policy / Permission 分级 / CapabilityView）——
             届时 native backend 成为 Policy 的执行点，安全价值真正兑现
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 行为契约（从 C++ 提取，native 必须对齐）

| 项 | C++ 实现（对齐目标） |
|---|---|
| app_open | 中文别名表（记事本→notepad/计算器→calc/画图→mspaint/命令提示符→cmd/控制面板→control/资源管理器→explorer/浏览器·Edge→msedge/网易云音乐·网易云→cloudmusic/微信→wechat/QQ→qq）；ShellExecute(open)；`已打开 "X"` |
| app_focus | 三级查找：L1 可见窗口标题 → L2 任意窗口（Restore）→ L3 进程名反查；`SetForegroundWindow`；失败文案 `未找到标题含 "X" 的窗口（且进程 Y 未运行）` |
| media_control | 播放控制走 SMTC；音量/mute 走系统媒体键；`未知 action: X` |
| file_* | **路径必须位于 allowed_base（daemon cwd = engine/）内**，否则 `denied`；file_create 自动建父目录；文案 `已创建文件: X（N 字节）` |
| dry_run | `dry-run：将打开/聚焦/创建/读取/写入 "X"`，status=dry-run |
| 返回 | `SystemActionResult(trace_id, status, approval_required, approval_request_id, stdout, artifacts)` |

## 交付报告（2026-09-12 完成）

### Changed files

| 文件 | 改动 |
|---|---|
| `engine/yuiro/native/{__init__.py, ops.py, backend.py}` | **新增**：`ops`（Windows API/ctypes + 标准库 + PowerShell SMTC 桥）+ `NativeBackend`（与 daemon 同签名，dry-run 文案对齐） |
| `engine/yuiro/tools/system_tool.py` | `SystemActionTool(daemon=, backend=)`：backend 优先，旧路径兼容 |
| `engine/yuiro/config.py` | `[systemd].backend`（native/daemon）+ `file_roots`；FIELD_META 同步（调试台可切） |
| `engine/config.toml` + `config.example.toml` | `[systemd]` 新字段（当前实配 = native） |
| `engine/yuiro/main.py` | `_build_system_backend()` + lifespan 按后端装配 + 启动日志广播后端名 |
| `engine/yuiro/agent/__init__.py` / `debug_api.py` | `system_backend=` 透传（`system_daemon=` 兼容保留） |
| `engine/tests/test_native_backend.py` | **新增** 15 个用例 |
| `docs/spec/README.md`（约束 9 + 蓝图）、`docs/spec/architecture-goal.md`（安全链×2）、`ARCHITECTURE.md`（×4）、`AGENTS.md`（×4）、`README.md`（×2） | 规格与文档同步修订 |

### 冒烟证据（真实执行）

```
CONFIG backend: native | file_roots: ['.']
BACKEND: NativeBackend | running: True
DRY app_open    -> dry-run | dry-run：将打开 "notepad"
DRY media_control -> dry-run | dry-run：将发送媒体键 next
DRY app_focus   -> dry-run | dry-run：将聚焦窗口 "网易云音乐"
CREATE -> ok | 已创建文件: …\engine\data\_s10_smoke.txt（17 字节）
READ   -> ok | native backend ok
DENY   -> denied | 路径不在允许目录内，已拒绝: C:/Windows/Temp/evil.txt
```

### 过程中抓到并修复的真 bug

`ops._find_window` 的 L3 进程候选集使用海象运算符于条件求值之前（`(p := ...)[:-4] if p...`）
→ ruff F821 报出，已改为先解析再归一化（否则进程名兜底查找会 NameError）。

### Tests

- 新增 **15 个**全部通过；全量回归 **159 passed**（S09 基线 144 + 15），失败集与基线一致；
- `native/`、`system_tool.py`、测试文件 ruff 零告警。

### DoD 对照

- [x] NativeBackend 覆盖 6 个工具；dry-run/错误文案与 C++ 对齐（测试逐条断言）
- [x] 文件路径边界默认与 daemon 一致（仅 engine 目录）；`file_roots` 可放宽；穿越与近似前缀均拒绝
- [x] `[systemd].backend` 可切换；daemon 代码保留可用（未删）；`system_daemon=` 旧路径兼容
- [x] spec 约束 9 / 蓝图 / ARCHITECTURE / AGENTS / README 同步修订
- [x] 回归通过（S05–S09 护栏不破）

### Human Acceptance（待人工）

1. 重启引擎 → 日志出现 `系统执行后端: NativeBackend（[systemd].backend='native'）`；
2. 说"**打开记事本**"→ 记事本真的打开；说"**下一首**"→ 切歌；
3. 让它写文件到 engine 目录外 → 被拒绝并说明（若需放宽，改 `file_roots`）；
4. （可选）把 `backend` 改成 `"daemon"` 重启 → 行为应一致（验证两后端等价）。

### 风险 / 遗留

- `now_playing` / `list_sessions` 依赖 PowerShell + WinRT SMTC 桥（Windows 10+ 可用；失败时返回说明，不影响播放控制类 action）；
- `system-daemon/` 未删除（按方案 B 保留为可选后端；若长期不用可后续再评估移除）；
- `file_roots` 默认严格（仅 engine 目录）——如需让 Yuiro 操作桌面/文档，用户需显式配置；
- 审批仍为 `approval.py` 的全有全无模型（分级属 S11 Capability 层）。
