#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Compatibility shim: the GUI now lives in the :mod:`hsc.gui` package.

Kept so ``run_gui.py``, ``python -m hsc.capture_gui``, and any external
scripts importing ``hsc.capture_gui`` keep working unchanged.
"""

from hsc.gui.app import CaptureGui, main
from hsc.gui.selftest import run_selftest as _run_selftest  # noqa: F401 - re-export

__all__ = ["CaptureGui", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
