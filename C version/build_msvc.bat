@echo off
setlocal EnableDelayedExpansion

rem Build with MSVC. This script can run from normal PowerShell/CMD; it will
rem initialize the Visual Studio x64 build environment when cl.exe is not found.
rem It links against the IMV C SDK import library in ..\Development\Lib\x64.

set "ROOT=%~dp0."
set "INCLUDE_DIR=%ROOT%\Development\Include\IMV"
set "LIB_DIR=%ROOT%\Development\Lib\x64"
set "OUT_DIR=%~dp0build"

where cl >nul 2>nul
if errorlevel 1 (
  set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
  if not exist "!VSWHERE!" set "VSWHERE=C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
  if not exist "!VSWHERE!" set "VSWHERE=C:\Program Files\Microsoft Visual Studio\Installer\vswhere.exe"
  if not exist "!VSWHERE!" (
    echo cl.exe was not found, and vswhere.exe was not found.
    echo Install Visual Studio Build Tools with "Desktop development with C++".
    exit /b 1
  )

  for /f "usebackq tokens=*" %%i in (`"!VSWHERE!" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VSINSTALL=%%i"
  if not defined VSINSTALL (
    echo Visual Studio C++ tools were not found.
    echo Install the "Desktop development with C++" workload.
    exit /b 1
  )

  call "!VSINSTALL!\Common7\Tools\VsDevCmd.bat" -arch=x64 -host_arch=x64
  if errorlevel 1 (
    echo Failed to initialize Visual Studio build environment.
    exit /b 1
  )
)

if not exist "%OUT_DIR%" mkdir "%OUT_DIR%"

cl /nologo /EHsc /std:c++17 /O2 ^
  /I "%INCLUDE_DIR%" ^
  /Fo"%OUT_DIR%\capture_image_cpp.obj" ^
  "%~dp0capture_image_cpp.cpp" ^
  /link /LIBPATH:"%LIB_DIR%" MVSDKmd.lib ^
  /OUT:"%OUT_DIR%\capture_image_cpp.exe"

if errorlevel 1 (
  echo Build failed.
  exit /b 1
)

if exist "%OUT_DIR%\capture_image_cpp.obj" del /f /q "%OUT_DIR%\capture_image_cpp.obj"

echo Built: %OUT_DIR%\capture_image_cpp.exe
