@echo off
setlocal

rem Build a self-contained, copy-anywhere folder for the Qt GUI.
rem Output: gui\dist\capture_gui_qt\  (exe + Qt DLLs + IMV SDK DLLs + MSVC runtime)
rem
rem Run build_gui.bat first so build\Release exists, then run this.
rem Copy the whole dist\capture_gui_qt folder to the other PC and double-click
rem capture_gui_qt.exe. No PATH setup needed; the IMV DLLs sit next to the exe.

set "GUI_DIR=%~dp0"
set "REL=%GUI_DIR%build\Release"
set "RT=%GUI_DIR%..\Runtime\x64"
set "DIST=%GUI_DIR%dist\capture_gui_qt"

if not exist "%REL%\capture_gui_qt.exe" (
  echo Missing %REL%\capture_gui_qt.exe
  echo Build first with build_gui.bat.
  exit /b 1
)
if not exist "%RT%\MVSDKmd.dll" (
  echo Missing IMV runtime at %RT%
  exit /b 1
)

if exist "%DIST%" rmdir /s /q "%DIST%"
mkdir "%DIST%"

rem 1) exe + Qt DLLs + plugin folders (from windeployqt)
robocopy "%REL%" "%DIST%" /E /XF hsc_tests.* *.log *.tmp /XD settings data /NFL /NDL /NJH /NJS >nul
rem 2) IMV SDK runtime DLLs + deps (also supplies the MSVC runtime) next to the exe
robocopy "%RT%" "%DIST%" /E /NFL /NDL /NJH /NJS >nul

if not exist "%DIST%\capture_gui_qt.exe" ( echo Packaging failed. & exit /b 1 )
if not exist "%DIST%\MVSDKmd.dll"        ( echo Packaging failed: no MVSDKmd.dll. & exit /b 1 )

echo.
echo Portable package ready: %DIST%
echo Copy that whole folder to the target PC and run capture_gui_qt.exe.
echo (The target PC still needs the camera USB driver installed once.)
