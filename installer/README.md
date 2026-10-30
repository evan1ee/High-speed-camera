# High Speed Camera - Windows MSI Installer & CI Workflow

This directory contains the packaging tooling and WiX configuration for building the enterprise-ready Windows MSI installer (`HighSpeedCamera_v<version>_x64.msi`) for test rig PCs.

---

## 1. Architecture Highlights

### User-Writable Directory Architecture
- **Default Installation Target**: `C:\HighSpeedCamera` (rooted via `[WindowsVolume]HighSpeedCamera` rather than `Program Files`).
- **Permissions**: Grants standard Windows `Users` security group full read/write/modify access (`GenericAll="yes"`) via WiX `WixToolset.Util.wixext` (`PermissionEx`).
- **Why**: Test rig operators actively record high-speed burst frames, export raw BMP/AVI datasets, and update local calibrations (`calibration.json`, `reference.json`). Standard `Program Files` installations trigger Windows UAC permission errors when standard operators run test routines.
- **Dedicated Subdirectories**:
  - `C:\HighSpeedCamera\data\`: Operator burst runs and video exports.
  - `C:\HighSpeedCamera\settings\`: Camera parameters and calibration stores.
  - `C:\HighSpeedCamera\drivers\`: Camera driver installers and repair utilities.

### Camera Driver Integration
- **Driver Executable**: `drivers\instUSBDriver.exe` (USB3 Vision camera driver for Huaray / iRayple industrial cameras).
- **Silent Deferred Custom Action**:
  - MSI executes `instUSBDriver.exe /S` during installation.
  - Configured with `Execute="deferred"` and `Impersonate="no"` to run under elevated `NT AUTHORITY\SYSTEM` / Administrator context.
  - Test rig operators do not encounter secondary UAC prompts during installation.
- **IT Silent Deployment Flag**:
  - The driver installation is controlled by the property `INSTALL_CAMERA_DRIVER` (default `1`).
  - Automated deployment systems can skip driver installation via:
    ```cmd
    msiexec /i HighSpeedCamera_v1.0.0_x64.msi /qn INSTALL_CAMERA_DRIVER=0
    ```
- **Driver Maintenance Shortcut**:
  - Adds an "Install Camera USB Driver" shortcut to the Start Menu for single-click driver repairs without reinstalling the entire application.

### Shortcuts & Shell Integration
- **Desktop Shortcut**: "High Speed Camera" launching `capture_gui_qt.exe`.
- **Start Menu Shortcuts**:
  - "High Speed Camera" (Main application)
  - "Install Camera USB Driver" (Driver maintenance / repair)
  - "Uninstall High Speed Camera" (`msiexec /x [ProductCode]`)
- **Windows Settings Integration**:
  - Registered in Windows Settings -> Installed Apps / Add or Remove Programs with `app_icon.ico`.
  - Supports clean upgrades (`MajorUpgrade` with `AllowSameVersionUpgrades="yes"`) and complete removal.

---

## 2. GitHub Actions CI Workflow

The workflow at `.github/workflows/build-installer.yml` automates end-to-end compilation, testing, and packaging on `windows-latest`:

1. **Environment Setup**:
   - Visual Studio 2022 MSVC x64 via `ilammy/msvc-dev-cmd@v1`.
   - Qt 6.8 MSVC 64-bit via `jurplel/install-qt-action@v4` (including `qtsvg` module).
   - WiX Toolset v7 via global .NET CLI (`wix eula accept wix7`, `WixToolset.UI.wixext`, `WixToolset.Util.wixext`).
2. **Version Resolution**:
   - Automatically parses git release tags (`v1.0.0` -> `1.0.0`) or manual input via `workflow_dispatch`.
3. **Application Build & Verification**:
   - CMake configuration and MSVC compilation of `capture_gui_qt` and `hsc_tests`.
   - Runs verification test suite (`hsc_tests.exe`) ensuring 100% test pass before packaging.
4. **Packaging**:
   - Runs `windeployqt` for runtime dependencies.
   - Bundles IMV Camera SDK DLLs and camera drivers.
   - Compiles MSI package via WiX.
5. **MSI Inspection & Artifact Upload**:
   - Runs `installer/inspect_msi.ps1` to verify properties, actions, and shortcuts.
   - Publishes `HighSpeedCamera_v<version>_x64.msi` as a GitHub Actions workflow artifact.
   - Attaches MSI to GitHub Releases on tag pushes.

---

## 3. Local Build Instructions

To build the MSI installer locally:

```cmd
# From repository root:
build_msi.bat 1.0.0
```

### Inspection Script
To verify the internal MSI tables, properties, and custom actions:
```powershell
pwsh -ExecutionPolicy Bypass -File installer/inspect_msi.ps1
```
