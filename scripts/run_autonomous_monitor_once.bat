@echo off
setlocal
chcp 65001 >nul

set PROJECT_DIR=C:\Users\theoi\PycharmProjects\TradingWatchAgent
set PYTHON_EXE=C:\Users\theoi\anaconda3\envs\openaiAgent\python.exe
set LOG_DIR=%PROJECT_DIR%\logs
set LOCK_DIR=%LOG_DIR%\monitor.lock
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set TRADINGWATCH_TIMESTAMP_LOGS=1

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

cd /d "%PROJECT_DIR%"

for /f %%I in ('powershell -NoProfile -Command "$now=Get-Date; if ($now.DayOfWeek -in @(''Saturday'',''Sunday'') -or $now.Hour -lt 10 -or $now.Hour -ge 21) { ''SKIP'' } else { ''RUN'' }"') do set MARKET_WINDOW=%%I
if "%MARKET_WINDOW%"=="SKIP" (
  echo. >> "%LOG_DIR%\scheduled-monitor.log"
  echo ===== %DATE% %TIME% SKIP: fuori finestra operativa lun-ven 10:00-20:59 ===== >> "%LOG_DIR%\scheduled-monitor.log"
  echo. >> "%LOG_DIR%\run-journal.log"
  echo ===== %DATE% %TIME% SKIP scheduled monitor: fuori finestra operativa lun-ven 10:00-20:59 ===== >> "%LOG_DIR%\run-journal.log"
  goto :end
)

mkdir "%LOCK_DIR%" 2>nul
if errorlevel 1 (
  echo. >> "%LOG_DIR%\scheduled-monitor.log"
  echo ===== %DATE% %TIME% SKIP: run gia attiva ===== >> "%LOG_DIR%\scheduled-monitor.log"
  echo. >> "%LOG_DIR%\run-journal.log"
  echo ===== %DATE% %TIME% SKIP scheduled monitor: run gia attiva ===== >> "%LOG_DIR%\run-journal.log"
  goto :end
)

echo. >> "%LOG_DIR%\scheduled-monitor.log"
echo ===== %DATE% %TIME% START scheduled monitor ===== >> "%LOG_DIR%\scheduled-monitor.log"
echo. >> "%LOG_DIR%\run-journal.log"
echo ===== %DATE% %TIME% START scheduled monitor ===== >> "%LOG_DIR%\run-journal.log"

powershell -NoProfile -ExecutionPolicy Bypass -Command "& '%PYTHON_EXE%' '%PROJECT_DIR%\agent_portfolio_manager.py' --model gpt-5-mini --autonomous-monitor --once --monitor-interval-minutes 30 --periodic-live-news --periodic-max-turns 80 --scan-limit 5 --deep-confirm-limit 2 --max-auto-trade-pct 25 2>&1 | Tee-Object -FilePath '%LOG_DIR%\scheduled-monitor.log' -Append | Tee-Object -FilePath '%LOG_DIR%\run-journal.log' -Append; exit $LASTEXITCODE"

echo ===== %DATE% %TIME% END scheduled monitor exit=%ERRORLEVEL% ===== >> "%LOG_DIR%\scheduled-monitor.log"
echo ===== %DATE% %TIME% END scheduled monitor exit=%ERRORLEVEL% ===== >> "%LOG_DIR%\run-journal.log"

rmdir "%LOCK_DIR%" 2>nul

:end
endlocal
