@echo off
setlocal EnableDelayedExpansion

rem =========================================================================
rem High Speed Camera - Windows MSI Installer Build Script
rem Compiles GUI & tests, verifies test pass, stages dependencies,
rem and builds the Windows MSI package using WiX Toolset.
rem =========================================================================

set "INSTALLER_DIR=%~dp0"
set "REPO_ROOT=%INSTALLER_DIR%..\"
set "GUI_DIR=%REPO_ROOT%C version\gui\"
set "RUNTIME_DIR=%REPO_ROOT%C version\Runtime\x64\"
set "DRIVERS_DIR=%INSTALLER_DIR%drivers\"
set "STAGING_DIR=%INSTALLER_DIR%staging\"
set "OUTPUT_DIR=%INSTALLER_DIR%dist\"

set "VERSION=%~1"
if "%VERSION%"=="" set "VERSION=1.0.0"

echo =========================================================================
echo High Speed Camera MSI Installer Builder
echo Version: %VERSION%
echo Repository Root: %REPO_ROOT%
echo =========================================================================

rem -------------------------------------------------------------------------
rem 1. Locate Qt Kit
rem -------------------------------------------------------------------------
if not defined QT_DIR (
    if defined QT_ROOT_DIR (
        set "QT_DIR=%QT_ROOT_DIR%"
    ) else if exist "D:\Qt\6.11.1\msvc2022_64\bin\windeployqt.exe" (
        set "QT_DIR=D:\Qt\6.11.1\msvc2022_64"
    ) else if exist "C:\Qt\6.11.1\msvc2022_64\bin\windeployqt.exe" (
        set "QT_DIR=C:\Qt\6.11.1\msvc2022_64"
    ) else if exist "C:\Qt\6.8.0\msvc2022_64\bin\windeployqt.exe" (
        set "QT_DIR=C:\Qt\6.8.0\msvc2022_64"
    ) else (
        rem Try to find qmake/windeployqt on PATH
        for /f "tokens=*" %%I in ('where windeployqt.exe 2^>nul') do (
            for %%P in ("%%~dpI..") do set "QT_DIR=%%~fP"
        )
    )
)

if not exist "%QT_DIR%\bin\windeployqt.exe" (
    echo [ERROR] Qt MSVC kit not found!
    echo Please set QT_DIR, e.g. set QT_DIR=D:\Qt\6.11.1\msvc2022_64
    exit /b 1
)
echo [OK] Using Qt: %QT_DIR%

rem -------------------------------------------------------------------------
rem 2. Verify WiX Toolset
rem -------------------------------------------------------------------------
where wix >nul 2>&1
if errorlevel 1 (
    if exist "%USERPROFILE%\.dotnet\tools\wix.exe" (
        set "PATH=%USERPROFILE%\.dotnet\tools;!PATH!"
        set "WIX_CMD=%USERPROFILE%\.dotnet\tools\wix.exe"
    ) else (
        echo [ERROR] WiX Toolset is required to build the MSI installer.
        echo To install: dotnet tool install --global wix --version 7.0.1
        echo             wix eula accept wix7
        echo             wix extension add -g WixToolset.UI.wixext
        echo             wix extension add -g WixToolset.Util.wixext
        exit /b 1
    )
) else (
    set "WIX_CMD=wix"
)
echo [OK] Using WiX Toolset command: %WIX_CMD%

rem -------------------------------------------------------------------------
rem 3. Build Application and Test Suite
rem -------------------------------------------------------------------------
set "BUILD_DIR=%GUI_DIR%build"
echo.
echo [1/5] Configuring CMake...
cmake -S "%GUI_DIR%." -B "%BUILD_DIR%" -G "Visual Studio 17 2022" -A x64 -DCMAKE_PREFIX_PATH="%QT_DIR%"
if errorlevel 1 (
    echo [ERROR] CMake configure failed.
    exit /b 1
)

echo.
echo [2/5] Building Release binaries (capture_gui_qt, hsc_tests)...
cmake --build "%BUILD_DIR%" --config Release --parallel
if errorlevel 1 (
    echo [ERROR] MSVC build failed.
    exit /b 1
)

