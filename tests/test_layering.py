#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""The rig layer must stay testable without a server, and the dependencies
must point one way. Both are load-bearing for the coverage claim.

Structural, not textual: every module is parsed with ``ast`` and its import
statements are read, so a reformat, a line continuation or an import moved
inside a function cannot slip past the guard.

Matching is by PREFIX, not equality. ``from hsc.api.app import create_app``
names the module ``hsc.api.app``, which is not equal to the forbidden
``hsc.api`` -- an equality test lets the most natural form of the import
straight through, which is the hole this guard exists to close.
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RIG = ROOT / "hsc" / "rig"
HARDWARE = ROOT / "hsc" / "hardware"
API = ROOT / "hsc" / "api"
ANALYSIS = ROOT / "hsc"
FORBIDDEN = {"fastapi", "starlette", "uvicorn", "hsc.api"}
#: The rig layer may not import the API layer either way round.
FORBIDDEN_IN_ANALYSIS = {"hsc.rig", "hsc.api"}
#: The service packages live inside ``hsc/`` but answer to their own rules
#: above, so the analysis sweep below skips them.
SERVICE_PACKAGES = (HARDWARE, RIG, API)
#: Must run without a server. ``hsc/hardware/`` belongs here as much as the rig
#: does: it is the camera seam every rig test stands on, it is exempt from the
#: analysis sweep because it is a service package, and until this was added it
#: was covered by NEITHER rule -- it could have imported fastapi with nothing
#: noticing.
NO_WEB_PACKAGES = (RIG, HARDWARE)


def imported_names(path):
    """Every module named by an import in *path*, plus its top-level package.

    ``import a.b`` and ``from a.b import c`` both contribute ``a`` and ``a.b``.
    Deeper names are kept whole (``a.b.c``) and matched by prefix in
    ``violations``.
    """
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.add(node.module.split(".")[0])
    return names


def violations(names, forbidden):
    """The forbidden entries *names* reaches, as a package or below it."""
    return {f for f in forbidden for n in names
            if n == f or n.startswith(f + ".")}


def _module_id(path):
    return path.relative_to(ROOT).as_posix()


def sweep(root, exempt=()):
    """Every ``.py`` under *root*, RECURSIVELY, skipping the *exempt* packages.

    Recursive on purpose: an analysis package added under ``hsc/`` later must
    be guarded without anyone remembering to edit this file. ``rglob``, not
    ``glob`` -- and ``test_the_sweep_is_recursive`` is what holds it to that,
    because every module in ``hsc/`` happens to sit at the top level today
    (``hsc/gui/`` used to be the living proof, and went with the Tk app).
    """
    return sorted(p for p in root.rglob("*.py")
                  if not any(pkg in p.parents for pkg in exempt))


NO_WEB_MODULES = sorted(m for pkg in NO_WEB_PACKAGES for m in sweep(pkg))
ANALYSIS_MODULES = sweep(ANALYSIS, SERVICE_PACKAGES)

#: Exactly what the analysis sweep must find. An open-ended ``>=`` here was a
#: restatement of the comprehension that builds the list, so it could not fail;
#: this can. Adding an analysis module means adding its name here -- one
#: deliberate line, in exchange for a guard that notices when a module silently
#: leaves the sweep (or when a service package silently joins it).
EXPECTED_ANALYSIS = {
    "__init__.py", "app_paths.py", "calibrate_scale.py", "capture_image.py",
    "frame_writer.py", "injection_extract.py", "make_video.py",
    "measure_angle.py", "measure_block.py", "measure_piston.py", "monitor.py",
    "piston_plot.py", "piston_track.py", "reference_lines.py",
    "smart_save.py", "summary.py",
}


def test_the_guard_has_modules_to_guard():
    """An empty glob would make every parametrised case below vanish
    silently, leaving a green guard that guards nothing."""
    assert {p.name for p in ANALYSIS_MODULES} == EXPECTED_ANALYSIS
    assert len(ANALYSIS_MODULES) == len(EXPECTED_ANALYSIS)


