@echo off
setlocal
set "NODE_OPTIONS="
where python >nul 2>nul
if errorlevel 1 (
    echo Python not found. Please install Python 3.10+ and add to PATH.
    pause
    exit /b 1
)
echo Installing PyInstaller...
python -m pip install pyinstaller -q
if errorlevel 1 (
    echo PyInstaller install failed.
    pause
    exit /b 1
)
echo Building one-file exe (CorporateJourneyHub)...
python -m PyInstaller --onefile --console --clean --name CorporateJourneyHub "%~dp0launcher.py"
if exist "dist\CorporateJourneyHub.exe" (
    copy /Y "dist\CorporateJourneyHub.exe" "%~dp0CorporateJourneyHub.exe" >nul
    echo.
    echo Build complete: CorporateJourneyHub.exe
    echo Place it in the project root (same dir as frontend/ and launcher.py).
) else (
    echo Build failed, see output above.
    pause
)
endlocal
