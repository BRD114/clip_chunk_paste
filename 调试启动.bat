@echo off
rem Debug launcher: keeps a console window so errors are visible.
rem ASCII-only on purpose (see the header of the tray launcher).
setlocal
cd /d "%~dp0"
echo ===== ClipChunkPaste debug launcher =====
echo Working dir: %CD%
echo.

if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0clip_chunk_paste.py" --debug
) else (
    python "%~dp0clip_chunk_paste.py" --debug
)

echo.
echo ===== exited with code %errorlevel% =====
echo If the window closed instantly, the code above is the reason.
pause
