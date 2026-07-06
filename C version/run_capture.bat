@echo off
setlocal

set ROOT=%~dp0.
set PATH=%ROOT%\Runtime\x64;%PATH%
set EXE=%~dp0build\capture_image_cpp.exe

if not exist "%EXE%" (
  echo Missing executable: %EXE%
  echo Run build_msvc.bat first from an x64 Native Tools Command Prompt for VS.
  exit /b 1
)

"%EXE%" %*
