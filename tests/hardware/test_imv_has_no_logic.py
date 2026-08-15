"""The SDK adapter is the one file excluded from coverage, so it must be too
trivial to be wrong. This asserts that: pure delegation, no decisions.

Without it, logic drifts into the untested file and the exclusion stops being
honest -- which is exactly how an untestable frame-rate bug survived into two
rig runs.
"""
import ast
import inspect
from pathlib import Path

import hsc.hardware.imv as imv

FORBIDDEN = (ast.If, ast.For, ast.While, ast.ListComp, ast.DictComp,
             ast.SetComp, ast.GeneratorExp, ast.BinOp, ast.BoolOp, ast.Compare,
             ast.IfExp, ast.Try)


def _tree():
    return ast.parse(Path(inspect.getfile(imv)).read_text(encoding="utf-8"))


def test_adapter_contains_no_branching_or_computation():
    offenders = [type(node).__name__ for node in ast.walk(_tree())
                 if isinstance(node, FORBIDDEN)]
    assert not offenders, (
        f"hsc/hardware/imv.py is excluded from coverage and must hold no "
        f"logic, but contains: {sorted(set(offenders))}. Move it into "
        f"hsc/rig/ where it can be tested.")


def test_adapter_is_the_only_coverage_exclusion():
    config = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'omit = ["hsc/hardware/imv.py"]' in config


def test_adapter_implements_the_protocol():
    from hsc.hardware.device import CameraDevice
    assert isinstance(imv.ImvCamera(), CameraDevice)
