@echo off
setlocal EnableDelayedExpansion

rem Build the Qt6 GUI (capture_gui_qt) with the MSVC toolchain and deploy Qt DLLs.
rem Qt must be the MSVC build because the IMV import library (MVSDKmd.lib) is MSVC.
rem
rem Override the Qt kit path with:  set QT_DIR=D:\Qt\6.x.y\msvc2022_64

set "GUI_DIR=%~dp0"
set "BUILD_DIR=%GUI_DIR%build"

if not defined QT_DIR set "QT_DIR=D:\Qt\6.11.1\msvc2022_64"
if not exist "%QT_DIR%\bin\windeployqt.exe" (
  echo Qt kit not found at "%QT_DIR%".
  echo Set QT_DIR to your MSVC Qt kit, e.g. set QT_DIR=D:\Qt\6.11.1\msvc2022_64
  exit /b 1
)

echo Using Qt: %QT_DIR%

cmake -S "%GUI_DIR%." -B "%BUILD_DIR%" -G "Visual Studio 17 2022" -A x64 ^
  -DCMAKE_PREFIX_PATH="%QT_DIR%"
if errorlevel 1 (
  echo CMake configure failed.
  exit /b 1
)

cmake --build "%BUILD_DIR%" --config Release
if errorlevel 1 (
  echo Build failed.
  exit /b 1
)

set "EXE=%BUILD_DIR%\Release\capture_gui_qt.exe"
echo Deploying Qt runtime next to %EXE%
"%QT_DIR%\bin\windeployqt.exe" --release "%EXE%"
if errorlevel 1 (
  echo windeployqt failed.
  exit /b 1
)

echo.
echo Built: %EXE%
echo Run it with run_gui.bat (adds Runtime\x64 to PATH for the IMV DLLs).
