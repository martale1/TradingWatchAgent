$ProjectDir = "C:\Users\theoi\PycharmProjects\TradingWatchAgent"
$ScriptPath = Join-Path $ProjectDir "scripts\run_autonomous_monitor_once.bat"
$TaskName = "TradingWatchAgentMonitor"

if (-not (Test-Path $ScriptPath)) {
    throw "Script non trovato: $ScriptPath"
}

$Action = New-ScheduledTaskAction -Execute $ScriptPath -WorkingDirectory $ProjectDir
$Trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).Date.AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 30) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "TradingWatchAgent autonomous virtual portfolio monitor every 30 minutes." `
    -Force | Out-Null

Write-Host "Task installato: $TaskName"
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
