# 把本机 keychain 里的 Yuiro API key 导出为 .secrets/mac-keys.env（Windows 侧，迁移用）。
#
# 输出目录 .secrets/ 已在 .gitignore 中，绝不入库；屏幕只打印导出了哪些项。
#
# 用法（仓库根目录）：
#   .\scripts\setup\mac\export_keys.ps1
# 然后把 .secrets\mac-keys.env 用 AirDrop / iCloud / U 盘传到 Mac（别走公开聊天）。

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$py = Join-Path $root ".env-local\engine-venv2\Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "找不到 engine venv: $py" -ForegroundColor Red
    exit 1
}

& $py (Join-Path $root "scripts\setup\mac\export_keys.py")
