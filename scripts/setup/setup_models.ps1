# 模型与依赖一次性安装脚本（venv2 + 国内镜像优先）
# 须在仓库根目录执行：. .\scripts\setup_models.ps1

$ErrorActionPreference = "Stop"
$Root = Resolve-Path $PSScriptRoot\..
$Venv = Join-Path $Root ".env-local\engine-venv2"
$Py = Join-Path $Venv "Scripts\python.exe"
$Uv = "D:\software\ComfyUI-aki-v3\ComfyUI-aki-v3\python\Scripts\uv.exe"

# 1) 用阿里云 PyPI 镜像安装 runtime 依赖（含 funasr / modelscope）
Write-Host "[1/3] 安装语音运行时依赖 (funasr, modelscope)…" -ForegroundColor Cyan
& $Uv pip install --python $Py --index-url https://mirrors.aliyun.com/pypi/simple/ `
    "funasr>=1.2" "modelscope>=1.20" "faster-whisper>=1.0" "silero-vad>=5.0"

# 2) 下载本地模型（BGE-M3 走 ModelScope，见 AGENTS.md 镜像优先约定）
Write-Host "[2/3] 下载 BGE-M3 嵌入模型（ModelScope）…" -ForegroundColor Cyan
& $Py $Root\scripts\setup\downloads\download_bge_m3_modelscope.py

# 3) 下载 SenseVoice-Small + FSMN-VAD（ModelScope）
Write-Host "[3/3] 下载 SenseVoice + FSMN-VAD（ModelScope）…" -ForegroundColor Cyan
& $Py $Root\scripts\setup\downloads\download_sensevoice_modelscope.py

Write-Host "模型与依赖安装完成。" -ForegroundColor Green
