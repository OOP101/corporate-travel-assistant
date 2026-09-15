@echo off
setlocal
set "NODE_OPTIONS="
cd /d "%~dp0"

echo ============================================================
echo  Corporate Journey Hub - Full Update
echo  (stop services - rebuild EXE - restart - verify)
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+ and add to PATH.
    pause
    exit /b 1
)

python "%~dp0scripts\rebuild_and_restart.py" %*

echo.
pause
endlocal
