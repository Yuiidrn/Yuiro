# 共享配置规范

## 密钥管理
- **所有 API key 一律走系统 OS keychain**（DPAPI / Keychain / libsecret），使用 `keyring`(Python) / `safeStorage`(Electron)。
- 配置文件只存 **keychain 引用**（如 `key_ref = "yuiro/llm/openai"`），绝不存明文。
- 敏感配置禁止提交 git。

## 端口约定
| 服务 | 端口 | 说明 |
|---|---|---|
| Engine HTTP/WS | 8200 | localhost-only，`YUIRO_SHARED_SECRET` 鉴权 |
| SystemDaemon HTTP (可选) | 8300 | MCP HTTP transport |
| Metrics | 9100 | prometheus |

## 环境配置（不占 C 盘 ✨重点）
> 所有 venv / 模型缓存 / node_modules 都放在 **项目内 `.env-local/` 目录**（已 gitignore），
> 不污染系统盘 `C:\Users\...\AppData`。磁盘位置跟随项目所在盘（如 `D:\Project\...\Yuiro\.env-local\`）。

```
Yuiro/.env-local/                  ← 本地环境根（gitignore）
├── engine-venv/                   ← Python 虚拟环境 (venv)
├── models/                        ← 所有本地模型下载目录（faster-whisper、silero、BGE-M3 等）
├── node_modules/                  ← 前端依赖（.npmrc 指定，见下）
└── tmp/                           ← 运行时临时文件/音频
```

**推荐一键加载的环境变量**（写入 `.env-local/env.ps1` / `.env-local/env.sh`）：
```powershell
# PowerShell 示例 (env.ps1)
$env:YUIRO_ROOT    = "$PWD"
$env:YUIRO_DATA_DIR    = "$env:YUIRO_ROOT\.env-local\data"
$env:YUIRO_MODELS_DIR  = "$env:YUIRO_ROOT\.env-local\models"
$env:YUIRO_SHARED_SECRET = "change-me"

# 下方 HF/Torch 缓存重定向 → 全部进 .env-local/models/.cache（避开 C:\Users 缓存）
$env:HF_HOME          = "$env:YUIRO_MODELS_DIR\cache\huggingface"   # faster-whisper / transformers
$env:HUGGINGFACE_HUB_CACHE = "$env:HF_HOME\hub"
$env:TORCH_HOME       = "$env:YUIRO_MODELS_DIR\cache\torch"
$env:XDG_CACHE_HOME   = "$env:YUIRO_MODELS_DIR\cache\xdg"
$env:TRANSFORMERS_CACHE = "$env:HF_HOME"
```

**前端依赖不占 C 盘（可选）**：在 `shell/.npmrc` 设
```
cache=D:/<你的>/Yuiro/.env-local/npm-cache
# (pnpm 会自动用 D:\Program Files\nodejs... 的 store；如需彻底搬家可加：)
store-dir=D:/<你的>/Yuiro/.env-local/pnpm-store
```
或用 Node 侧环境变量 `npm_config_cache` 指向 `.env-local/npm-cache`。
electron 二进制默认会下到 C 盘缓存——同样可设 `electron_config_cache` 指向 `.env-local/electron-cache`。

## 环境变量
- `YUIRO_SHARED_SECRET` — WS 控制通道共享密钥（必须设置）
- `YUIRO_DATA_DIR` — 数据/记忆目录（默认 `<userData>/yuiro`）
- `YUIRO_SYSTEMD_BIN` — C++ 守护进程路径

## 目录结构
```
<userData>/yuiro/
├── memory.db            # sqlite + sqlite-vec (三层记忆)
├── device_id            # 跨重启稳定设备标识 (AIRI device.rs 思路)
├── logs/                # 结构化日志
├── audit/               # SystemDaemon 审计日志 (JSONL)
└── skills/              # 用户自定义 skills (watchdog 热加载)
```