rem -------------------------------------------------------------------------
rem 4. Run Verification Tests
rem -------------------------------------------------------------------------
echo.
echo [3/5] Running verification tests before packaging...
set "ORIG_PATH=%PATH%"
set "PATH=%QT_DIR%\bin;%RUNTIME_DIR%;%PATH%"
"%BUILD_DIR%\Release\hsc_tests.exe"
set "TEST_EXIT=!ERRORLEVEL!"
set "PATH=%ORIG_PATH%"

if not "%TEST_EXIT%"=="0" (
    echo [FATAL] Test suite failed! Halting installer packaging.
    exit /b 1
)
echo [OK] All tests passed!

rem -------------------------------------------------------------------------
rem 5. Prepare Staging Directory
rem -------------------------------------------------------------------------
echo.
echo [4/5] Staging payload and deploying Qt runtime...
if exist "%STAGING_DIR%" rmdir /s /q "%STAGING_DIR%"
mkdir "%STAGING_DIR%"
mkdir "%STAGING_DIR%drivers"
mkdir "%STAGING_DIR%data"
mkdir "%STAGING_DIR%settings"

copy "%BUILD_DIR%\Release\capture_gui_qt.exe" "%STAGING_DIR%" >nul
copy "%INSTALLER_DIR%app_icon.ico" "%STAGING_DIR%" >nul
if exist "%REPO_ROOT%app_icon.png" copy "%REPO_ROOT%app_icon.png" "%STAGING_DIR%" >nul

echo Running windeployqt...
"%QT_DIR%\bin\windeployqt.exe" --release --no-translations "%STAGING_DIR%capture_gui_qt.exe"
if errorlevel 1 (
    echo [ERROR] windeployqt failed.
    exit /b 1
)

echo Copying IMV Camera SDK runtime DLLs...
xcopy /E /I /Y "%RUNTIME_DIR%*" "%STAGING_DIR%" >nul

echo Copying camera drivers...
if exist "%DRIVERS_DIR%instUSBDriver.exe" (
    copy "%DRIVERS_DIR%instUSBDriver.exe" "%STAGING_DIR%drivers\" >nul
    echo   - Bundled: instUSBDriver.exe [USB3 Vision Driver]
) else (
    echo   [WARNING] instUSBDriver.exe not found in %DRIVERS_DIR%
)
if exist "%DRIVERS_DIR%instPCIeCXPDriver.exe" (
    copy "%DRIVERS_DIR%instPCIeCXPDriver.exe" "%STAGING_DIR%drivers\" >nul
    echo   - Bundled: instPCIeCXPDriver.exe [CoaXPress Driver]
)

rem -------------------------------------------------------------------------
rem 6. Compile MSI with WiX
rem -------------------------------------------------------------------------
echo.
echo [5/5] Compiling MSI with WiX Toolset...
if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"
set "MSI_NAME=HighSpeedCamera_v%VERSION%_x64.msi"
set "MSI_PATH=%OUTPUT_DIR%%MSI_NAME%"

rem Clean any stale intermediate cab before compiling
if exist "%INSTALLER_DIR%cab1.cab" del /f /q "%INSTALLER_DIR%cab1.cab"

cd /d "%INSTALLER_DIR%"
%WIX_CMD% build "%INSTALLER_DIR%HighSpeedCamera.wxs" ^
    -arch x64 ^
    -ext WixToolset.UI.wixext ^
    -ext WixToolset.Util.wixext ^
    -d ProductVersion="%VERSION%" ^
    -o "%MSI_PATH%"

if errorlevel 1 (
    echo [ERROR] WiX MSI build failed.
    exit /b 1
)

rem Clean up intermediate cab file once embedded in MSI
if exist "%INSTALLER_DIR%cab1.cab" del /f /q "%INSTALLER_DIR%cab1.cab"

echo.
echo =========================================================================
echo [SUCCESS] MSI Installer built successfully:
echo Package: %MSI_PATH%
for %%A in ("%MSI_PATH%") do (
    set /a "SIZE_MB=%%~zA / 1048576"
    echo Size:    %%~zA bytes [~!SIZE_MB! MB]
)
echo =========================================================================
exit /b 0
