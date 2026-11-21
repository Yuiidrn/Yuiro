# 把 Hotaru Shiomi 的 Live2D 资源打成压缩包（Windows 侧，跨机传输用）。
#
# 为什么走压缩包而不是 git：
#   - 该目录 60MB+ / 280 余文件，属于二进制美术资源，几乎不再变动；
#   - 一旦进 git，历史里会永久保留每一版，仓库无限膨胀；
#   - `.gitignore` 已显式排除 `shell/src/renderer/public/live2d/Hotaru Shiomi/`。
#
# 用法（仓库根目录）：
#   .\scripts\setup\mac\pack_live2d_assets.ps1
#   .\scripts\setup\mac\pack_live2d_assets.ps1 -OutDir D:\transfer
#
# 产物：<OutDir>\yuiro-live2d-hotaru-<yyyyMMdd>.zip + 同名 .sha256
# 默认 OutDir = .env-local\transfer（已被 .gitignore 覆盖，不会被误提交）。

param(
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$src = Join-Path $root "shell\src\renderer\public\live2d\Hotaru Shiomi"

if (-not (Test-Path -LiteralPath $src)) {
    Write-Host "找不到源目录: $src" -ForegroundColor Red
    exit 1
}

if (-not $OutDir) {
    $OutDir = Join-Path $root ".env-local\transfer"
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$stamp = Get-Date -Format "yyyyMMdd"
$zip = Join-Path $OutDir "yuiro-live2d-hotaru-$stamp.zip"

$files = Get-ChildItem -LiteralPath $src -Recurse -File
$totalMB = [math]::Round((($files | Measure-Object Length -Sum).Sum) / 1MB, 1)
Write-Host "==> 打包 $src（$($files.Count) 个文件 / $totalMB MB）"

if (Test-Path -LiteralPath $zip) {
    Remove-Item -LiteralPath $zip -Force
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
# 逐条写入，而不是 CreateFromDirectory —— 后者在 Windows PowerShell 下会把条目名
# 写成 "Hotaru Shiomi\016_casual_spring_01\..."（反斜杠），macOS 的 unzip 不认，
# 解压出来会变成一堆名字里带 \ 的扁平文件。ZIP 规范要求分隔符必须是 "/"。
# entryName 统一手工拼 "Hotaru Shiomi/" 前缀，解压到 live2d/ 即可直接用。
$archive = [System.IO.Compression.ZipFile]::Open($zip, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    $prefix = "Hotaru Shiomi/"
    foreach ($f in $files) {
        $rel = $f.FullName.Substring($src.Length + 1).Replace('\', '/')
        $entry = $archive.CreateEntry($prefix + $rel, [System.IO.Compression.CompressionLevel]::Optimal)
        $entry.LastWriteTime = $f.LastWriteTime
        $out = $entry.Open()
        try {
            $in = [System.IO.File]::OpenRead($f.FullName)
            try { $in.CopyTo($out) } finally { $in.Dispose() }
        }
        finally { $out.Dispose() }
    }
}
finally { $archive.Dispose() }

$hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLower()
$zipName = Split-Path -Leaf $zip
"$hash  $zipName" | Set-Content -LiteralPath "$zip.sha256" -Encoding ascii

$zipMB = [math]::Round((Get-Item -LiteralPath $zip).Length / 1MB, 1)
Write-Host ""
Write-Host "已生成: $zip ($zipMB MB)" -ForegroundColor Green
Write-Host "SHA256: $hash" -ForegroundColor Cyan
Write-Host ""
Write-Host "传到 Mac 后执行：" -ForegroundColor Cyan
Write-Host "  ./scripts/setup/mac/unpack_live2d_assets.sh ~/Downloads/$zipName" -ForegroundColor Cyan
