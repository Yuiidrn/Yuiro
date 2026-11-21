# 在 engine-venv2（独立完整 CPython，由 uv 创建无 pip）上用 uv pip 安装依赖
$ErrorActionPreference = "Stop"
$root = "D:\Project\Yuii\desktop-pet\Yuiro"
$venv = "$root\.env-local\engine-venv2"

# 环境重定向：不占 C 盘
$env:PIP_CACHE_DIR = "$root\.env-local\pip-cache"
$env:UV_CACHE_DIR = "$root\.env-local\uv-cache"
$env:XDG_CACHE_HOME = "$root\.env-local\uv-xdg"
$env:HOME = $root
# 实测官方 pypi.org 可达（npmmirror 的 pypi/simple 路径 404），故用官方默认源
$INDEX = ""

# 定位 uv（优先 PATH，回退到已知携带 uv 的 ComfyUI python 目录）
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) {
    $cand = @(
        "$root\.env-local\uv.exe",
        "$root\scripts\uv.exe",
        "D:\software\ComfyUI-aki-v3\ComfyUI-aki-v3\python\Scripts\uv.exe"
    )
    foreach ($c in $cand) { if (Test-Path $c) { $uv = $c; break } }
}
if (-not $uv) { Write-Error "未找到 uv，请先安装或指定路径"; exit 1 }
Write-Host "==> 使用 uv: $uv"

Write-Host "==> uv pip install -e engine[dev]"
& $uv pip install --python "$venv\Scripts\python.exe" -e "$root\engine[dev]"

Write-Host "==> 安装 modelscope"
& $uv pip install --python "$venv\Scripts\python.exe" modelscope

Write-Host "==> 验证关键导入"
& "$venv\Scripts\python.exe" -c "import fastapi, uvicorn, FlagEmbedding, faster_whisper, sqlite_vec, modelscope; print('OK imports')"

Write-Host "DONE"
