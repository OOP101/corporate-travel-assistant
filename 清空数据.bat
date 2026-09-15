@echo off
rem Corporate Journey Hub - clear runtime data only (no start)
rem Trips / approvals / reimbursements / profiles / logs / caches -> backed up to .backup/ then removed
rem Options: --full (also clear org & policy seed data)  --dry-run (list only)  --no-backup
title Corporate Journey Hub - Clear Runtime Data
setlocal
set "NODE_OPTIONS="
where python >nul 2>nul
if errorlevel 1 (
    echo Python not found. Please install Python 3.10+ and add to PATH.
    pause
    exit /b 1
)
python "%~dp0launcher.py" clean %*
endlocal
