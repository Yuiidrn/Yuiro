# 启动 Yuiro 引擎（engine-venv2，不带 --reload，避免 uvicorn reloader 与 BGE-M3
# 多进程 spawn 冲突）。启动前自动清理 8200 端口残留，防止 [Errno 10048]。
param(
    [switch]$Reload,   # 可选：传入则使用 --reload（注意：可能与 BGE-M3 子进程冲突，不推荐）
    [switch]$NoTTS     # 可选：传入则不同步启动本地 TTS 服务（端口 5005）
)

$ErrorActionPreference = "Stop"
$root = "D:\Project\Yuii\desktop-pet\Yuiro"
$venv = "$root\.env-local\engine-venv2"
$py = "$venv\Scripts\python.exe"
$port = 8200
$ttsPort = 5005
$logOut = "$root\.env-local\engine_start.out.log"
$logErr = "$root\.env-local\engine_start.err.log"
$ttsLogOut = "$root\.env-local\tts_server.out.log"
$ttsLogErr = "$root\.env-local\tts_server.err.log"

# 加载本地环境（设置 YUIRO_* + 缓存重定向到 .env-local）
if (Test-Path "$root\config\env.ps1") { . "$root\config\env.ps1" }

# 日志编码：强制 Python 使用 UTF-8 模式写 stdout/stderr。
# Windows 上 Python 默认按 cp936(GBK) 输出，而 PowerShell/VSCode 按 UTF-8 读取，
# 会导致中文日志整片乱码。设为 1 后日志文件为 UTF-8，可直接查看。
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

# 1) 先停掉残留进程，避免端口占用（含 8200 与 5005）
& "$root\scripts\engine\engine_stop.ps1"

# 2) 用 venv2 启动引擎（不带 --reload）
Write-Host "==> 启动引擎 (PID 见日志) 于 http://127.0.0.1:$port"
$args = @("-m", "uvicorn", "yuiro.main:app", "--host", "127.0.0.1", "--port", "$port")
if ($Reload) { $args += "--reload" }
Start-Process -FilePath $py -ArgumentList $args `
    -WorkingDirectory "$root\engine" `
    -RedirectStandardOutput $logOut -RedirectStandardError $logErr -NoNewWindow

# 3) 按 config.toml 的 [tts] provider 同步启动对应本地 TTS 服务：
#    gptsovits -> 外部 GPT-SoVITS Bundle（端口 5000，独立 runtime）
#    cosyvoice -> yuiro.tts_server.server（端口 5005，venv2）
#    siliconflow / edge-tts 等云端 provider -> 不起本地服务（engine 直接 HTTPS 调云端，零本地显存）
if (-not $NoTTS) {
    # 读取 [tts] provider（简单 TOML 解析：先按段切分，取 [tts] 段内的 provider= 值）
    $ttsProvider = "edge-tts"
    if (Test-Path "$root\engine\config.toml") {
        $inTts = $false
        foreach ($line in (Get-Content "$root\engine\config.toml" -Encoding UTF8)) {
            $t = $line.Trim()
            if ($t.StartsWith('[')) {
                $inTts = $false
                if ($t -eq '[tts]') { $inTts = $true }
                continue
            }
            if ($inTts -and $t -like 'provider*') {
                $m = [regex]::Match($t, 'provider\s*=\s*"([^"]+)"')
                if ($m.Success) { $ttsProvider = $m.Groups[1].Value; break }
            }
        }
    }
    Write-Host "==> config.toml [tts] provider = $ttsProvider"

    $activeTtsLog = ""   # 记录实际启动的本地 TTS 服务日志，末尾据此打印
    if ($ttsProvider -eq "gptsovits") {
        # GPT-SoVITS：外部 Bundle 独立进程（自带 runtime），engine 侧仅 HTTP 调用
        $activeTtsLog = "$root\.env-local\gptsovits.err.log"
        & "$root\scripts\tts\start_gptsovits.ps1"
    }
    elseif ($ttsProvider -eq "cosyvoice") {
        # CosyVoice：onnxruntime CUDA EP 依赖 nvidia 各包 DLL（cudart/cublasLt/cudnn9/cufft/curand/nvrtc/nvjitlink），
        # 遍历 nvidia 下所有子包 bin 加入 PATH（缺任一 => onnxruntime error 126），Start-Process 子进程会继承。
        $nvRoot = "$venv\Lib\site-packages\nvidia"
        Get-ChildItem $nvRoot -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            $bin = Join-Path $_.FullName "bin"
            if (Test-Path $bin) { $env:PATH = "$bin;" + $env:PATH }
        }
        $env:TQDM_DISABLE = "1"   # 关掉 tqdm 进度条刷屏
        $activeTtsLog = $ttsLogErr
        Write-Host "==> 启动本地 TTS 服务 (PID 见日志) 于 http://127.0.0.1:$ttsPort"
        Start-Process -FilePath $py -ArgumentList @("-m", "yuiro.tts_server.server", "--host", "127.0.0.1", "--port", "$ttsPort") `
            -WorkingDirectory "$root\engine" `
            -RedirectStandardOutput $ttsLogOut -RedirectStandardError $ttsLogErr -NoNewWindow
    }
    else {
        Write-Host "==> provider=$ttsProvider：云端 TTS（siliconflow/edge-tts 类），engine 直连云端，不启动本地 TTS 服务"
    }
}

Start-Sleep -Seconds 6
Write-Host "==> 引擎启动日志尾部："
if (Test-Path $logErr) { Get-Content $logErr -Tail 15 }
if (Test-Path $logOut) { Get-Content $logOut -Tail 10 }
if (-not $NoTTS -and $activeTtsLog) {
    Write-Host "==> TTS 服务启动日志尾部（$activeTtsLog）："
    if (Test-Path $activeTtsLog) { Get-Content $activeTtsLog -Tail 20 }
}
