"""resource_root() must expose the SDK wrapper, Runtime DLLs and helper exe."""
from hsc.app_paths import resource_root


def test_vendor_layout():
    root = resource_root()
    assert root.name == "vendor"
    assert (root / "Runtime" / "x64" / "MVSDKmd.dll").is_file()
    assert (root / "Development" / "Samples" / "Python" / "IMV" / "MVSDK" / "IMVApi.py").is_file()


def test_scanner_exe_where_injection_extract_looks():
    from hsc import injection_extract

    assert injection_extract.CPP_EXE.is_file()
