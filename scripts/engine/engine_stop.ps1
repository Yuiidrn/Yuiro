# 停止所有占用 8200 的 Yuiro 引擎进程及其 BGE-M3 嵌入 worker 子进程，
# 以及 5005 的本地 TTS 服务（yuiro.tts_server.server）、5000 的 GPT-SoVITS 服务（外部 Bundle api.py）。
# 使用 WMI Terminate（能终止普通 Stop-Process/taskkill 无法结束的 Session 1 进程）。
$ErrorActionPreference = "SilentlyContinue"
$ports = @(8200, 5005, 5000)

Write-Host "==> 查找占用端口 $($ports -join '/') 的进程..."

# 1) 直接占用端口的进程
$listenPids = @()
foreach ($p in $ports) {
    $listenPids += @(Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique)
}
# 2) 所有 uvicorn 引擎主进程
$enginePids = @(Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*yuiro.main:app*" -and $_.CommandLine -like "*uvicorn*" } |
    Select-Object -ExpandProperty ProcessId)
# 3) 本地 TTS 服务进程（yuiro.tts_server.server = CosyVoice，端口 5005）
$ttsPids = @(Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*yuiro.tts_server.server*" } |
    Select-Object -ExpandProperty ProcessId)
# 4) GPT-SoVITS 服务进程（外部 Bundle runtime 的 api.py，端口 5000）
$gptPids = @(Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*GPT-SoVITS*api.py*" -and $_.CommandLine -like "*-p*5000*" } |
    Select-Object -ExpandProperty ProcessId)

$kill = @($listenPids + $enginePids + $ttsPids + $gptPids | Sort-Object -Unique)
if ($kill.Count -eq 0) {
    Write-Host "==> 端口 $($ports -join '/') 无占用，无需清理。"
    exit 0
}

Write-Host "==> 待终止 PID: $($kill -join ', ')"
# 先杀子进程（worker 由 engine 主进程派生），再杀主进程
foreach ($p in (Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -in $kill })) {
    $r = Invoke-CimMethod -InputObject $p -MethodName Terminate
    Write-Host "  terminate $($p.ProcessId) => $($r.ReturnValue)"
}
# 连带清理派生 worker
Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*multiprocessing-fork*" } |
    ForEach-Object { Invoke-CimMethod -InputObject $_ -MethodName Terminate | Out-Null }

Start-Sleep -Seconds 2
$still = @()
foreach ($p in $ports) {
    $still += @(Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)
}
if ($still.Count -gt 0) {
    Write-Host "WARN: 端口 $($ports -join '/') 仍被占用，可能需管理员权限。"
    exit 1
}
Write-Host "==> 引擎与 TTS 服务已停止，端口 $($ports -join '/') 已释放。"
