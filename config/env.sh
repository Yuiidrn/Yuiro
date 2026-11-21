# Yuiro 本地环境加载脚本（macOS / Linux）
#
# 用法（在仓库根目录）：
#   source config/env.sh
#
# 与 config/env.ps1 对齐：把 venv / 模型缓存 / 依赖全部指到项目内 .env-local，
# 不污染用户主目录（Windows 侧是不占 C 盘，macOS 侧是不占 ~）。

_env_src="${BASH_SOURCE[0]:-$0}"
if [ -f "$_env_src" ]; then
  YUIRO_ROOT="$(cd "$(dirname "$_env_src")/.." && pwd)"
else
  # 某些 shell（极老的 sh）拿不到 sourced 文件路径，回退到当前目录
  YUIRO_ROOT="$(pwd)"
fi
export YUIRO_ROOT

export YUIRO_DATA_DIR="$YUIRO_ROOT/.env-local/data"
export YUIRO_MODELS_DIR="$YUIRO_ROOT/.env-local/models"

# 共享密钥（引擎两个 WS 通道校验；与壳层默认值保持一致，正式环境请改掉）
if [ -z "${YUIRO_SHARED_SECRET:-}" ]; then
  export YUIRO_SHARED_SECRET='dev-only-change-me'
fi

# ---- 模型缓存重定向到 .env-local/models/.cache ----
export HF_HOME="$YUIRO_MODELS_DIR/cache/huggingface"
export HUGGINGFACE_HUB_CACHE="$HF_HOME/hub"
export TRANSFORMERS_CACHE="$HF_HOME"
export TORCH_HOME="$YUIRO_MODELS_DIR/cache/torch"
export XDG_CACHE_HOME="$YUIRO_MODELS_DIR/cache/xdg"
export YUIRO_ASR_MODEL_DIR="$YUIRO_MODELS_DIR/faster-whisper"

# 国内镜像（与 Windows 侧一致；海外网络可自行注释）
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export HF_HUB_DISABLE_XET="1"

# ---- 前端依赖缓存不占用户主目录 ----
export npm_config_cache="$YUIRO_ROOT/.env-local/npm-cache"
export electron_config_cache="$YUIRO_ROOT/.env-local/electron-cache"

# ---- mpv：网易云播放后端（brew install mpv 即可，无需 YUIRO_MPV_DIR）----
# macOS 上 mpv 的 IPC 走 /tmp/yuiro-mpv.sock（见 engine/yuiro/netease/player.py）。

echo "[Yuiro] 环境已加载: ROOT=$YUIRO_ROOT"
echo "[Yuiro] MODELS=$YUIRO_MODELS_DIR"
