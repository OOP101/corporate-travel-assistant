@echo off
rem Corporate Journey Hub - fresh start (clear previous trips/logs/caches, then start)
rem Clears: trips / test trips / approvals / reimbursements / profiles / logs / caches
rem Keeps:  data/system (admin & model config), org & policy seed data
rem Backup: old data is moved to .backup/ (latest 3 kept)
title Corporate Journey Hub - Fresh Start
setlocal
set "NODE_OPTIONS="
where python >nul 2>nul
if errorlevel 1 (
    echo Python not found. Please install Python 3.10+ and add to PATH.
    pause
    exit /b 1
)
python "%~dp0launcher.py" fresh %*
endlocal
