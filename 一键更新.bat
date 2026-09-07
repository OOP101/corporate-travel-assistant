@echo off
setlocal
set "NODE_OPTIONS="
cd /d "%~dp0"

echo ============================================================
echo  企业智行 - 全面更新（停止服务 - 重新打包EXE - 重启 - 验证）
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+ 并加入 PATH。
    pause
    exit /b 1
)

python "%~dp0scripts\rebuild_and_restart.py" %*

echo.
pause
endlocal
