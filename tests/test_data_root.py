from hsc.app_paths import data_root


def test_data_root_is_data_dir():
    d = data_root()
    assert d.name == "data"
    assert d.is_dir()


def test_moved_configs_still_found():
    d = data_root()
    assert (d / "calibration.json").is_file()
    assert (d / "reference_lines.json").is_file()
