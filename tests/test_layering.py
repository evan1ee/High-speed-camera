#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""The rig layer must stay testable without a server, and the dependencies
must point one way. Both are load-bearing for the coverage claim.

Structural, not textual: every module is parsed with ``ast`` and its import
statements are read, so a reformat, a line continuation or an import moved
inside a function cannot slip past the guard.
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


def imported_names(path):
    """Every module named by an import in *path*, plus its top-level package.

    ``import a.b`` and ``from a.b import c`` both contribute ``a`` and ``a.b``,
    so a forbidden name matches whether it is the package or the module.
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


RIG_MODULES = sorted(RIG.rglob("*.py"))
ANALYSIS_MODULES = sorted(ANALYSIS.glob("*.py"))


def test_the_guard_has_modules_to_guard():
    """An empty glob would make every parametrised case below vanish
    silently, leaving a green guard that guards nothing."""
    assert RIG_MODULES and ANALYSIS_MODULES


@pytest.mark.parametrize("path", RIG_MODULES, ids=lambda p: p.name)
def test_rig_layer_imports_no_web_framework(path):
    found = imported_names(path) & FORBIDDEN
    assert not found, (
        f"{path} imports {sorted(found)}; hsc/rig must run without a server")


@pytest.mark.parametrize("path", ANALYSIS_MODULES, ids=lambda p: p.name)
def test_hsc_analysis_modules_do_not_import_the_rig_layer(path):
    """Dependencies point one way: rig -> analysis, never back."""
    found = imported_names(path) & FORBIDDEN_IN_ANALYSIS
    assert not found, (
        f"{path} imports {sorted(found)}; the analysis modules must not "
        f"depend on the service layers above them")
