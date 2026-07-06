"""Ensure the repo root (holding the hsc/ package) is importable under bare ``pytest``."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
