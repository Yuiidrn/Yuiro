"""补齐 BGE-M3 模型 —— 语义检索/语义匹配的前提。

**为什么要这个脚本**：本机 HF 主站不可达（DNS 失败），而 `~/.cache/huggingface`
里的 BGE-M3 曾下载中断（缺 pytorch_model.bin），导致 `Embedder` 一直静默降级到
md5 向量（无语义）——表现是"记忆召回调不准、语义匹配全错"。

`hf-mirror.com` 在国内可达，故显式指定 endpoint。`snapshot_download` 支持断点续传，
已下的分片不会重下。

用法：
    python scripts/fetch_bge.py                # 只补必需权重（跳过约 2GB 的 onnx）
    python scripts/fetch_bge.py --with-onnx    # 连 onnx 一起下（FlagEmbedding 用不到）
    python scripts/fetch_bge.py --verify       # 只体检，不下载
"""
from __future__ import annotations

import os
import sys

# 必须在 import huggingface_hub 之前设置：endpoint 在 import 时读取
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
# 镜像站**不支持 Xet 存储后端**（会转发到 cas-server.xethub.hf.co 并返回 401）。
# 必须显式回退到传统 HTTP 下载，否则报 "CAS Client Error: 401 Unauthorized"。
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
# 镜像速度波动大，放宽超时，避免大文件（2.2GB）传到一半被判超时。
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")

#: FlagEmbedding 走 PyTorch 路径，只需要这些；onnx 那套约 2GB 可以不下载。
NEEDED_PATTERNS = ["*.json", "*.txt", "*.model", "pytorch_model.bin", "sentencepiece*"]
ONNX_PATTERNS = ["onnx/*", "*.onnx"]

#: 落盘目录（相对 engine 工作目录）。**必须落到本地目录**，而不是只补 HF 缓存：
#: transformers 加载前会校验整个 snapshot，缺 onnx/model.onnx_data 就直接拒载 ——
#: 明明权重齐了也起不来（这是补齐过程中踩的第三个坑）。
LOCAL_DIR = "models/bge-m3"


def verify() -> bool:
    """体检：模型文件是否齐全。返回是否可用。"""
    try:
        from huggingface_hub import try_to_load_from_cache

        missing = [
            f
            for f in ("config.json", "tokenizer.json", "pytorch_model.bin")
            if not isinstance(try_to_load_from_cache("BAAI/bge-m3", f), str)
        ]
    except Exception as exc:  # noqa: BLE001
        print(f"体检失败：{exc}")
        return False
    if missing:
        print(f"模型不完整，缺：{missing}")
        return False
    print("模型文件齐全 ✓")
    return True


def main() -> int:
    if "--verify" in sys.argv:
        return 0 if verify() else 1

    from huggingface_hub import snapshot_download

    patterns = list(NEEDED_PATTERNS)
    if "--with-onnx" in sys.argv:
        patterns += ONNX_PATTERNS

    # ★ 关键：下到**本地目录**，而不是只留在 HF 缓存里。
    # 原因：只补缓存时，transformers 加载前会校验**整个 snapshot** 的完整性，
    # 发现缺 onnx/model.onnx_data（我们故意不下的 2GB）就直接拒绝加载 ——
    # 于是权重明明齐了，Embedder 仍报"snapshot incomplete"起不来。
    # 指向本地目录则走"本地加载"路径，不触发任何 snapshot 校验与联网。
    print(f"endpoint = {os.environ['HF_ENDPOINT']}")
    print(f"patterns = {patterns}")
    print(f"local_dir = {LOCAL_DIR}")
    path = snapshot_download("BAAI/bge-m3", allow_patterns=patterns, local_dir=LOCAL_DIR)
    print("DONE", path)

    names = set(os.listdir(LOCAL_DIR))
    ok = bool({"pytorch_model.bin", "model.safetensors"} & names)
    print("权重齐全 ✓" if ok else "⚠ 仍然缺少权重文件")
    print(f'下一步：config.toml 的 [memory].embedder 应指向该目录，例如：embedder = "{LOCAL_DIR}"')
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
