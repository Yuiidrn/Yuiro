#!/usr/bin/env bash
# Yuiro macOS 依赖安装（最小可运行：引擎文本聊天 + Electron 壳层）
#
# 用法（仓库根目录）：
#   ./scripts/setup/mac/bootstrap.sh            # 装最小依赖
#   ./scripts/setup/mac/bootstrap.sh --voice    # 额外装语音栈（faster-whisper + edge-tts）
#
# 不做的事：不下载模型权重（BGE-M3 / ASR 模型），缺模型只会降级并打 WARNING。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"

WITH_VOICE=0
for arg in "$@"; do
  case "$arg" in
    --voice) WITH_VOICE=1 ;;
    *) echo "未知参数: $arg" >&2; exit 2 ;;
  esac
done

echo "==> 仓库根目录: $ROOT"

if ! xcode-select -p >/dev/null 2>&1; then
  echo "缺少 Xcode Command Line Tools，请先执行：xcode-select --install" >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "==> 未找到 uv，尝试用 Homebrew 安装"
  if ! command -v brew >/dev/null 2>&1; then
    echo "请先安装 Homebrew: https://brew.sh/zh-cn/" >&2
    exit 1
  fi
  brew install uv
fi

PY_VER="${YUIRO_PYTHON:-3.11}"
echo "==> 创建虚拟环境 .venv (Python $PY_VER)"
uv venv .venv --python "$PY_VER"

VPY="$ROOT/.venv/bin/python"

# 装引擎包本体（--no-deps：语音栈按需装，避免一上来拉数 GB 的 torch）
echo "==> 安装 engine（--no-deps）"
uv pip install --python "$VPY" -e engine --no-deps

echo "==> 安装核心运行时依赖"
uv pip install --python "$VPY" \
  "fastapi>=0.115" "uvicorn[standard]>=0.30" "websockets>=15" "msgpack>=1.0" \
  "pydantic>=2.6" "pydantic-settings>=2.0" "structlog>=24.0" "keyring>=25.0" \
  "numpy>=1.26" "sqlite-vec>=0.1" "openai>=1.40" "anthropic>=0.30" \
  "httpx>=0.27" "mcp>=1.0" "prometheus-client>=0.20" "edge-tts>=6.1"

echo "==> 安装开发依赖（pytest / ruff）"
uv pip install --python "$VPY" "pytest>=8" "pytest-asyncio>=0.23" "ruff>=0.5"

if [ "$WITH_VOICE" -eq 1 ]; then
  echo "==> 安装语音栈（faster-whisper / silero-vad / funasr / modelscope / FlagEmbedding）"
  uv pip install --python "$VPY" "faster-whisper>=1.0" "silero-vad>=5.0" \
    "funasr>=1.2" "modelscope>=1.20" "FlagEmbedding>=1.3"
fi

# 首次运行生成配置（config.toml 不入库，含本机路径）
if [ ! -f engine/config.toml ]; then
  echo "==> 生成 engine/config.toml（来自 config.example.toml）"
  cp engine/config.example.toml engine/config.toml
  # macOS 没有 CUDA：把 ASR 推理设备改为 CPU
  sed -i '' 's/^device = "cuda"$/device = "cpu"/' engine/config.toml 2>/dev/null || \
    sed -i 's/^device = "cuda"$/device = "cpu"/' engine/config.toml
  echo "    已把 [asr].device 改为 cpu（Apple Silicon 如需 GPU 可改 mps）"
fi

mkdir -p .env-local/data .env-local/models

echo ""
echo "==> 完成。下一步："
echo "    1) source config/env.sh"
echo "    2) ./scripts/setup/mac/import_keys.py ~/Downloads/mac-keys.env   # 导入 API key 到钥匙串"
echo "    3) ./scripts/engine/engine_start.sh"
echo "    4) 另开终端: cd shell && pnpm install && pnpm dev"
