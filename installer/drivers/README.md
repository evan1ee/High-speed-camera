# High Speed Camera Drivers

This folder holds the device driver installers for cameras supported by the High Speed Camera Rig System.

## Supported Drivers

### 1. USB3 Vision Driver (`instUSBDriver.exe`)
- **Camera Type**: USB3 Vision high-speed industrial cameras (e.g. Huaray / iRayple AH7040MU000 USB3 model).
- **Installer Type**: Nullsoft Scriptable Install System (NSIS).
- **Silent Installation Switch**: `/S`
- **Elevation Requirement**: Administrator privileges (configured in MSI deferred custom action with `Impersonate="no"`).
- **Uninstall Executable**: Installed to `C:\Program Files\MV viewer\MV Viewer\Drivers\USBDriver\uninstUSBDriver.exe` (or camera driver repository).

### 2. CoaXPress (CXP) PCIe Grabber Driver (`instPCIeCXPDriver.exe`)
- **Camera Type**: CoaXPress PCIe frame grabber boards.
- **Installer Type**: Inno Setup.
- **Silent Installation Switch**: `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART`
- **Optional**: Because this installer is ~90MB, it can be dropped into this folder when building for CXP-specific test rigs.

## MSI Integration Architecture

1. **Automatic Elevated Installation**:
   The Windows Installer (`.msi`) includes an embedded deferred custom action that runs `instUSBDriver.exe /S` under the elevated `NT AUTHORITY\SYSTEM` / Administrator context during setup when `INSTALL_CAMERA_DRIVER=1` (the default). Operators do not experience secondary UAC prompts.

2. **Operator Disablement / IT Scripting**:
   If IT administrators want to deploy the application without touching existing drivers:
   ```cmd
   msiexec /i HighSpeedCamera.msi INSTALL_CAMERA_DRIVER=0
   ```

3. **Start Menu Maintenance Hook**:
   The installer creates an "Install Camera USB Driver" shortcut in the Start Menu, allowing operators or lab technicians to repair or re-install the driver with a single click at any time without reinstalling the entire application.
