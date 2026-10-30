import pytest

from hsc.app_paths import data_root, settings_path


def test_data_root_is_data_dir():
    d = data_root()
    assert d.name == "data"
    assert d.is_dir()


def test_settings_path_in_root_settings_dir():
    p = settings_path("calibration.json")
    # <root>/settings, next to data/ (not inside it).
    assert p.parent == data_root().parent / "settings"


def test_moved_configs_still_found():
    d = data_root().parent / "settings"
    if not (d / "calibration.json").is_file():
        pytest.skip("no rig data on this machine (data/ is gitignored)")
    assert (d / "calibration.json").is_file()
    assert (d / "reference_lines.json").is_file()
