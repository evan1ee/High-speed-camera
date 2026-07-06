@echo off
REM Build the High Speed Camera GUI into a transferable Windows folder app.
REM Output: dist\HighSpeedCamera\  (zip this folder and copy it to another PC).
REM
REM Requires: pip install pyinstaller  (one time).

cd /d "%~dp0"

python -m PyInstaller HighSpeedCamera.spec --noconfirm --clean
if errorlevel 1 (
    echo.
    echo BUILD FAILED.
    exit /b 1
)

echo.
echo Build complete: dist\HighSpeedCamera\HighSpeedCamera.exe
echo Zip the dist\HighSpeedCamera folder to transfer the app.
