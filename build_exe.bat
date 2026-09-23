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
set "PY=python"

:run
echo ============================================================
echo  Corporate Journey Hub - Build EXE
echo  Intermediate files go to .build/  -  the root stays clean
echo ============================================================
echo.

"%PY%" "%~dp0scripts\build_exe.py" %*

if errorlevel 1 (
    echo.
    echo [FAILED] Build did not complete. See the output above.
) else (
    echo.
    echo [OK] CorporateJourneyHub.exe is ready in the project root.
)

echo.
pause
endlocal
