# 在 macOS 上调试运行 Yuiro

> 适用：macOS 13+（Apple Silicon / Intel 均可，Apple Silicon 优先）。
> 本文目标是**最小可运行闭环**：引擎启动 + 文本聊天 + Live2D 桌宠壳层，并能在 mac 上继续开发。
> Windows 侧的完整运行方式见仓库根 `AGENTS.md`；两边共用同一套代码与仓库。

---

## 0. 先看结论：mac 上哪些能用

| 能力 | mac 支持 | 说明 |
|---|---|---|
| 引擎启动 / 文本聊天 / 记忆 / Agent 工具 | ✅ | 与 Windows 同一套 Python 代码 |
| Live2D 桌宠壳层（Electron） | ✅ | `pnpm dev` 直接跑；打包（dmg）尚未配置 |
| 云端 TTS（edge-tts / SiliconFlow） | ✅ | 无需本地模型 |
| 本地 TTS（CosyVoice / GPT-SoVITS） | ⚠️ | 依赖 CUDA，mac 上不建议；直接用云端 TTS |
| 语音输入 ASR | ⚠️ | 需改 `[asr].provider = "faster-whisper"` + `device = "cpu"` |
| 系统操作（打开应用 / 聚焦窗口） | ⚠️ | 已做平台分支（`open`），但应用别名表是 Windows 应用名 |
| 音量 / 媒体键 / SMTC 媒体会话 | ❌ | WinRT + 系统媒体键，仅 Windows |
| 网易云播放（mpv） | ⚠️ | IPC 已支持 Unix socket，但需 `brew install mpv`，未在 mac 实测 |
| C++ SystemDaemon | ❌ | 依赖 WinRT/MSVC；mac 用默认 `backend = "native"` 即可 |

---

## 1. 前置条件

```bash
# Xcode 命令行工具（编译原生依赖用）
xcode-select --install

# Homebrew（若未安装）
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Node 20+ / pnpm / mpv（mpv 可选，只为网易云播放）
brew install node pnpm mpv
```

| 依赖 | 版本 | 检查命令 |
|---|---|---|
| Python | ≥ 3.11 | `python3 --version` |
| uv | 最新 | `uv --version`（没装时 bootstrap 会用 brew 装） |
| Node | ≥ 20 | `node -v` |
| pnpm | ≥ 9 | `pnpm -v` |

---

## 2. 克隆与安装

```bash
git clone https://github.com/Yuiidrn/Yuiro.git
cd Yuiro

# 最小依赖（引擎 + 文本聊天 + dev 工具）
./scripts/setup/mac/bootstrap.sh

# 需要语音输入时再装语音栈（会拉 torch，数 GB，慢）
./scripts/setup/mac/bootstrap.sh --voice
```

脚本做的事：
1. `uv venv .venv --python 3.11`；
2. `uv pip install -e engine --no-deps` + 显式装核心依赖（避开 funasr/torch 等重型包）；
3. 首次运行时从 `engine/config.example.toml` 生成 `engine/config.toml`，并把 `[asr].device` 改成 `cpu`；
4. 创建 `.env-local/`（模型与缓存都落在这里，不写用户主目录）。

> `engine/config.toml`、`engine/characters/`、`engine/models/`、`.env-local/`、`node_modules/` 都**不入库**，属于本机运行态。

---

## 3. 配置 `engine/config.toml`

生成后按需改这几个键（其它保持默认即可）：

```toml
[llm]
provider = "openai"                       # 与 Windows 侧保持一致即可
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
model = "qwen-plus"

[asr]
provider = "faster-whisper"               # mac 上没有 CUDA，SenseVoice 也可跑但要装 funasr
device = "cpu"
compute_type = "int8"

[tts]
provider = "edge-tts"                     # mac 上最省事：云端、零模型、零显存
# provider = "siliconflow"                # 想用克隆音色时选它（需要 SiliconFlow key）

[memory]
embedder = "md5"                          # 没下 BGE-M3 时显式用 md5，避免每次启动探测
```

**注意**：不要从 Windows 直接拷 `engine/config.toml` 过来 —— Windows 那份里可能有
`D:/...` 绝对路径（ASR 模型目录、参考音频）。参考音频的默认值已改为相对路径
`../assets/voices/neuro_prompt.wav`，确实要拷的话把盘符路径逐条改掉。

