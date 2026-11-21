# 仅抓取网易云主窗口。截图含私人界面信息，只保存在本地临时目录。
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;using System.Runtime.InteropServices;
public class NcmTargetCapture {
[StructLayout(LayoutKind.Sequential)] public struct RECT {public int Left,Top,Right,Bottom;}
[DllImport("user32.dll")] public static extern IntPtr SetThreadDpiAwarenessContext(IntPtr ctx);
[DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hwnd,out RECT r);
[DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hwnd,IntPtr dc,uint flags);
}
'@
[NcmTargetCapture]::SetThreadDpiAwarenessContext([IntPtr](-4))|Out-Null
$clientProc=Get-Process cloudmusic|Where-Object MainWindowHandle -ne 0|Select-Object -First 1
if (-not $clientProc) {throw 'NetEase main window unavailable'}
$r=New-Object NcmTargetCapture+RECT
if (-not [NcmTargetCapture]::GetWindowRect($clientProc.MainWindowHandle,[ref]$r)) {throw 'Cannot read target rectangle'}
$bmp=New-Object System.Drawing.Bitmap(($r.Right-$r.Left),($r.Bottom-$r.Top))
$g=[System.Drawing.Graphics]::FromImage($bmp)
$dc=$g.GetHdc()
try {
 if (-not [NcmTargetCapture]::PrintWindow($clientProc.MainWindowHandle,$dc,2)) {throw 'Target capture failed'}
} finally {$g.ReleaseHdc($dc)}
try {$bmp.Save((Join-Path $PSScriptRoot '../../.env-local/acceptance/netease-client-window.png'))}
finally {$g.Dispose();$bmp.Dispose()}
