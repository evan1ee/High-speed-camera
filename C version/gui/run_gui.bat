@echo off
setlocal

rem Launch the Qt GUI. Prepends Runtime\x64 to PATH so Windows can find
rem MVSDKmd.dll and its dependent DLLs (same trick as run_capture.bat).

set "ROOT=%~dp0.."
set "PATH=%ROOT%\Runtime\x64;%PATH%"
set "EXE=%~dp0build\Release\capture_gui_qt.exe"

if not exist "%EXE%" (
  echo Missing executable: %EXE%
  echo Build it first with build_gui.bat.
  exit /b 1
)

"%EXE%" %*
