# Yuiro 引擎启动脚本 (PowerShell)
# 用途：固化引擎启动，确保监听 127.0.0.1:8200，供壳层 WebSocket 连接。
# 用法：在 Yuiro 根目录  PowerShell:  .\scripts\run_engine.ps1

$ErrorActionPreference = 'Stop'

# 加载环境变量（venv / 模型缓存 / 密钥等），必须在进入 engine 目录前加载。
$root = (Get-Location).Path
. (Join-Path $root 'config\env.ps1')

$venvPy = Join-Path $root '.env-local\engine-venv2\Scripts\python.exe'

# 注意：config.py 的 port 只是配置值，uvicorn CLI 必须显式
# --host 127.0.0.1 --port 8200，否则壳层（ws://127.0.0.1:8200/ws/control）连不上。
Push-Location (Join-Path $root 'engine')
try {
    & $venvPy -m uvicorn yuiro.main:app --host 127.0.0.1 --port 8200
} finally {
    Pop-Location
}
