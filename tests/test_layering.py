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
ANALYSIS = ROOT / "hsc"
FORBIDDEN = {"fastapi", "starlette", "uvicorn", "hsc.api"}
#: The rig layer may not import the API layer either way round.
FORBIDDEN_IN_ANALYSIS = {"hsc.rig", "hsc.api"}
#: The service packages live inside ``hsc/`` but answer to their own rules
#: above, so the analysis sweep below skips them.
SERVICE_PACKAGES = (ROOT / "hsc" / "hardware", RIG, ROOT / "hsc" / "api")


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


RIG_MODULES = sorted(RIG.rglob("*.py"))
ANALYSIS_MODULES = sorted(
    p for p in ANALYSIS.rglob("*.py")
    if not any(pkg in p.parents for pkg in SERVICE_PACKAGES))


def test_the_guard_has_modules_to_guard():
    """An empty glob would make every parametrised case below vanish
    silently, leaving a green guard that guards nothing."""
    assert RIG_MODULES and ANALYSIS_MODULES
    # The sweep is recursive, so an analysis package added under hsc/ later is
    # guarded without touching this file. Only the three service packages are
    # exempt, and only because they answer to the rule above instead.
    # (hsc/gui/ used to be the proof that recursion works; it was deleted with
    # the Tk app, leaving every analysis module at the top level today.)
    assert not any(pkg in p.parents
                   for p in ANALYSIS_MODULES for pkg in SERVICE_PACKAGES)
    assert {p.name for p in ANALYSIS_MODULES} >= {
        "measure_angle.py", "piston_track.py", "measure_piston.py"}


@pytest.mark.parametrize("path", RIG_MODULES, ids=_module_id)
def test_rig_layer_imports_no_web_framework(path):
    found = violations(imported_names(path), FORBIDDEN)
    assert not found, (
        f"{path} imports {sorted(found)}; hsc/rig must run without a server")


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
