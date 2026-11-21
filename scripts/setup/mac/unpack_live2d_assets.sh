#!/usr/bin/env bash
# 解压 Hotaru Shiomi 的 Live2D 资源到壳层静态目录（macOS / Linux）。
#
# 配套 pack_live2d_assets.ps1（Windows 侧打包）。该目录不进 git，原因见打包脚本注释。
#
# 用法（仓库根目录）：
#   ./scripts/setup/mac/unpack_live2d_assets.sh ~/Downloads/yuiro-live2d-hotaru-20261121.zip
#
# 行为：
#   1. 若同目录有 .sha256，先校验；
#   2. 解压到临时目录，只取 "Hotaru Shiomi/"；
#   3. 目标已存在时先备份到 .env-local/backup/（不直接删除）；
#   4. 校验 model3.json 存在。
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "用法: $0 <yuiro-live2d-hotaru-*.zip>" >&2
  exit 2
fi

ZIP="$1"
if [ ! -f "$ZIP" ]; then
  echo "找不到压缩包: $ZIP" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
DEST="$ROOT/shell/src/renderer/public/live2d"

# 1) 校验（.sha256 与 zip 同目录、同名前缀）
if [ -f "$ZIP.sha256" ]; then
  echo "==> 校验 SHA256"
  ( cd "$(dirname "$ZIP")" && shasum -a 256 -c "$(basename "$ZIP").sha256" )
else
  echo "==> 未找到 $ZIP.sha256，跳过校验"
fi

# 2) 解压到临时目录
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
echo "==> 解压到临时目录"
unzip -q "$ZIP" -d "$TMP"

SRC="$TMP/Hotaru Shiomi"
if [ ! -d "$SRC" ]; then
  echo "压缩包内没有 'Hotaru Shiomi' 目录，内容可能不符合预期：" >&2
  ls -1 "$TMP" >&2
  exit 1
fi
rm -rf "$SRC/__MACOSX" 2>/dev/null || true

# 3) 已有目录先备份，避免覆盖后无法回退
if [ -d "$DEST/Hotaru Shiomi" ]; then
  BACKUP="$ROOT/.env-local/backup"
  mkdir -p "$BACKUP"
  STAMP="$(date +%Y%m%d%H%M%S)"
  echo "==> 目标已存在，备份到 $BACKUP/Hotaru Shiomi.$STAMP"
  mv "$DEST/Hotaru Shiomi" "$BACKUP/Hotaru Shiomi.$STAMP"
fi

mkdir -p "$DEST"
mv "$SRC" "$DEST/Hotaru Shiomi"

# 4) 快速校验
CHECK="$DEST/Hotaru Shiomi/016_casual_spring_01/016_casual_spring_01.model3.json"
if [ ! -f "$CHECK" ]; then
  echo "解压完成，但未找到预期的 model3.json：$CHECK" >&2
  echo "请检查压缩包是否包含了 016_casual_spring_01 目录。" >&2
  exit 1
fi

COUNT="$(find "$DEST/Hotaru Shiomi" -type f | wc -l | tr -d ' ')"
echo ""
echo "==> 完成：$DEST/Hotaru Shiomi（$COUNT 个文件）"
echo "    壳层若已在运行，刷新窗口或重启 pnpm dev 即可在「外观」页看到 Hotaru。"
echo "    该目录仍被 .gitignore 排除，不会进入 git 索引。"
