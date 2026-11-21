"""通过 ModelScope 拉取 SenseVoice-Small 与 FSMN-VAD 权重到本地（国内可达，避免直连 HF CDN）。

用法（须在 engine/ 目录内、venv2 激活状态下）：
    python scripts/download_sensevoice_modelscope.py
或指定输出目录：
    python scripts/download_sensevoice_modelscope.py --out .env-local/models/sensevoice

落盘结构：
    {out}/SenseVoiceSmall/
    {out}/FSMN-VAD/
镜像优先约定见 AGENTS.md：ModelScope 为 HF 模型默认镜像。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 允许从仓库根目录直接运行（venv2 下导入 modelscope）
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))

MODELS = {
    "SenseVoiceSmall": "iic/SenseVoiceSmall",
    "FSMN-VAD": "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download SenseVoice + FSMN-VAD via ModelScope")
    parser.add_argument(
        "--out",
        default=str(ROOT / ".env-local" / "models" / "sensevoice"),
        help="本地输出根目录",
    )
    args = parser.parse_args()
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    try:
        from modelscope import snapshot_download
    except ImportError:
        print("[错误] 未找到 modelscope，请先在 venv2 安装：funasr modelscope", file=sys.stderr)
        return 1

    for name, model_id in MODELS.items():
        target = out_root / name
        print(f"[下载] {model_id} -> {target}")
        try:
            path = snapshot_download(model_id, cache_dir=str(target))
            print(f"[完成] {name}: {path}")
        except Exception as exc:  # noqa: BLE001
            print(f"[失败] {name}: {exc}", file=sys.stderr)
            return 1
    print("[全部完成] SenseVoice + FSMN-VAD 权重已落地。")
    print("提示：在 config.toml [asr]/[hard_of_hearing] 设置 local_model_path 指向上述目录。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