def test_the_hardware_seam_is_guarded_too():
    """It was in neither rule: exempt from the analysis sweep because it is a
    service package, and absent from the no-web-framework rule."""
    hardware = sweep(HARDWARE)
    assert {p.name for p in hardware} == {
        "__init__.py", "device.py", "fake.py", "imv.py"}
    assert set(hardware) <= set(NO_WEB_MODULES)
    assert set(sweep(RIG)) <= set(NO_WEB_MODULES)


def test_the_sweep_is_recursive(tmp_path):
    """The property the real sweep cannot demonstrate on itself today: every
    module under hsc/ is at the top level, so swapping rglob for glob would
    still pass every other test in this file."""
    (tmp_path / "pkg" / "deep").mkdir(parents=True)
    (tmp_path / "service" / "inner").mkdir(parents=True)
    for relative in ("top.py", "pkg/nested.py", "pkg/deep/deeper.py",
                     "service/exempt.py", "service/inner/exempt.py"):
        (tmp_path / relative).write_text("", encoding="utf-8")

    found = sweep(tmp_path, exempt=(tmp_path / "service",))

    assert {p.name for p in found} == {"top.py", "nested.py", "deeper.py"}


@pytest.mark.parametrize("path", NO_WEB_MODULES, ids=_module_id)
def test_the_rig_and_hardware_layers_import_no_web_framework(path):
    found = violations(imported_names(path), FORBIDDEN)
    assert not found, (
        f"{path} imports {sorted(found)}; hsc/rig and hsc/hardware must run "
        f"without a server")


@pytest.mark.parametrize("path", ANALYSIS_MODULES, ids=_module_id)
def test_hsc_analysis_modules_do_not_import_the_rig_layer(path):
    """Dependencies point one way: rig -> analysis, never back."""
    found = violations(imported_names(path), FORBIDDEN_IN_ANALYSIS)
    assert not found, (
        f"{path} imports {sorted(found)}; the analysis modules must not "
        f"depend on the service layers above them")


# -- the guard's own regression tests ------------------------------------
# Submodule imports are the form these violations actually take; an equality
# match let all three dotted names through, so each is pinned here.

@pytest.mark.parametrize("source, forbidden, expected", [
    ("from hsc.api.app import create_app", FORBIDDEN, {"hsc.api"}),
    ("from hsc.rig.store import RunStore", FORBIDDEN_IN_ANALYSIS, {"hsc.rig"}),
    ("from hsc.api.errors import Boom", FORBIDDEN_IN_ANALYSIS, {"hsc.api"}),
    ("import hsc.api.app", FORBIDDEN, {"hsc.api"}),
    ("import hsc.rig.jobs as jobs", FORBIDDEN_IN_ANALYSIS, {"hsc.rig"}),
    ("from starlette.responses import JSONResponse", FORBIDDEN,
     {"starlette"}),
    ("def f():\n    import uvicorn\n", FORBIDDEN, {"uvicorn"}),
], ids=lambda v: v if isinstance(v, str) else "")
def test_a_submodule_import_is_caught(tmp_path, source, forbidden, expected):
    module = tmp_path / "probe.py"
    module.write_text(source + "\n", encoding="utf-8")
    assert violations(imported_names(module), forbidden) == expected


@pytest.mark.parametrize("source", [
    "from hsc import measure_piston",
    "from hsc.app_paths import data_root",
    "import hsc.apiary",              # a prefix match must respect the dot
    "from hsc.rigging import thing",
])
def test_an_innocent_import_is_not_caught(tmp_path, source):
    module = tmp_path / "probe.py"
    module.write_text(source + "\n", encoding="utf-8")
    assert not violations(imported_names(module),
                          FORBIDDEN | FORBIDDEN_IN_ANALYSIS)
