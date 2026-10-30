param(
    [string]$MsiPath = "$PSScriptRoot\dist\HighSpeedCamera_v1.0.0_x64.msi",
    [string]$ExpectedVersion = ""
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $MsiPath)) {
    Write-Error "MSI file not found: $MsiPath"
    exit 1
}

$msiFile = Resolve-Path $MsiPath
$fileInfo = Get-Item $msiFile.Path
Write-Host "=========================================================="
Write-Host "Inspecting MSI: $($msiFile.Path)"
Write-Host ("File Size:      {0:N0} bytes [{1:N2} MB]" -f $fileInfo.Length, ($fileInfo.Length / 1MB))
Write-Host "=========================================================="

if ($fileInfo.Length -lt 1000000) {
    Write-Error "MSI file is abnormally small ($($fileInfo.Length) bytes), likely missing payload!"
    exit 1
}

$com = New-Object -ComObject WindowsInstaller.Installer
$db = $com.GetType().InvokeMember("OpenDatabase", [System.Reflection.BindingFlags]::InvokeMethod, $null, $com, @($msiFile.Path, 0))

function Query-Msi($sql) {
    $view = $db.GetType().InvokeMember("OpenView", [System.Reflection.BindingFlags]::InvokeMethod, $null, $db, @($sql))
    $view.GetType().InvokeMember("Execute", [System.Reflection.BindingFlags]::InvokeMethod, $null, $view, $null)
    $results = @()
    while ($true) {
        $rec = $view.GetType().InvokeMember("Fetch", [System.Reflection.BindingFlags]::InvokeMethod, $null, $view, $null)
        if ($null -eq $rec) { break }
        $recType = $rec.GetType()
        $fc = [int]($recType.InvokeMember("FieldCount", [System.Reflection.BindingFlags]::GetProperty, $null, $rec, $null))
        $row = @{}
        for ($i = 1; $i -le $fc; $i++) {
            $row["Field$i"] = [string]($recType.InvokeMember("StringData", [System.Reflection.BindingFlags]::GetProperty, $null, $rec, @([int]$i)))
        }
        $results += [PSCustomObject]$row
    }
    $view.GetType().InvokeMember("Close", [System.Reflection.BindingFlags]::InvokeMethod, $null, $view, $null)
    return $results
}

$failCount = 0

function Assert-Msi($name, $condition, $detail) {
    if ($condition) {
        Write-Host "  [PASS] $name ($detail)" -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] $name ($detail)" -ForegroundColor Red
        $script:failCount++
    }
}

Write-Host "`n--- 1. VERIFYING PROPERTIES ---"
$props = @{}
Query-Msi "SELECT Property, Value FROM Property" | Where-Object { -not [string]::IsNullOrWhiteSpace($_.Field1) } | ForEach-Object {
    $props[$_.Field1] = $_.Field2
    if ($_.Field1 -match 'Product|INSTALL|ARP|UpgradeCode') {
        Write-Host ("    {0,-28} = {1}" -f $_.Field1, $_.Field2)
    }
}

Assert-Msi "ProductName" ($props["ProductName"] -eq "High Speed Camera") "Value: '$($props['ProductName'])'"
Assert-Msi "UpgradeCode" ($props["UpgradeCode"] -eq "{648B1C63-024F-4C21-BD33-EE3E92B9229A}") "Value: '$($props['UpgradeCode'])'"
Assert-Msi "INSTALL_CAMERA_DRIVER" ($props["INSTALL_CAMERA_DRIVER"] -eq "1") "Value: '$($props['INSTALL_CAMERA_DRIVER'])'"
if ($ExpectedVersion) {
    Assert-Msi "ProductVersion Match" ($props["ProductVersion"] -eq $ExpectedVersion) "Expected: '$ExpectedVersion', Actual: '$($props['ProductVersion'])'"
} else {
    Assert-Msi "ProductVersion Present" (-not [string]::IsNullOrWhiteSpace($props["ProductVersion"])) "Value: '$($props['ProductVersion'])'"
}

Write-Host "`n--- 2. VERIFYING CUSTOM ACTIONS ---"
$cas = @{}
Query-Msi "SELECT Action, Target FROM CustomAction" | Where-Object { -not [string]::IsNullOrWhiteSpace($_.Field1) } | ForEach-Object {
    $cas[$_.Field1] = $_.Field2
    Write-Host ("    Action: {0,-32} | Target: {1}" -f $_.Field1, $_.Field2)
}

Assert-Msi "SetINSTALLFOLDER Target" ($cas["SetINSTALLFOLDER"] -eq "[WindowsVolume]HighSpeedCamera") "Target: '$($cas['SetINSTALLFOLDER'])'"
Assert-Msi "InstallCameraDriverAction Target" ($cas["InstallCameraDriverAction"] -eq '"[INSTALLFOLDER]drivers\instUSBDriver.exe" /S') "Target: '$($cas['InstallCameraDriverAction'])'"
Assert-Msi "Permissions Extension CA" ($cas.ContainsKey("Wix4ExecSecureObjects_X64")) "Wix4ExecSecureObjects_X64 present"

Write-Host "`n--- 3. VERIFYING SHORTCUTS ---"
$shortcuts = @{}
Query-Msi "SELECT Shortcut, Target, Name FROM Shortcut" | Where-Object { -not [string]::IsNullOrWhiteSpace($_.Field1) } | ForEach-Object {
    $shortcuts[$_.Field1] = $_.Field2
    Write-Host ("    Shortcut: {0,-26} | Target: {1}" -f $_.Field1, $_.Field2)
}

Assert-Msi "AppStartMenuShortcut" ($shortcuts["AppStartMenuShortcut"] -eq "[INSTALLFOLDER]capture_gui_qt.exe") "Target: '$($shortcuts['AppStartMenuShortcut'])'"
Assert-Msi "DriverStartMenuShortcut" ($shortcuts["DriverStartMenuShortcut"] -eq "[INSTALLFOLDER]drivers\instUSBDriver.exe") "Target: '$($shortcuts['DriverStartMenuShortcut'])'"
Assert-Msi "AppDesktopShortcut" ($shortcuts["AppDesktopShortcut"] -eq "[INSTALLFOLDER]capture_gui_qt.exe") "Target: '$($shortcuts['AppDesktopShortcut'])'"

Write-Host "`n--- 4. VERIFYING DIRECTORY STRUCTURE ---"
$dirs = @{}
Query-Msi "SELECT Directory, Directory_Parent, DefaultDir FROM Directory" | Where-Object { -not [string]::IsNullOrWhiteSpace($_.Field1) } | ForEach-Object {
    $dirs[$_.Field1] = $_.Field2
}

Assert-Msi "INSTALLFOLDER" ($dirs.ContainsKey("INSTALLFOLDER")) "Directory table contains INSTALLFOLDER"
Assert-Msi "DriversFolder" ($dirs.ContainsKey("DriversFolder") -or ($dirs.Values -contains "INSTALLFOLDER")) "Drivers folder present"
Assert-Msi "DataFolder" ($dirs.ContainsKey("DataFolder")) "User-writable data folder present"
Assert-Msi "SettingsFolder" ($dirs.ContainsKey("SettingsFolder")) "User-writable settings folder present"

Write-Host "`n=========================================================="
if ($failCount -gt 0) {
    Write-Error "MSI Verification FAILED with $failCount error(s)!"
    exit 1
} else {
    Write-Host "[OK] All MSI verification checks passed successfully!" -ForegroundColor Green
    Write-Host "=========================================================="
    exit 0
}
