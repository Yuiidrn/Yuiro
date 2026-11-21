# Yuiro — 部署 / 运行指南

> 从零把这个项目跑起来的**完整步骤**。所有环境都放在项目内 `.env-local/`（不占 C 盘）。
> 以下步骤均已在 Windows + PowerShell 上验证通过（当前 M1 里程碑）。

---

## 0. 前置工具（都在 D 盘/非系统盘，天然不占 C 盘）

| 工具 | 本项目使用的位置 | 说明 |
|---|---|---|
| Python ≥3.11 | `D:\software\ComfyUI-aki-v3\...\python.exe` | 用于创建 venv |
| Node + pnpm | `D:\Program Files\nodejs` | 用于前端 |

> 其它机器：有 `python` / `node` / `pnpm` 即可，无需特定路径。venv 会自动建在项目内。

## 1. 一键加载环境（模型/依赖缓存 → D 盘）

```powershell
cd d:\Project\Yuii\desktop-pet\Yuiro
. .\config\env.ps1          # 设好 YUIRO_* 和 HF/pip/npm/electron 缓存到 .env-local
```
> 作用：`HF_HOME`、`PIP_CACHE_DIR`、`npm_config_cache`、`electron_config_cache` 全部指到项目内 `.env-local`，避免写系统 C 盘。

## 2. 引擎（Python FastAPI）

```powershell
# 首次：建 venv（只在没有 .env-local\engine-venv 时做一次）
$py = 'D:\software\ComfyUI-aki-v3\ComfyUI-aki-v3\python\python.exe'
& $py -m venv d:\Project\Yuii\desktop-pet\Yuiro\.env-local\engine-venv

# 安装依赖（用 venv 里的 python，别用系统的！）
$venvPy = 'd:\Project\Yuii\desktop-pet\Yuiro\.env-local\engine-venv\Scripts\python.exe'
& $venvPy -m pip install -e .\engine     # 安装 pyproject.toml 里的依赖

# 启动服务（后台）
cd .\engine
& $venvPy -m uvicorn yuiro.main:app --host 127.0.0.1 --port 8200
# 验证
Invoke-RestMethod http://127.0.0.1:8200/health
# → {"status":"ok","version":"0.1.0"}
```

> **已装**的核心依赖：fastapi、uvicorn、websockets、pydantic、keyring、httpx、numpy、mcp、silero-vad、torch(cpu)。
> **未装（M2 需要时）**：faster-whisper、FlagEmbedding、edge-tts（届时按里程碑补装并复用同一 venv）。

## 3. 前端（Electron + Vue3 + TS）

```powershell
cd .\shell
pnpm install        # 依赖（缓存走 .env-local，不占 C）
pnpm dev            # 弹出透明桌宠窗口（M1 空壳 UI）
pnpm build          # 仅编译产物验证
pnpm run typecheck  # vue-tsc 类型检查
```
> 首启：会下载 electron 二进制到 `.env-local\electron-cache`（约 100MB+，一次性）。

## 4. 当前已验证状态（M1 里程碑 ✅）

| 项 | 结果 |
|---|---|
| 引擎 FastAPI 启动 | ✅ `Application startup complete` |
| `/health` 健康检查 | ✅ `{"status":"ok","version":"0.1.0"}` |
| 引擎 WS 路由 | ✅ `/ws/control`、`/ws/audio` 已注册 |
| 前端 typecheck | ✅ 0 错误 |
| 前端 build | ✅ 0 错误，main/preload/renderer 都出产物 |
| 前端 `pnpm dev` | ✅ Electron 进程存活，dev server HTTP 200，透明窗口打开 |
| Live2D demo 模型 | ✅ 已拷入 `shell/src/renderer/public/live2d/{shizuku,mao_pro}` |

## 5. 里程碑路线（下一步）

- **M2 声控**：加载 Live2D 模型渲染 + 采音(AudioWorklet) + VAD(silero) + ASR(faster-whisper) + TTS(edge-tts)。
  - Live2D 选型注意：`pixi-live2d-display@0.4.0` 是给 pixi v6 的，我们当前是 pixi v7；届时参照 deskpet 同款组合或 AIRI 路线（见 `Live2DCanvas.vue` 注释）。
- 完整路线见 [milestones.md](milestones.md)。

---

## 常见问题

### Q: 为什么不用 activate venv？
项目约定**直接用 venv 里的 `python.exe`**（如 `$venvPy`），不依赖 activate，避免歧义。也可 `.config\env.ps1` 后自行 `activate`。

### Q: 想换 Live2D 模型？
把模型整文件夹放进 `shell/src/renderer/public/live2d/`，并在 `model_dict.json` 注册；M2 渲染接入后会读取它切换。

### Q: pip/pnpm 很慢？
命令里已把 `PIP_CACHE_DIR`/`npm_config_cache` 指到 D 盘缓存；网络镜像由本机 pnpm/pip 配置决定（本项目默认走 npmmirror）。
