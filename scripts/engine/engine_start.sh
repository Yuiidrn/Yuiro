#!/usr/bin/env bash
# 启动 Yuiro 引擎（macOS / Linux）
#
# 用法（仓库根目录）：
#   ./scripts/engine/engine_start.sh            # 前台运行，日志直接打在终端
#   ./scripts/engine/engine_start.sh --reload   # 开发热重载（BGE-M3 子进程可能冲突，按需）
#   ./scripts/engine/engine_start.sh --bg       # 后台运行，日志写 .env-local/engine_start.*.log
#
# 与 engine_start.ps1 对齐：先清理 8200 端口残留，再以 engine/ 为工作目录启动
# uvicorn（勿在仓库根启动 —— 配置与 data/ 都是相对 engine/ 解析的）。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PORT="${YUIRO_PORT:-8200}"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="$ROOT/.env-local/engine-venv2/bin/python"
[ -x "$PY" ] || PY="$(command -v python3 || true)"

if [ -z "$PY" ] || [ ! -x "$PY" ]; then
  echo "找不到 Python 解释器。请先执行 scripts/setup/mac/bootstrap.sh" >&2
  exit 1
fi

# shellcheck disable=SC1091
. "$ROOT/config/env.sh" >/dev/null
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

# 1) 清理端口残留
if command -v lsof >/dev/null 2>&1; then
  PIDS="$(lsof -ti "tcp:$PORT" || true)"
  if [ -n "$PIDS" ]; then
    echo "==> 清理 $PORT 端口残留: $PIDS"
    kill $PIDS 2>/dev/null || true
    sleep 1
  fi
fi

ARGS=(-m uvicorn yuiro.main:app --host 127.0.0.1 --port "$PORT")
BG=0
for arg in "$@"; do
  case "$arg" in
    --reload) ARGS+=(--reload) ;;
    --bg) BG=1 ;;
    *) echo "未知参数: $arg" >&2; exit 2 ;;
  esac
done

echo "==> 启动引擎 http://127.0.0.1:$PORT （工作目录 $ROOT/engine）"
cd "$ROOT/engine"

if [ "$BG" -eq 1 ]; then
  LOG_OUT="$ROOT/.env-local/engine_start.out.log"
  LOG_ERR="$ROOT/.env-local/engine_start.err.log"
  mkdir -p "$ROOT/.env-local"
  nohup "$PY" "${ARGS[@]}" >"$LOG_OUT" 2>"$LOG_ERR" &
  echo "==> 后台 PID=$!，日志："
  echo "    tail -f $LOG_OUT"
  echo "    tail -f $LOG_ERR"
else
  exec "$PY" "${ARGS[@]}"
fi
