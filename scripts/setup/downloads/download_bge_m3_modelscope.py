"""从 ModelScope（国内可达）下载 BGE-M3 嵌入模型到本地目录。

背景：Yuiro 的语义记忆需要 BAAI/bge-m3（约 2.3GB）。该模型默认从 HuggingFace Hub
下载，但本机网络对 HF CDN 不可达。本脚本改用 ModelScope 镜像源（国内直连）拉取，
落到本地目录后，在 engine/config.toml 的 [memory] 段把 embedder 指向该目录即可
（FlagEmbedding/transformers 检测到目录存在会直接本地加载，不再触发任何下载）。

用法（在 engine-venv 中执行）：
    & .env-local/engine-venv/Scripts/python.exe scripts/download_bge_m3_modelscope.py

可选环境变量：
    YUIRO_BGE3_LOCAL_DIR  覆盖本地落盘目录（默认 engine/models/bge-m3）
    MODELSCOPE_CACHE       modelscope 自身缓存目录（默认 .env-local/modelscope-cache）

依赖：modelscope（pip install modelscope，国内源可装，无需 VPN）。
下载支持断点续传：中断后重跑本脚本会从已下载处继续。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 仓库根目录（config/env.ps1 已将 YUIRO_ROOT 设好；这里兜底用脚本相对路径推导）
ROOT = Path(os.environ.get("YUIRO_ROOT", Path(__file__).resolve().parents[3]))
# 落盘目录与 scripts/fetch_bge.py 的 LOCAL_DIR（engine/models/bge-m3，相对 engine 工作目录）
# 保持同一处：两脚本曾各下一份，磁盘上出现 2.2GB + 4.4GB 两份重复权重（2026-09-29 清理）。
DEFAULT_LOCAL_DIR = ROOT / "engine" / "models" / "bge-m3"
MODEL_ID = "BAAI/bge-m3"


def main() -> int:
    local_dir = Path(os.environ.get("YUIRO_BGE3_LOCAL_DIR", DEFAULT_LOCAL_DIR)).resolve()
    cache_dir = Path(os.environ.get("MODELSCOPE_CACHE", ROOT / ".env-local" / "modelscope-cache"))

    print(f"[bge-m3] ModelScope 源: {MODEL_ID}")
    print(f"[bge-m3] 本地落盘目录: {local_dir}")
    print(f"[bge-m3] modelscope 缓存: {cache_dir}")

    try:
        from modelscope import snapshot_download
    except ImportError:
        print(
            "[bge-m3] 未安装 modelscope。请先执行：\n"
            f"  & {ROOT / '.env-local' / 'engine-venv' / 'Scripts' / 'python.exe'}"
            " -m pip install modelscope",
            file=sys.stderr,
        )
        return 1

    # 下载到 cache，再拷贝到 local_dir。
    # snapshot_download(local_dir=...) 会把模型文件直接落盘到该目录（Windows 下默认拷贝）。
    local_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        path = snapshot_download(
            model_id=MODEL_ID,
            cache_dir=str(cache_dir),
            local_dir=str(local_dir),
            revision="master",
        )
    except Exception as exc:  # noqa: BLE001 - 网络/鉴权错误需明确提示
        print(f"[bge-m3] 下载失败：{exc}", file=sys.stderr)
        print("[bge-m3] 可重试本脚本（支持断点续传）。若仍失败，检查网络是否能访问 modelscope.cn。",
              file=sys.stderr)
        return 1

    print(f"[bge-m3] 下载完成：{path}")
    print("[bge-m3] 下一步：在 engine/config.toml 中将 [memory] 段改为：")
    print(f'  embedder = "{local_dir}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
