$ProjectDir = "C:\Users\theoi\PycharmProjects\TradingWatchAgent"
$ScriptPath = Join-Path $ProjectDir "scripts\run_autonomous_monitor_once.bat"
$TaskName = "TradingWatchAgentMonitor"

if (-not (Test-Path $ScriptPath)) {
    throw "Script non trovato: $ScriptPath"
}

$Action = New-ScheduledTaskAction -Execute $ScriptPath -WorkingDirectory $ProjectDir
$Triggers = @()
foreach ($Hour in 9..20) {
    foreach ($Minute in @(0, 30)) {
        $At = (Get-Date).Date.AddHours($Hour).AddMinutes($Minute)
        $Triggers += New-ScheduledTaskTrigger `
            -Weekly `
            -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
            -At $At
    }
}
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Triggers `
    -Settings $Settings `
    -Description "TradingWatchAgent autonomous virtual portfolio monitor every 30 minutes, Monday-Friday 09:00-20:30." `
    -Force | Out-Null

Write-Host "Task installato: $TaskName"
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State
