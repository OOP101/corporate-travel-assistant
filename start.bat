@echo off
rem Corporate Journey Hub - one-click start (auto-closes when services are up)
rem Default: single core service - one process, one port 8001.
rem "micro" is a retired alias (same behaviour as default); no 8002/8003 ports exist.
rem Add "fresh" to clear previous trips/logs before starting.
rem Stop: double-click the stop script (stop.bat equivalent).
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
