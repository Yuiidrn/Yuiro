#!/usr/bin/env bash
# 停止 Yuiro 引擎 / 本地 TTS（macOS / Linux）
#
# 用法：./scripts/engine/engine_stop.sh
# 只杀「监听对应端口」的进程，不会误伤同名的其它 Python 进程。
set -uo pipefail

for PORT in "${YUIRO_PORT:-8200}" 5005 5000; do
  if ! command -v lsof >/dev/null 2>&1; then
    echo "缺少 lsof（macOS 自带；Linux 需 apt install lsof）" >&2
    exit 1
  fi
  PIDS="$(lsof -ti "tcp:$PORT" || true)"
  if [ -n "$PIDS" ]; then
    echo "==> 停止端口 $PORT 上的进程: $PIDS"
    kill $PIDS 2>/dev/null || true
    sleep 1
    PIDS="$(lsof -ti "tcp:$PORT" || true)"
    [ -n "$PIDS" ] && kill -9 $PIDS 2>/dev/null || true
  fi
done
echo "==> 已清理 8200 / 5005 / 5000"
