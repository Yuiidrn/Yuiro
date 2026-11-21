# S19 — Capability Scope（Wave 6 后半：参数级越界拦截）

> 状态：**进行中**（2026-09-13）。
> 来源：`docs/spec/roadmap.md` Wave 6 Security Runtime +
> `docs/spec/architecture-goal.md` §3.7：
> **Policy 是"规则"，Sandbox 是"访问不到"** —— 本 Sprint 补上中间那层：
> **CapabilityScope = 参数级边界（路径 / 域名 / 进程）**。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YUIRO SPRINT 19
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TITLE:    Capability Scope —— "它做事我放心"
SURPRISE: 它再也不能碰 C:\Windows（哪怕我让它碰）
ARCHITECTURE:
  Agent → Capability(Policy + Scope) → Approval → Execution
                        │
                        └─ 参数级：filesystem / network / process / media / clipboard / screen
  约束：
   1. 默认宽松（未声明的域不限）—— 不打断现有工作流；
   2. 硬红线（系统目录）即使写 * 也拒绝；
   3. 只在 ToolDispatcher 单点校验（不碰各工具实现，Sandbox 可再兜一层）。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 设计

| 概念 | 回答什么 | 现状 |
|---|---|---|
| Policy（S11） | 这个**工具**该不该做（风险 × 档位） | ✅ 已有 |
| **CapabilityScope（S19）** | 这个工具**碰的这个东西**允不允许（参数级） | ★ 本 Sprint |
| Sandbox（后续） | 即使想做，OS 层也访问不到 | 未做（SystemDaemon 侧） |

**域声明（借鉴手机权限，spec §3.7）**：

```toml
[capability.scope]
filesystem = ["~/Documents/Yuiro/**", "~/Downloads/**"]   # 未声明 = 不限
network    = ["api.siliconflow.cn", "*.163.com"]
process    = ["记事本", "网易云音乐"]
media      = ["*"]
```

## 交付报告（2026-09-13 完成）

### Changed files

**新增**：`engine/yuiro/capability/scope.py`、`engine/tests/test_capability_scope.py`（14 个用例）

**修改**：

| 文件 | 改动 |
|---|---|
| `engine/yuiro/capability/policy.py` | `Policy(scope=...)`；`decide` 改为 **先参数级域校验 → 再工具级风险档位**（越界直接 deny，不进审批流）；`Policy.scope` 属性 |
| `engine/yuiro/capability/__init__.py` | 导出 `CapabilityScope` / `ResourceDomain` |
| `engine/yuiro/config.py` | `CapabilityConfig.scope: dict[str, list[str]]` |
| `engine/config.toml` + `config.example.toml` | 新增 `[capability.scope]`（默认全注释 = 不限） |
| `engine/yuiro/agent/__init__.py` | `Policy(profile=..., scope=...)` 装配透传 |
| `engine/yuiro/debug_api.py` | `GET /capability/scope`（域视图）+ `GET /capability/check`（判定试算，不执行） |

### 冒烟证据（真实拦截链路）

```
VIEW: declared {filesystem: ["~/Downloads/**"], process: ["记事本"]},
      unrestricted_domains: [network, media, clipboard, screen],
      hard_deny: [c:/windows, c:/program files, ..., /etc, /usr/bin, ...]
HARD DENY (C:/Windows): False       SCOPE ALLOW (~/Downloads): True
SCOPE DENY (~/Desktop): False       TRAVERSAL (~/Downloads/../../Desktop): False
PROCESS ok/deny: True False
BLOCKED: {"status":"denied","tool":"file_write","note":"参数越出 filesystem 授权范围：C:/Windows/evil.dll"}
ALLOWED: {"status":"ok","wrote":"~/Downloads/ok.txt"}
EXECUTED ONLY: ['~/Downloads/ok.txt']      ← 越界工具根本没被执行
```

### 两个设计决策（实现过程中定下）

1. **硬红线默认生效**（有意收紧 S11 行为）：即使没配 `scope`、即使 `profile = "trusted"`，
   `file_write` 到 `C:/Windows`、`/etc`、`Program Files` 也一律 `deny`（此前是 `ask` —— 用户可能点同意）。
   **普通路径的档位行为完全不变**（`normal` 下 `file_write` 到普通目录仍是 `ask`），
   故不破坏现有工作流；测试同时固化这两面。
2. **POSIX 路径跨平台**：`/etc/passwd` 在 Windows 上 `abspath` 会被补盘符（`d:/etc/passwd`）
   从而绕过硬红线 —— 归一化时对 POSIX 绝对路径回补形态，使跨平台红线在任一平台都成立
   （由测试 `test_star_means_unrestricted_but_hard_deny_still_applies` 抓出）。

### Tests

- 新增 **14 个**全部通过；全量回归 **243 passed / 5 failed / 1 error**（失败集与基线一致）；
- `capability/` 与测试文件 ruff 零告警。

### DoD 对照

- [x] 域模型（filesystem / network / process / media / clipboard / screen）+ 声明式配置
- [x] 参数级越界拦截（glob `**` / 域名 / 进程关键词），**在 ToolDispatcher 单点校验**（工具未被执行）
- [x] 系统目录硬红线（默认生效，`*` 也不放行）；路径穿越归一化后同样拦下
- [x] 默认宽松（未声明的域不限）→ 现有工作流零影响（全量回归失败集未变）
- [x] 可观测：域视图 + 判定试算 API；越界日志 `[capability] 拒绝 …`
- [x] 热重载：`Policy` 由 `capability_config` 每次重建（改配置 → 重建 AgentLoop 即生效）

### Human Acceptance（待人工）

1. 让 Yuiro「**把 `C:\Windows\System32` 里的文件列出来**」→ 预期被拒（日志 `[capability] 拒绝 …`），
   回复里说明越界而非报错；
2. 让它写一个正常文件（如「在下载文件夹建 notes.txt」）→ 正常完成；
3. 访问 `GET /debug/capability/scope` 看当前域策略；
   `GET /debug/capability/check?tool=file_write&value=C:/Windows/x.txt` 试算判定；
4. 想收紧时：把 `[capability.scope]` 的 `filesystem` 设为 `["~/Documents/Yuiro/**"]`，重启后生效。

### 风险 / 遗留

- **Sandbox（OS 层隔离）仍未做**：本 Sprint 是"配置层拒绝"（引擎侧），若 Agent 绕过工具
  直接执行系统调用仍可能越界——真正的 OS 层兜底属 SystemDaemon/C++ 侧（spec 的 `sandbox.cpp`）；
- 域仅覆盖已映射的工具（`file_*` / `app_*` / `process_kill`）；`network` / `clipboard` / `screen`
  域模型已就位但暂无工具使用（留给未来 HTTP / 剪贴板 / 截屏能力）；
- `media` 域不做参数校验（`media_control(action=...)` 无资源值语义）；
- 未做"域级审批"（spec 的 plan approval，LEVEL 4）——属后续 Wave。
