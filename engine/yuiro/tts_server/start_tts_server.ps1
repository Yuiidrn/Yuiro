# 启动本地 TTS 服务（独立进程，GPU 推理 CosyVoice2）
# 在任何目录下执行：& .\engine\yuiro\tts_server\start_tts_server.ps1
# 实际用 venv2 跑 yuiro 包内的 yuiro.tts_server.server（cwd 切到 engine/，保证 yuiro 包可导入）

$ErrorActionPreference = "Stop"

# 基于脚本位置定位：yuiro/tts_server -> yuiro -> engine -> 仓库根
$EngineRoot = $PSScriptRoot | Split-Path -Parent | Split-Path -Parent   # yuiro/tts_server -> engine
$Root = $EngineRoot | Split-Path -Parent                                # engine -> 仓库根

# 加载本地环境（设置 YUIRO_* + 缓存重定向到 .env-local；用绝对路径，与 cwd 无关）
if (Test-Path (Join-Path $Root "config\env.ps1")) { . (Join-Path $Root "config\env.ps1") }

# cwd 切到 engine/：`python -m yuiro.tts_server.server` 才找得到 yuiro 包
Set-Location $EngineRoot

$Py = Join-Path $Root ".env-local\engine-venv2\Scripts\python.exe"
$Venv = Join-Path $Root ".env-local\engine-venv2"

# CosyVoice2 推理（onnxruntime CUDA EP）依赖 nvidia 各包的 DLL：
# cuda_runtime(cudart) + cublas(cublasLt) + cudnn9 + cufft + curand + nvrtc + nvjitlink，
# 全部在 nvidia/<pkg>/bin 下。遍历 nvidia 下所有子包 bin 加进 PATH，缺一不可（否则 error 126）。
$nvRoot = Join-Path $Venv "Lib\site-packages\nvidia"
Get-ChildItem $nvRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object {
    $bin = Join-Path $_.FullName "bin"
    if (Test-Path $bin) { $env:PATH = "$bin;" + $env:PATH }
}

# tqdm 进度条关掉，避免刷屏；模型加载日志走 logging
$env:TQDM_DISABLE = "1"

Write-Host "[tts-server] 启动 CosyVoice2 @ 127.0.0.1:5005 (venv2, cwd=$EngineRoot)"
& $Py -m yuiro.tts_server.server --host 127.0.0.1 --port 5005
