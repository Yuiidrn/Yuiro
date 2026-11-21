#!/usr/bin/env python3
"""把本机 keychain 里的 Yuiro API key 导出为 .secrets/mac-keys.env（迁移用）。

安全约束：
  - 输出落在 <仓库>/.secrets/ 下，该目录已列入 .gitignore，绝不入库；
  - 屏幕只打印「导出了哪些项」，不打印 key 本身；
  - 传到 Mac 并导入钥匙串后请立即删除该文件。

用法（Windows 仓库根目录）：
    .env-local\\engine-venv2\\Scripts\\python.exe scripts\\setup\\mac\\export_keys.py
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / ".secrets" / "mac-keys.env"

# 与 engine/yuiro/keychain.py 的命名空间一致
ITEMS = [
    ("YUIRO_LLM_KEY", "yuiro-engine", "llm", "LLM 对话"),
    ("YUIRO_SILICONFLOW_KEY", "yuiro-siliconflow", "tts", "SiliconFlow TTS"),
    ("YUIRO_SEARCH_KEY", "yuiro-deepseek-search", "search", "联网检索"),
    ("YUIRO_FISH_KEY", "yuiro-fish", "tts", "Fish TTS"),
]


def main() -> int:
    try:
        import keyring
    except ImportError:
        print("当前解释器没有 keyring，请用 engine venv 运行本脚本", file=sys.stderr)
        return 1

    lines = [
        "# Yuiro 迁移密钥（明文，仅本地传输用；导入 Mac 钥匙串后立即删除）",
        f"# 生成时间: {datetime.now():%Y-%m-%d %H:%M:%S}",
        "",
    ]
    count = 0
    for env_name, service, username, label in ITEMS:
        try:
            secret = keyring.get_password(service, username)
        except Exception as exc:  # noqa: BLE001 — 后端异常不代表 key 不存在
            print(f"读取 {label} 失败: {type(exc).__name__}", file=sys.stderr)
            continue
        if not secret:
            print(f"跳过 {label}（keychain 中不存在）")
            continue
        lines.append(f"{env_name}={secret}")
        count += 1
        print(f"已导出 {label}")

    if count == 0:
        print("没有可导出的 key（keychain 中未找到 Yuiro 条目）", file=sys.stderr)
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n已写入 {OUT}（{count} 项）")
    print("传到 Mac 后执行：")
    print("  ./.venv/bin/python scripts/setup/mac/import_keys.py ~/Downloads/mac-keys.env")
    print("导入完成后请删除本文件。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
