@echo off
setlocal

set PROJECT_DIR=C:\Users\theoi\PycharmProjects\TradingWatchAgent
set PYTHON_EXE=C:\Users\theoi\anaconda3\envs\openaiAgent\python.exe
set LOG_DIR=%PROJECT_DIR%\logs

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

cd /d "%PROJECT_DIR%"

"%PYTHON_EXE%" "%PROJECT_DIR%\telegram_agent_bot.py" ^
  >> "%LOG_DIR%\telegram-agent.log" 2>> "%LOG_DIR%\telegram-agent.err.log"

endlocal
