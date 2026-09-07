@echo off
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
