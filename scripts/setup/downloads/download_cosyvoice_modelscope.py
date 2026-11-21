"""从 ModelScope 下载 CosyVoice2-0.5B 权重到本地（HF 国内常需代理，故用 ModelScope）。

落地目录：.env-local/models/cosyvoice2-0.5B
引擎 tts-server 默认读取该目录（可被 COSYVOICE2_MODEL_DIR 环境变量覆盖）。

用法（venv2，阿里云 PyPI 镜像）：
    & .env-local\\engine-venv2\\Scripts\\python.exe scripts\\download_cosyvoice_modelscope.py
"""
# 注意：本机 modelscope 版本较旧，snapshot_download 不支持 local_dir_use_symlink 参数
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = ROOT / ".env-local" / "models" / "cosyvoice2-0.5B"


def main() -> int:
    try:
        from modelscope import snapshot_download
    except ImportError:
        print(
            "缺少 modelscope，请先安装：\n"
            "  & .env-local\\engine-venv2\\Scripts\\python.exe -m pip install modelscope "
            "-i https://mirrors.aliyun.com/pypi/simple/"
        )
        return 1

    MODEL_DIR.parent.mkdir(parents=True, exist_ok=True)
    print(f"[download] 下载 CosyVoice2-0.5B → {MODEL_DIR}")
    snapshot_download(
        "iic/CosyVoice2-0.5B",
        local_dir=str(MODEL_DIR),
    )
    print("[download] 完成。可启动 tts-server：. .\\tts-server\\start_tts_server.ps1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