**人设一致**：`engine/characters/`（角色卡，含私人提示词）不入库，首次启动会按当前
`[persona]` 自动 seed 一份。若希望与 Windows 侧完全一致，手动把
`engine/characters/` 整个目录拷过来即可。

---

## 4. API Key 迁移（不要提交到仓库）

Yuiro 的 key 一律存 OS keychain（`engine/yuiro/keychain.py`），配置文件里没有明文，
所以 **key 不会跟着 git 走**，需要单独搬一次。

### 4.1 在 Windows 上导出

```powershell
# 仓库根目录
.\scripts\setup\mac\export_keys.ps1
```

生成 `.secrets\mac-keys.env`（该目录已加入 `.gitignore`，**不会被提交**）。
用 AirDrop / iCloud 云盘 / U 盘把它传到 Mac —— 不要经过聊天工具或公开网盘。

### 4.2 在 mac 上导入钥匙串

```bash
cd ~/Yuiro
./.venv/bin/python scripts/setup/mac/import_keys.py ~/Downloads/mac-keys.env
rm ~/Downloads/mac-keys.env          # 导入后立刻删除
```

脚本只打印「写入了哪些项」，不打印 key 本身。导入后可用调试台「API Key 设置」验证，
或：

```bash
./.venv/bin/python - <<'PY'
import keyring
print("LLM key:", "已配置" if keyring.get_password("yuiro-engine", "llm") else "未配置")
PY
```

### 4.3 没有 `.secrets` 文件时

也可以直接在调试台 UI（壳层 → 设置 → API Key）里粘贴，效果相同：
键最终都落在 macOS「钥匙串访问」→ 登录 → 密码项里，服务名为 `yuiro-engine` /
`yuiro-siliconflow` / `yuiro-deepseek-search`。

> 首次写入时 macOS 可能弹窗询问「是否允许 python 访问钥匙串」，选**始终允许**。

---

## 5. 启动

### 5.1 引擎（终端 A）

```bash
cd ~/Yuiro
./scripts/engine/engine_start.sh
```

默认前台运行、日志直接打印。确认出现：

```
Uvicorn running on http://127.0.0.1:8200
```

后台模式（日志写 `.env-local/engine_start.*.log`）：

```bash
./scripts/engine/engine_start.sh --bg
tail -f .env-local/engine_start.out.log
```

停止：

```bash
./scripts/engine/engine_stop.sh      # 清理 8200 / 5005 / 5000
```

### 5.2 壳层（终端 B）

```bash
cd ~/Yuiro/shell
pnpm install        # 首次；会下载 darwin-arm64 的 electron
pnpm dev
```

若 electron 下载慢，可用镜像：

```bash
export ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/
export ELECTRON_BUILDER_BINARIES_MIRROR=https://npmmirror.com/mirrors/electron-builder-binaries/
pnpm install
```

壳层默认连 `http://127.0.0.1:8200`（`shell/src/shared/config.ts`），**先起引擎再起壳层**。

### 5.3 验证闭环

1. 桌宠窗口出现（默认模型 `hiyori`，已随仓库提供）；
2. 输入一句「你好」→ 有文字回复；
3. 终端 A 出现 `[chat]` / `[agent]` 阶段日志。

---

## 6. 可选组件

### 6.1 语义记忆（BGE-M3，约 2.2 GB）

不装也能用：`[memory].embedder = "md5"` 是确定性降级向量（无语义），聊天不受影响。
需要语义检索时：

```bash
source config/env.sh
./.venv/bin/python scripts/setup/downloads/download_bge_m3_modelscope.py
# 权重落在 engine/models/bge-m3，然后把 [memory].embedder 改成 "models/bge-m3"
```

### 6.2 语音输入

```bash
./scripts/setup/mac/bootstrap.sh --voice
```

首次识别会从 HuggingFace 镜像拉 faster-whisper 权重（数百 MB）。
macOS 首次使用麦克风会弹权限请求；开发模式（`pnpm dev`）下授权给 Electron 即可。

### 6.3 本地 TTS

不建议在 mac 上跑 CosyVoice（无 CUDA）。用 `edge-tts`（免费、跨平台）或
`siliconflow`（云端克隆音色）即可。

### 6.4 Live2D 角色资源（Hotaru）走压缩包

