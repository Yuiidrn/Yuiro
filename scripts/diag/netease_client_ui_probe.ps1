param()
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$clientProcess = Get-Process -Name cloudmusic -ErrorAction Stop | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $clientProcess) { throw '未找到网易云客户端主窗口' }
$root = [System.Windows.Automation.AutomationElement]::FromHandle($clientProcess.MainWindowHandle)
$nodes = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
$safeNodes = @()
foreach ($node in $nodes) {
    try {
        $name = $node.Current.Name
        if ($name -notmatch 'Monody|TheFatRat|Laura Brehm|播放|暂停|停止|搜索|search') { continue }
        $rect = $node.Current.BoundingRectangle
        $safeNodes += [pscustomobject]@{ name=$name; type=$node.Current.ControlType.ProgrammaticName; x=$rect.X; y=$rect.Y; width=$rect.Width; height=$rect.Height; automationId=$node.Current.AutomationId }
    } catch { }
}
[pscustomobject]@{ clientVersion=$clientProcess.MainModule.FileVersionInfo.FileVersion; nodeCount=$nodes.Count; matchingControls=$safeNodes } | ConvertTo-Json -Depth 5 -Compress
