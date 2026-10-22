@echo off
rem ============================================================
rem  ClipChunkPaste launcher (tray, no console window)
rem  NOTE: keep this file ASCII-only. UTF-8 Chinese text inside a
rem  .bat is mis-parsed under the GBK console codepage and will
rem  break the launcher (the rem lines get executed as commands).
rem ============================================================
setlocal
cd /d "%~dp0"

set "APP=%~dp0clip_chunk_paste.py"

if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%APP%"
    exit /b 0
)

where pythonw >nul 2>nul
if not errorlevel 1 (
    start "" pythonw "%APP%"
    exit /b 0
)

where pyw >nul 2>nul
if not errorlevel 1 (
    start "" pyw -3 "%APP%"
    exit /b 0
)

echo Python not found. Run install_deps.bat first.
pause
