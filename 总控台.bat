@echo off
rem Corporate Journey Hub - Control Center (status panel + start/stop/restart/logs)
rem Mode: single = one process on 8001 (default) / micro = 8001 + 8002 + 8003
title Corporate Journey Hub - Control Center
setlocal
set "NODE_OPTIONS="
where python >nul 2>nul
if errorlevel 1 (
    echo Python not found. Please install Python 3.10+ and add to PATH.
    pause
    exit /b 1
)
python "%~dp0launcher.py" menu %*
endlocal
