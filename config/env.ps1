# Yuiro 本地环境加载脚本 (PowerShell)
# 用法：在 Yuiro 根目录  PowerShell:  . .\config\env.ps1
# 作用：把所有 venv / 模型缓存 / 依赖 都指到项目内 .env-local（不占 C 盘）

# 用脚本所在目录定位仓库根（config/ 的上一级），避免依赖"必须在根目录执行"
$env:YUIRO_ROOT       = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$env:YUIRO_DATA_DIR   = Join-Path $env:YUIRO_ROOT '.env-local\data'
$env:YUIRO_MODELS_DIR = Join-Path $env:YUIRO_ROOT '.env-local\models'

# 共享密钥（请改成强随机串；或改为从环境读取而非硬编码）
if (-not $env:YUIRO_SHARED_SECRET) { $env:YUIRO_SHARED_SECRET = 'dev-only-change-me' }

# ---- 模型缓存全部重定向到 .env-local/models/.cache（避开 C:\Users 的默认缓存）----
$env:HF_HOME                 = Join-Path $env:YUIRO_MODELS_DIR 'cache\huggingface'
$env:HUGGINGFACE_HUB_CACHE   = Join-Path $env:HF_HOME 'hub'
$env:TRANSFORMERS_CACHE      = $env:HF_HOME
$env:TORCH_HOME              = Join-Path $env:YUIRO_MODELS_DIR 'cache\torch'
$env:XDG_CACHE_HOME          = Join-Path $env:YUIRO_MODELS_DIR 'cache\xdg'
# faster-whisper 显式指定模型目录
$env:YUIRO_ASR_MODEL_DIR     = Join-Path $env:YUIRO_MODELS_DIR 'faster-whisper'

# 国内镜像：HF 官方源国内直连极慢（~300kB/s），改用镜像加速模型下载
$env:HF_ENDPOINT             = "https://hf-mirror.com"
# bge-m3 等模型使用 Xet 分块存储，镜像源对其转发会偶发 401，禁用 Xet 走普通 HTTP 更稳
$env:HF_HUB_DISABLE_XET      = "1"

# ---- 前端依赖缓存不占 C 盘 ----
$env:npm_config_cache        = Join-Path $env:YUIRO_ROOT '.env-local\npm-cache'
$env:electron_config_cache   = Join-Path $env:YUIRO_ROOT '.env-local\electron-cache'

# ---- mpv：ncm-cli 的播放后端 ----
# 网易云桌面客户端在 Windows 上无法被外部唤起（ncm-cli --player orpheus 明确报
# "仅支持 macOS"，orpheus:// 投递也无效），故点歌统一走 ncm-cli + mpv 播放。
# ncm-cli 的 player 配置只接受 "mpv" 字面量（内部依赖 PATH 查找），
# 因此这里把 mpv 所在目录并入 PATH，保证引擎进程内也能找到。
$env:YUIRO_MPV_DIR = 'D:\cppVenv\mpv'
if (Test-Path (Join-Path $env:YUIRO_MPV_DIR 'mpv.exe')) {
  if ($env:Path -notlike "*$env:YUIRO_MPV_DIR*") {
    $env:Path = "$env:YUIRO_MPV_DIR;$env:Path"
  }
}

Write-Host "[Yuiro] 环境已加载: ROOT=$env:YUIRO_ROOT" -ForegroundColor Green
Write-Host "[Yuiro] MODELS=$env:YUIRO_MODELS_DIR" -ForegroundColor Green
