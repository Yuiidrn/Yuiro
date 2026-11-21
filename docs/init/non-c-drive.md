# Yuiro — 避免占用 C 盘空间的约定

> 目的：**所有 venv / 依赖缓存 / 模型缓存一律放项目内 `.env-local/`（跟随项目在 D 盘等非系统盘）**，
> 绝不写入 `C:\Users\<你>\AppData` 等系统缓存目录。

---

## 一、统一环境根目录

```
Yuiro/.env-local/          ← 已 gitignore，跟随项目
├── engine-venv/           # Python venv（解释器 + 已装依赖）
├── pip-cache/             # pip 下载缓存
├── npm-cache/             # npm/pnpm 缓存
├── electron-cache/        # electron 二进制下载缓存
└── models/                # 模型缓存(hf/torch 等)、模型文件
    └── cache/{huggingface,torch,xdg}
```

## 二、各类默认占 C 盘项 → 重定向到 D

| 项 | 默认(C盘) | 本项目 | 手段 |
|---|---|---|---|
| Python 包 | 系统/AppData | `.env-local\engine-venv` | 自建 venv |
| pip 缓存 | `.cache\pip` | `.env-local\pip-cache` | `PIP_CACHE_DIR` |
| npm 缓存 | `AppData\Local\npm-cache` | `.env-local\npm-cache` | `npm_config_cache` |
| electron 二进制 | `AppData\Local\electron` | `.env-local\electron-cache` | `electron_config_cache` |
| HuggingFace 模型 | `.cache\huggingface` | `.env-local\models\cache\huggingface` | `HF_HOME` |
| torch 缓存 | `.cache\torch` | `.env-local\models\cache\torch` | `TORCH_HOME` |
| 通用缓存 | `.cache` | `.env-local\models\cache\xdg` | `XDG_CACHE_HOME` |

## 三、固化手段（不用每次手敲）

- `config/env.ps1`：一键设置所有上述变量（`. .\config\env.ps1` 后生效）。
- `shell/.npmrc` + `package.json.pnpm.onlyBuiltDependencies`：保证 electron/esbuild 下载走 D 盘缓存并放行构建脚本。
- 命令统一用 venv 内的 `python.exe`（见 [DEPLOYMENT.md](DEPLOYMENT.md)）。

## 四、效果

不改进时，一个含本地 AI 模型 + 完整前端依赖的项目可能吃掉 **3~10GB** C 盘（模型动辄数 GB）。
改进后这些全部落在 D 盘 `.env-local`，且**删除项目目录即整体清空**，对系统零污染。
