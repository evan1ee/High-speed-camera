#!/usr/bin/env python
"""Launcher for the High Speed Camera GUI (also the PyInstaller entry point).

Usage:  python run_gui.py                       -- open the GUI
        python run_gui.py --selftest <folder>   -- headless measure+video check
"""
from hsc.capture_gui import main

if __name__ == "__main__":
    raise SystemExit(main())
