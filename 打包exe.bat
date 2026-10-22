@echo off
rem Optional: build a single-file exe (no Python needed). Output: dist\ClipChunkPaste.exe
rem ASCII-only on purpose (see the header of the tray launcher).
setlocal
cd /d "%~dp0"

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Run install_deps.bat first.
    pause
    exit /b 1
)

"%~dp0.venv\Scripts\python.exe" -m pip install -q pyinstaller
if errorlevel 1 goto :fail

"%~dp0.venv\Scripts\python.exe" -m PyInstaller --noconfirm --onefile --noconsole ^
    --name ClipChunkPaste "%~dp0clip_chunk_paste.py"
if errorlevel 1 goto :fail

echo.
echo Built: dist\ClipChunkPaste.exe
echo Tip: create a shortcut to the exe and put it in shell:startup for auto-start.
pause
exit /b 0

:fail
echo.
echo Build failed. See the messages above.
pause
exit /b 1
