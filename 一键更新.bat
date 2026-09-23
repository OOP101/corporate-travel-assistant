@echo off
setlocal
set "NODE_OPTIONS="
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if exist "%PY%" goto run
where py >nul 2>nul
if not errorlevel 1 (
    set "PY=py"
    goto run
)
where python >nul 2>nul
if not errorlevel 1 (
    set "PY=python"
    goto run
)
echo [ERROR] Python not found. Install Python 3.10+ or create the .venv first.
pause
exit /b 1

:run
echo ============================================================
echo  Corporate Journey Hub - Full Update
echo  stop services - rebuild EXE - restart - verify
echo ============================================================
echo.

"%PY%" "%~dp0scripts\rebuild_and_restart.py" %*

echo.
pause
endlocal
