# system-daemon — C++ 系统操作守护进程设计

> 借鉴 **AIRI computer-use-mcp**（控制面/执行面分离、审批+审计、确定性优先）。
> 定位：Engine(Python Agent) 是**控制面**；SystemDaemon(C++) 是**本地执行基座**，通过 **MCP** 暴露"真实操作系统能力"。

---

## 1. 为什么用 C++

- **真实 OS 能力**：直接 WinAPI（`CreateProcess`/`ShellExecute`/窗口句柄/输入注入），比 Python `subprocess`/`pyautogui` 更原生、绕过层转换。
- **独立进程沙箱**：作为独立守护进程运行，可独立授权、审计、崩溃隔离（Engine 挂了它还在）。
- **性能**：处理高频系统事件/输入注入无 GC 停顿。
- **单二进制部署**：无运行时依赖，绿色分发。

> 代价：AI/LLM 生态弱 → **只让它做"手"，不让它做"脑"**。脑在 Python，手在 C++，中间 MCP。

---

## 2. 进程模型

```
Engine (Python Agent)  ──MCP(stdio/HTTP)──▶  SystemDaemon (C++)  ──▶  OS (WinAPI)
     控制面 / 决策                                                  执行面 / 能力
                                                │
                                                ├─ 审批队列 ← 原生对话框(经Engine→Shell)
                                                ├─ trace / audit log
                                                └─ dry-run 沙箱
```

## 3. 能力清单（MCP 工具）

| 工具 | 说明 | approval_required | dry_run 可 |
|---|---|---|---|
| `app_open(name)` | ShellExecute 打开软件/文件/URL | 常开 | ✅ |
| `app_focus(name)` | 枚举窗口→SetForegroundWindow 聚焦 | 否 | ✅ |
| `process_list()` | 枚举进程 | 否 | ✅ |
| `process_kill(pid)` | 结束进程 | **是** | ✅ |
| `file_create(path, content)` | 生成文件(目录自动建) | 危险路径是 | ✅ |
| `file_read(path)` / `file_write(path, content)` | 读写 | 写=危险是 | ✅ |
| `terminal_exec(cmd, cwd, background)` | 后台 shell 执行行列 | **是** | ✅ |
| `window_screenshot(rect?)` | 截图(供视觉/审批预览) | 否 | ✅ |
| `mouse_inject(x,y,btn)` / `keyboard_inject(keys)` | 输入注入 | **是** | ✅ |
| `clipboard_set/get` | 剪贴板 | 否 | ✅ |

**执行策略**（决定性优先，坐标兜底）：
`terminal_exec → file_* → 确定性 shell 命令 → 最后才坐标点击`（参考 computer-use-mcp「非盲点坐标」哲学）。

## 4. 安全模型

- **两层权限**：能力级审批 + 单次 approve/reject（参考 AIRI extension-grant ∩ module）。
- **审批协议**：MCP 返回 `{approval_required:true, request_id}` → Engine 转发 Shell → Electron 原生对话框 → `approve/reject` 回传。
- **dry-run 沙箱**：默认模式不注入任何输入，仅模拟并采集截图供调试（AIRI executor `dry-run`）。
- **审计/trace**：每次运行记录 trace_id、args(脱敏)、结果、审批者、时间 → 落盘 JSONL。
- **路径防越权**：文件操作限定在允许目录（deskpet file_tool path-traversal guard 思路）。

## 5. MCP 接口契约

```jsonc
// SystemResult 统一返回
{
  "trace_id": "uuid",
  "status": "ok" | "denied" | "error" | "dry-run",
  "approval_required": false,
  "approval_request_id": null,
  "stdout": "…",        // terminal_exec
  "artifacts": ["…"],   // 截图路径等
  "audit": { "tool": "app_open", "ts": "…", "actor": "engine" }
}
```

```jsonc
// 审批请求 (Engine→Shell)
{
  "approval_request_id": "uuid",
  "tool": "terminal_exec",
  "summary": "运行命令: pip install foo",
  "args": {"cmd":"pip install foo"},
  "preview": "screenshot.png"
}
```

## 6. 目录结构

```
system-daemon/
├── CMakeLists.txt
├── include/yuiro/
│   ├── capability/   # 能力抽象基类
│   ├── exec/         # terminal/file/process 执行器
│   ├── input/        # 鼠标键盘注入
│   ├── security/     # 审批/审计/dry-run/path guard
│   └── mcp/          # MCP server (C++ 侧)
├── src/
│   ├── main.cpp
│   ├── capability/...   # WinAPI 实现
│   └── mcp/...          # MCP 工具暴露
├── proto/            # 契约定义
└── tests/
```

## 7. 构建 (CMake)

```cmake
cmake_minimum_required(VERSION 3.20)
project(yuiro CXX)
set(CMAKE_CXX_STANDARD 20)
find_package(Threads REQUIRED)
# 依赖: 一个 C++ MCP/WS 库 + ASIO/uWebSockets(可选 HTTP)
add_executable(yuiro src/main.cpp src/…)
```
（具体依赖选型：C++ MCP SDK 目前无官方标准，可先用轻量 stdio-JSON 协议自实现 + 可选 HTTP via uWebSockets。）
