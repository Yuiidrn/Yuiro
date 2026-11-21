#!/usr/bin/env python3
"""把 mac-keys.env 里的 API key 写入 macOS 钥匙串（keyring）。

为什么需要它：Yuiro 的 key 一律走 OS keychain（见 engine/yuiro/keychain.py），
配置文件里只有引用、没有明文。Windows 的凭据管理器不会跟着仓库走，所以新机器
需要把 key 重新灌进钥匙串。本脚本只读本地文件、只写 keyring，不打印 key 内容。

用法（macOS，仓库根目录）：
    ./.venv/bin/python scripts/setup/mac/import_keys.py ~/Downloads/mac-keys.env

文件格式（每行 KEY=VALUE，# 开头为注释）：
    YUIRO_LLM_KEY=sk-...
    YUIRO_SILICONFLOW_KEY=sk-...
    YUIRO_SEARCH_KEY=sk-...
"""
from __future__ import annotations

import sys
from pathlib import Path

# 与 engine/yuiro/keychain.py 保持一致的命名空间，勿随意改动
TARGETS = {
    "YUIRO_LLM_KEY": ("yuiro-engine", "llm", "LLM 对话"),
    "YUIRO_SILICONFLOW_KEY": ("yuiro-siliconflow", "tts", "SiliconFlow TTS"),
    "YUIRO_SEARCH_KEY": ("yuiro-deepseek-search", "search", "联网检索"),
    "YUIRO_FISH_KEY": ("yuiro-fish", "tts", "Fish TTS"),
}


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value:
            values[key] = value
    return values


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    src = Path(argv[1]).expanduser()
    if not src.exists():
        print(f"找不到密钥文件: {src}", file=sys.stderr)
        return 1

    try:
        import keyring
    except ImportError:
        print("缺少 keyring：pip install keyring", file=sys.stderr)
        return 1

    values = parse_env_file(src)
    if not values:
        print("密钥文件里没有可用的 KEY=VALUE", file=sys.stderr)
        return 1

    written = 0
    for env_name, (service, username, label) in TARGETS.items():
        secret = values.get(env_name)
        if not secret:
            print(f"跳过 {label}（{env_name} 未提供）")
            continue
        keyring.set_password(service, username, secret)
        print(f"已写入 {label}: keychain[{service}/{username}]")
        written += 1

    if not written:
        print("没有写入任何 key，请检查变量名是否与脚本 TARGETS 一致", file=sys.stderr)
        return 1

    print(f"\n完成：{written} 项已进入钥匙串。建议删除临时文件: rm {src}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
