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

mkdir "%LOCK_DIR%" 2>nul
if errorlevel 1 (
  echo. >> "%LOG_DIR%\scheduled-monitor.log"
  echo ===== %DATE% %TIME% SKIP: run gia attiva ===== >> "%LOG_DIR%\scheduled-monitor.log"
  goto :end
)

echo. >> "%LOG_DIR%\scheduled-monitor.log"
echo ===== %DATE% %TIME% START scheduled monitor ===== >> "%LOG_DIR%\scheduled-monitor.log"

"%PYTHON_EXE%" "%PROJECT_DIR%\agent_portfolio_manager.py" ^
  --autonomous-monitor ^
  --once ^
  --monitor-interval-minutes 30 ^
  --no-auto-deep-confirmation ^
  --scan-limit 5 ^
  --deep-confirm-limit 0 ^
  --max-auto-trade-pct 25 ^
  >> "%LOG_DIR%\scheduled-monitor.log" 2>> "%LOG_DIR%\scheduled-monitor.err.log"

echo ===== %DATE% %TIME% END scheduled monitor exit=%ERRORLEVEL% ===== >> "%LOG_DIR%\scheduled-monitor.log"

rmdir "%LOCK_DIR%" 2>nul

:end
endlocal
