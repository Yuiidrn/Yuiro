# 启动 GPT-SoVITS 本地 TTS 服务（独立进程，GPU 推理，端口 5000）
# 依赖外部 GPT-SoVITS Bundle（自带 runtime\python.exe，与 engine venv 完全隔离）：
#   Bundle 路径由 $Bundle 指定（默认 E:\AI\GPT-SoVITS-v2pro-20250604\GPT-SoVITS-v2pro-20250604）
# 用法（仓库根目录）：
#   & .\scripts\start_gptsovits.ps1                 # 默认角色 MyGO_要乐奈 + 肥牛.wav 参考
#   & .\scripts\start_gptsovits.ps1 -Role 诗歌剧     # 换角色（必须与 GPT_weights_v2ProPlus 内一致）
# 停止：Ctrl+C 或 engine_stop.ps1（会连带清理 5000）

param(
    [string]$Bundle = "E:\AI\GPT-SoVITS-v2pro-20250604\GPT-SoVITS-v2pro-20250604",
    [string]$Role = "MyGO_要乐奈",          # GPT_weights_v2ProPlus / SoVITS_weights_v2ProPlus 下的角色名
    [string]$Port = "5000",
    [string]$Device = "cuda"
)

$ErrorActionPreference = "Stop"
$root = "D:\Project\Yuii\desktop-pet\Yuiro"
$logOut = "$root\.env-local\gptsovits.out.log"
$logErr = "$root\.env-local\gptsovits.err.log"

# 前置检查：Bundle 与 runtime 必须存在
if (-not (Test-Path $Bundle)) { Write-Error "GPT-SoVITS Bundle 不存在: $Bundle（请检查路径或传 -Bundle）" }
$RuntimePy = Join-Path $Bundle "runtime\python.exe"
if (-not (Test-Path $RuntimePy)) { Write-Error "Bundle 缺少 runtime\python.exe: $RuntimePy" }

# 角色权重：GPT(.ckpt) + SoVITS(.pth)，必须配对。
# 文件名带版本后缀（如 MyGO_要乐奈_v2pp.ckpt），按角色名前缀模糊匹配。
$gptDir = Join-Path $Bundle "GPT_weights_v2ProPlus"
$sovitsDir = Join-Path $Bundle "SoVITS_weights_v2ProPlus"
$gpt = Get-ChildItem $gptDir -Filter "$Role*.ckpt" -File -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
$sovits = Get-ChildItem $sovitsDir -Filter "$Role*.pth" -File -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
if (-not $gpt) { Write-Error "找不到 GPT 权重（含角色名 '$Role'）: $gptDir" }
if (-not $sovits) { Write-Error "找不到 SoVITS 权重（含角色名 '$Role'）: $sovitsDir" }

# 参考音频 + 转写文本（音色主体由说话人模型决定，参考音频提供韵律/风格）
$refer = "$root\assets\voices\neuro_prompt.wav"      # Fake Neuro(肥牛) 参考音频
if (-not (Test-Path $refer)) { $refer = "d:\Project\Yuii\desktop-pet\my-neuro\live-2d\fake_neuro_audio\Reference_audio\肥牛.wav" }
if (-not (Test-Path $refer)) { Write-Error "找不到参考音频（期望 assets\voices\neuro_prompt.wav 或 my-neuro 的 肥牛.wav）" }
$referText = "嗯，你说什么？我刚才在想别的事情，你再说一遍试试看。"

# 检查 5000 端口是否被占用
$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    Write-Host "端口 $Port 已被占用（可能是已有 GPT-SoVITS 服务在跑），跳过启动。"
    exit 0
}

Write-Host "==> 启动 GPT-SoVITS 服务 (PID 见日志) @ 127.0.0.1:$Port"
Write-Host "    角色: $Role | 参考: $(Split-Path $refer -Leaf) | 设备: $Device"
Write-Host "    日志: $logErr"

$env:PYTHONUTF8 = "1"
Start-Process -FilePath $RuntimePy -ArgumentList @(
    "api.py",
    "-p", $Port,
    "-d", $Device,
    "-g", $gpt,
    "-s", $sovits,
    "-dr", $refer,
    "-dt", $referText,
    "-dl", "auto"
) -WorkingDirectory $Bundle `
    -RedirectStandardOutput $logOut -RedirectStandardError $logErr -NoNewWindow

# 等待服务就绪（TCP 端口监听检测，最长 90s，GPT-SoVITS 首次加载模型较慢）
Write-Host "等待 GPT-SoVITS 就绪（首次加载模型可能 10-30s）..."
$ready = $false
for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep -Seconds 1
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($conn) { $ready = $true; break }
    if ($i % 15 -eq 14) { Write-Host "  ...等待中 ($($i+1))s" }
}
if ($ready) { Write-Host "==> GPT-SoVITS 服务已监听 @ 127.0.0.1:$Port" }
else {
    Write-Warning "超过 90s 端口仍未监听，请检查日志: $logErr"
    if (Test-Path $logErr) { Get-Content $logErr -Tail 20 }
}