`Hotaru Shiomi` 是 62 MB / 280 余个文件的二进制美术资源，且几乎不再变动，
因此**不进 git**（`.gitignore` 已排除 `shell/src/renderer/public/live2d/Hotaru Shiomi/`）。
仓库只带官方示例模型 `hiyori`，缺 Hotaru 时桌宠照常运行，只是「外观」页里选不到它
（`model_dict.json` 里的条目仍在，选中会加载失败）。

**Windows 侧打包**：

```powershell
# 仓库根目录
.\scripts\setup\mac\pack_live2d_assets.ps1
# 默认输出到 .env-local\transfer\yuiro-live2d-hotaru-<日期>.zip（已被忽略）
# 同时生成同名 .sha256
```

**mac 侧解包**：

```bash
./scripts/setup/mac/unpack_live2d_assets.sh ~/Downloads/yuiro-live2d-hotaru-20261121.zip
```

脚本会先校验 SHA256，再解压到
`shell/src/renderer/public/live2d/Hotaru Shiomi/`；若该目录已存在，会先备份到
`.env-local/backup/` 而不是直接覆盖。完成后刷新壳层窗口即可。

> 这套流程同样适用于以后新增的任何大体积角色资源：**资源进压缩包，代码进仓库**。
> 注意不要用 `git add -f` 强行加入，否则历史会被永久污染。

---

## 7. 平台差异与已知限制

1. **`[systemd].backend` 保持 `native`**。`daemon` 需要构建 `system-daemon/`（C++20 + WinRT），mac 上不可用。
2. **文件工具边界**：`[systemd].file_roots = ["."]` 相对 `engine/` 解析；mac 上想读写别处要显式加目录。
3. **应用名别名表是 Windows 专用**（记事本 / 计算器 / 网易云…）。mac 上 `app_open` 走 `open`，
   传应用名（如 `Safari`）或文件路径。
4. **音量 / 媒体键 / SMTC 在 mac 上直接返回错误串**，不影响其它工具。
5. **网易云**：`player.py` 已按平台切到 `/tmp/yuiro-mpv.sock`，但整条链路（ncm-cli 登录 +
   自签名取直链）只在 Windows 验证过；mac 上属于「未实测」。扫码登录需要额外装
   `uv pip install qrcode Pillow`（默认最小安装不含）。
6. **打包**：`pnpm build:mac` 已加，但仓库还没有 `electron-builder` 配置文件，
   首次打包需要补 `appId / productName / mac.target / 麦克风用途说明`。日常开发用 `pnpm dev` 即可。

---

## 8. 常见问题

| 现象 | 原因 / 处理 |
|---|---|
| `Address already in use` | `./scripts/engine/engine_stop.sh`，或改 `YUIRO_PORT` |
| 聊天无回复 | 先看引擎日志有没有 `401` / `APIConnectionError`；大概率是 LLM key 或 base_url 不匹配 |
| 回复特别慢 | 确认模型不是 reasoning 模式（qwen3 会自动关 thinking，其它模型要自己确认） |
| `[memory]` 打印 BGE-M3 超时 | 正常降级到 md5，不阻断聊天；要语义检索就下载模型 |
| 壳层白屏 | 引擎没起 / 端口不是 8200；看 `pnpm dev` 终端的 `[render:error]` |
| 钥匙串反复弹窗 | 选「始终允许」；或删掉旧条目后重新导入 |
| Live2D 模型 404 | 默认模型是 `hiyori`；`Hotaru Shiomi` 目录被 git 忽略，需从 Windows 机单独拷 |

---

## 9. 两机接续开发约定

```bash
# 换机器前
git add -A && git commit -m "..." && git push

# 到另一台机器
git pull
```

需要注意的「不随仓库走」的东西：

| 项目 | 处理方式 |
|---|---|
| API key | 各机器各自进钥匙串（第 4 节） |
| `engine/config.toml` | 各机器各自的（路径/设备不同） |
| `engine/characters/` | 本机角色卡（含私人提示词），不入库 |
| `engine/models/`、`.env-local/` | 模型与缓存，就地下载 |
| `shell/node_modules/` | 各自 `pnpm install` |
| `engine/data/` | 对话/记忆数据库，本机运行态 |

改完代码后建议跑：

```bash
cd engine && ./.venv/bin/python -m pytest tests/ -q
cd shell   && pnpm typecheck
```
