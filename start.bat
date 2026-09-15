@echo off
rem Corporate Journey Hub - one-click start (auto-closes when services are up)
rem Default: single mode (one process, port 8001). Add "micro" for 3-port mode.
rem Fresh start (clear previous trips/logs first): start.bat fresh  or double-click 干净启动.bat
rem Persistent console: double-click 总控台.bat  |  Stop: double-click 停止.bat
title Corporate Journey Hub - Start
setlocal
set "NODE_OPTIONS="
where python >nul 2>nul
if errorlevel 1 (
    echo Python not found. Please install Python 3.10+ and add to PATH.
    pause
    exit /b 1
)
python "%~dp0launcher.py" %*
endlocal
