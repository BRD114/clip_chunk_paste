@echo off
rem Create a local .venv and install dependencies. Safe to re-run.
rem ASCII-only on purpose (see the header of the tray launcher).
setlocal
cd /d "%~dp0"

set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    where python >nul 2>nul
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    echo Python not found. Install Python 3.9+ and tick "Add python.exe to PATH".
    pause
    exit /b 1
)

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo [1/2] creating virtual environment .venv ...
    %PY% -m venv "%~dp0.venv"
    if errorlevel 1 goto :fail
)

echo [2/2] installing pystray / pillow ...
"%~dp0.venv\Scripts\python.exe" -m pip install -q --upgrade pip
"%~dp0.venv\Scripts\python.exe" -m pip install -q -r "%~dp0requirements.txt"
if errorlevel 1 goto :fail

echo.
echo Done. Double-click the tray launcher to run.
pause
exit /b 0

:fail
echo.
echo Install failed. Check your network, or run manually:
echo   .venv\Scripts\pip install pystray pillow
pause
exit /b 1
