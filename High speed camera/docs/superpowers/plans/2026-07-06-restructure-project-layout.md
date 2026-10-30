# Project Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize the flat, cluttered repo root (13 Python modules + vendor SDK + user data + build artifacts all mixed together) into a clean layout — `hsc/` package, `vendor/`, `native/`, `packaging/`, `docs/`, `data/` — **without changing any behavior**.

**Architecture:** This is a *move-and-rewire* restructure, not a rewrite. Every module keeps its name and content; only locations and import/path plumbing change. Characterization tests are written FIRST against the current layout and must stay green through every task. The package lives at repo root (`hsc/`, not `src/`) so modules run via `python -m hsc.<name>` with zero install steps.

**Tech Stack:** Python 3.13, pytest, OpenCV/NumPy/SciPy/scikit-learn/Pillow (already installed), PyInstaller, MinGW g++ (optional, for the C++ scanner), git on Windows (Git Bash for commands below).

## Current → Target layout

```
CURRENT (root soup)                      TARGET
├── app_paths.py … reference_ui.py  →   ├── hsc/                  (package: same 12 modules + __init__.py)
├── injection_scan.cpp / .exe        →   ├── native/injection_scan.cpp + build_injection_scan.bat
│   build_injection_scan.bat             ├── vendor/
├── Development/  (1384 files!)      →   │   ├── Development/Samples/Python/IMV/MVSDK/   (wrapper only)
├── Runtime/                         →   │   ├── Runtime/{x64,Win32,CLProtocol}
│                                        │   └── bin/injection_scan.exe
├── HighSpeedCamera.spec             →   ├── packaging/HighSpeedCamera.spec + build_exe.bat
│   build_exe.bat                        ├── run_gui.py            (NEW: entry point)
├── *.pdf, Documentations/           →   ├── docs/                 (all manuals + Documentations/ + this plan)
├── captures/, injection images/,    →   ├── data/                 (gitignored; all runtime output + JSON configs)
│   measure/, reference line/,           ├── tests/                (NEW: characterization tests)
│   calibration.json,                    ├── pyproject.toml        (NEW)
│   reference_lines.json                 ├── README.md, CLAUDE.md, DISTRIBUTION.md, .gitignore
├── C version/  (492 MB)             →   moved OUT of repo → ../C version/
└── build/, dist/, __pycache__/      →   deleted (regenerable, already gitignored)
```

Unneeded vendor SDK samples (everything in `Development/` except the `MVSDK` wrapper) move OUT of the repo to `../sdk-archive/Development/`.

## Global Constraints

- **Windows-only project.** Use `python` (3.13). Git Bash syntax shown for shell steps; paths contain spaces — always quote.
- **No behavior changes.** Do not touch any tuned constant (`EDGE_*`, `RANSAC_*`, `QUALITY_*`, `NOZZLE_SIDE`, `MEASURE_START/END`, `VIDEO_FPS`, padding values) or any algorithm.
- **Do not rename modules.** `measure_angle.py` stays `measure_angle.py`, just inside `hsc/`.
- **Preserve GUI contracts:** `measure_folder(source, dest_base, start, end, progress)`, `injection_extract.detect_bounds_with_presence(...)`, `injection_extract.build_result(...)` signatures unchanged.
- **Never delete user data.** `captures/`, `injection images/`, `measure/`, `reference line/`, `calibration.json`, `reference_lines.json`, `C version/` are MOVED, never deleted.
- **Vendor layout invariant:** the vendor `IMVApi.py` resolves `MVSDKmd.dll` via the relative path `../../../../../Runtime/x64/MVSDKmd.dll` from the MVSDK folder — `Development/` and `Runtime/` must remain siblings under one root (that root becomes `vendor/`).
- **Use `git mv` for tracked files** so history follows; plain `mv` only for untracked/gitignored items.
- **No `pip install` of anything** (all deps already present; the project itself is never installed — flat package layout needs no install).
- Commit after every task, conventional-commits format (`refactor: …`, `test: …`, `build: …`, `docs: …`).
- All test/run commands are executed from the repo root: `D:\01_Data\code\spray-angle-test\High speed camera`.

---

### Task 1: Safety net — branch, pyproject, characterization tests

Write tests against the CURRENT flat layout so every later move is verified against them. No production code changes in this task.

**Files:**
- Create: `pyproject.toml`
- Create: `tests/test_imports.py`
- Create: `tests/test_measure_synthetic.py`
- Create: `tests/test_calibration.py`

**Interfaces:**
- Consumes: current flat modules importable from repo root (`import measure_angle` etc.), existing `calibration.json` at repo root.
- Produces: a pytest suite later tasks must keep green. Task 2 will rewrite these tests' imports to `from hsc import …`.

- [ ] **Step 1: Create a working branch**

```bash
cd "/d/01_Data/code/spray-angle-test/High speed camera"
git checkout -b restructure
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "hsc"
version = "1.0.0"
description = "High-speed camera spray-angle toolkit for a needle-free injector test rig"
requires-python = ">=3.11"
# Documented for reference; already installed on the rig machine. Do NOT pip install.
dependencies = [
    "numpy",
    "opencv-python",
    "scipy",
    "scikit-learn",
    "pillow",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 3: Write the import smoke test** (`tests/test_imports.py`)

```python
"""Every module must import without a camera attached (SDK loads lazily)."""
import importlib

import pytest

MODULES = [
    "app_paths",
    "calibrate_scale",
    "calibrate_ui",
    "capture_gui",
    "capture_image",
    "injection_extract",
    "make_video",
    "measure_angle",
    "measure_block",
    "reference_lines",
    "reference_ui",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    assert importlib.import_module(name) is not None
```

- [ ] **Step 4: Write the synthetic-jet characterization test** (`tests/test_measure_synthetic.py`)

```python
"""Characterization test: the measurement pipeline must survive the restructure.

A synthetic bright wedge (nozzle on the RIGHT, per NOZZLE_SIDE) with a 10-degree
full opening angle must measure to a sane angle. Tolerance is deliberately wide;
this guards against import/path breakage, not measurement accuracy.
"""
import cv2
import numpy as np


def make_wedge(width=320, height=240, half_angle_deg=5.0):
    img = np.full((height, width), 15, np.uint8)
    apex = (300, 120)
    length = 280
    half = np.tan(np.radians(half_angle_deg)) * length
    pts = np.array(
        [apex,
         (apex[0] - length, int(round(120 - half))),
         (apex[0] - length, int(round(120 + half)))],
        np.int32,
    )
    cv2.fillConvexPoly(img, pts, 230)
    return cv2.GaussianBlur(img, (5, 5), 0)


def test_measure_frame_synthetic_wedge():
    import measure_angle

    result = measure_angle.measure_frame(make_wedge())
    assert result is not None
    assert 3.0 <= result["angle"] <= 18.0
```

- [ ] **Step 5: Write the calibration-load test** (`tests/test_calibration.py`)

```python
"""The stored rig calibration must remain loadable after every move."""


def test_load_calibration_found():
    import calibrate_scale

    cal = calibrate_scale.load_calibration()
    assert cal is not None
    assert cal["mm_per_px"] > 0
```

- [ ] **Step 6: Run the suite — it must PASS against the current layout**

Run: `python -m pytest -v`
Expected: all tests PASS. If `test_measure_frame_synthetic_wedge` fails, adjust the *synthetic image* (brightness/size/apex) until the current pipeline measures it — do NOT touch `measure_angle.py`. If `result` uses a different key than `"angle"`, inspect the dict returned by `measure_frame` and use the actual key. These tests characterize current behavior; current behavior is by definition correct.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml tests/
git commit -m "test: add characterization suite before restructure"
```

---

### Task 2: Move Python modules into the `hsc/` package

**Files:**
- Create: `hsc/__init__.py`, `run_gui.py`
- Move (git mv): `app_paths.py`, `calibrate_scale.py`, `calibrate_ui.py`, `capture_gui.py`, `capture_image.py`, `injection_extract.py`, `make_video.py`, `measure_angle.py`, `measure_block.py`, `reference_lines.py`, `reference_ui.py` → `hsc/`
- Modify: every moved module's cross-imports; `hsc/app_paths.py`; `hsc/capture_gui.py` (`main()` refactor); all three test files.

**Interfaces:**
- Consumes: flat modules from Task 1.
- Produces: package `hsc` importable from repo root; `hsc.capture_gui.main(argv=None) -> int` (used by `run_gui.py` and Task 6's PyInstaller spec); `hsc.app_paths.resource_root()` / `data_root()` still returning the **repo root** (vendor/data splits come in Tasks 3–4).

- [ ] **Step 1: Move the modules**

```bash
mkdir hsc
git mv app_paths.py calibrate_scale.py calibrate_ui.py capture_gui.py \
       capture_image.py injection_extract.py make_video.py measure_angle.py \
       measure_block.py reference_lines.py reference_ui.py hsc/
```

Create `hsc/__init__.py`:

```python
"""High-speed camera spray-angle toolkit (capture -> find injection -> measure)."""
```

- [ ] **Step 2: Rewrite cross-module imports to package-absolute**

Exact replacements (each `old` line appears verbatim at the top of the named file):

| File | Old | New |
|---|---|---|
| `hsc/capture_gui.py` | `import calibrate_scale` | `from hsc import calibrate_scale` |
| `hsc/capture_gui.py` | `import calibrate_ui` | `from hsc import calibrate_ui` |
| `hsc/capture_gui.py` | `import capture_image` | `from hsc import capture_image` |
| `hsc/capture_gui.py` | `import injection_extract` | `from hsc import injection_extract` |
| `hsc/capture_gui.py` | `import make_video` | `from hsc import make_video` |
| `hsc/capture_gui.py` | `import measure_angle` | `from hsc import measure_angle` |
| `hsc/capture_gui.py` | `import measure_block` | `from hsc import measure_block` |
| `hsc/capture_gui.py` | `import reference_lines` | `from hsc import reference_lines` |
| `hsc/capture_gui.py` | `import reference_ui` | `from hsc import reference_ui` |
| `hsc/capture_gui.py` | `from app_paths import data_root` | `from hsc.app_paths import data_root` |
| `hsc/capture_image.py` | `from app_paths import resource_root` | `from hsc.app_paths import resource_root` |
| `hsc/injection_extract.py` | `from app_paths import resource_root` | `from hsc.app_paths import resource_root` |
| `hsc/make_video.py` | `import injection_extract` | `from hsc import injection_extract` |
| `hsc/measure_angle.py` | `import injection_extract` | `from hsc import injection_extract` |
| `hsc/measure_angle.py` | `import reference_lines` | `from hsc import reference_lines` |
| `hsc/measure_block.py` | `import injection_extract` | `from hsc import injection_extract` |
| `hsc/measure_block.py` | `import measure_angle as ma` | `from hsc import measure_angle as ma` |
| `hsc/calibrate_scale.py` | `import measure_angle as ma` | `from hsc import measure_angle as ma` |
| `hsc/calibrate_scale.py` | `from app_paths import data_root` | `from hsc.app_paths import data_root` |
| `hsc/calibrate_ui.py` | `import calibrate_scale` | `from hsc import calibrate_scale` |
| `hsc/calibrate_ui.py` | `import measure_angle as ma` | `from hsc import measure_angle as ma` |
| `hsc/reference_lines.py` | `import injection_extract` | `from hsc import injection_extract` |
| `hsc/reference_lines.py` | `from app_paths import data_root` | `from hsc.app_paths import data_root` |
| `hsc/reference_ui.py` | `import calibrate_scale` | `from hsc import calibrate_scale` |
| `hsc/reference_ui.py` | `import reference_lines as rl` | `from hsc import reference_lines as rl` |

After editing, verify nothing was missed:

```bash
grep -nE "^(import|from) (app_paths|capture_image|capture_gui|injection_extract|measure_angle|measure_block|make_video|calibrate_scale|calibrate_ui|reference_lines|reference_ui)\b" hsc/*.py
```

Expected: no output.

- [ ] **Step 3: Point `app_paths` roots back at the repo root**

`app_paths.py` used `Path(__file__).resolve().parent` (= repo root when the file was flat). Now the file sits one level down, so in `hsc/app_paths.py` change **both** functions' source-mode return:

```python
def resource_root() -> Path:
    """Base folder for bundled read-only resources (SDK, Runtime DLLs, helper exe)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parents[1]


def data_root() -> Path:
    """Base folder for user output written at runtime (next to the .exe when frozen)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]
```

(`parents[1]` = repo root, because the file is now at `<root>/hsc/app_paths.py`. Semantics identical to before the move.)

- [ ] **Step 4: Extract `main()` in `hsc/capture_gui.py` and add `run_gui.py`**

Replace the current `__main__` block at the bottom of `capture_gui.py`:

```python
if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        sys.exit(_run_selftest(sys.argv[2]))

    app = CaptureGui()
    app.mainloop()
```

with:

```python
def main(argv=None):
    """GUI entry point; ``--selftest <injection folder>`` runs headless."""
    import sys

    argv = sys.argv[1:] if argv is None else argv
    if len(argv) >= 2 and argv[0] == "--selftest":
        return _run_selftest(argv[1])

    app = CaptureGui()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Create `run_gui.py` at repo root:

```python
#!/usr/bin/env python
"""Launcher for the High Speed Camera GUI (also the PyInstaller entry point).

Usage:  python run_gui.py                       -- open the GUI
        python run_gui.py --selftest <folder>   -- headless measure+video check
"""
from hsc.capture_gui import main

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Update the tests to package imports**

- `tests/test_imports.py`: replace the `MODULES` list entries with `"hsc.app_paths"`, `"hsc.calibrate_scale"`, `"hsc.calibrate_ui"`, `"hsc.capture_gui"`, `"hsc.capture_image"`, `"hsc.injection_extract"`, `"hsc.make_video"`, `"hsc.measure_angle"`, `"hsc.measure_block"`, `"hsc.reference_lines"`, `"hsc.reference_ui"`.
- `tests/test_measure_synthetic.py`: `import measure_angle` → `from hsc import measure_angle`.
- `tests/test_calibration.py`: `import calibrate_scale` → `from hsc import calibrate_scale`.

- [ ] **Step 6: Run the suite**

Run: `python -m pytest -v`
Expected: all PASS.

- [ ] **Step 7: Sanity-check the CLI paths**

```bash
python -c "import run_gui" 2>/dev/null; python -m py_compile run_gui.py hsc/*.py && echo COMPILE-OK
python -m hsc.measure_angle --help >/dev/null 2>&1; echo "measure_angle CLI exit: $?"
```

Expected: `COMPILE-OK`. The CLI probe must not raise `ImportError` (a nonzero argparse exit like 1/2 is fine — only import failures matter here; if the module has no `--help`, run it with no args instead and check the error is about arguments, not imports).

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: move Python modules into hsc/ package with run_gui.py entry point"
```

---

### Task 3: Isolate the vendor SDK under `vendor/`, native scanner under `native/`

**Files:**
- Move: `Development/Samples/Python/IMV/MVSDK/` → `vendor/Development/Samples/Python/IMV/MVSDK/`; `Runtime/` → `vendor/Runtime/`; `injection_scan.exe` → `vendor/bin/injection_scan.exe`; `injection_scan.cpp`, `build_injection_scan.bat` → `native/`
- Move OUT of repo: remaining `Development/` → `../sdk-archive/Development/`
- Modify: `hsc/app_paths.py` (resource_root → vendor), `hsc/injection_extract.py` (exe path), `native/build_injection_scan.bat` (paths)
- Test: `tests/test_vendor_layout.py`

**Interfaces:**
- Consumes: `hsc.app_paths.resource_root()` from Task 2.
- Produces: `resource_root()` now returns the folder **containing** `Development/`, `Runtime/`, `bin/` (source mode: `<root>/vendor`; frozen: `<_MEIPASS>/vendor` — Task 6's spec bundles with the matching `vendor/` prefix). `hsc/capture_image.py` needs **no edit**: its `SDK_DIR = ROOT / "Development" / ...` and `RUNTIME_DIR = ROOT / "Runtime" / ...` compose correctly on top of the new root.

- [ ] **Step 1: Check how the vendor wrapper resolves the DLL (safety check)**

```bash
grep -n "MVSDKmd" "Development/Samples/Python/IMV/MVSDK/IMVApi.py" | head
```

Expected: a load via a path relative to the wrapper file (or a bare name resolved through `os.add_dll_directory`). Whatever the form, keeping `Development/` and `Runtime/` as siblings under `vendor/` preserves it. **If** the path is built from `os.getcwd()` instead of `__file__`, stop and report before proceeding.

- [ ] **Step 2: Move vendor pieces (tracked → `git mv`)**

```bash
mkdir -p vendor/Development/Samples/Python/IMV vendor/bin native
git mv "Development/Samples/Python/IMV/MVSDK" "vendor/Development/Samples/Python/IMV/MVSDK"
git mv Runtime vendor/Runtime
git mv injection_scan.exe vendor/bin/injection_scan.exe
git mv injection_scan.cpp native/injection_scan.cpp
git mv build_injection_scan.bat native/build_injection_scan.bat
```

- [ ] **Step 3: Archive the unused SDK samples outside the repo**

```bash
mkdir -p "../sdk-archive"
mv Development "../sdk-archive/Development"
git add -A   # stages the deletion of the ~1300 leftover tracked sample files
```

- [ ] **Step 4: Point `resource_root()` at `vendor/`**

In `hsc/app_paths.py` replace `resource_root` with:

```python
def resource_root() -> Path:
    """Folder containing the bundled read-only resources: ``Development/`` (SDK
    wrapper), ``Runtime/`` (DLLs) and ``bin/`` (helper exe). ``<root>/vendor``
    from source; ``<_MEIPASS>/vendor`` when frozen (the spec bundles with a
    matching ``vendor/`` prefix)."""
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    else:
        base = Path(__file__).resolve().parents[1]
    return base / "vendor"
```

Also update the module docstring's description of `resource_root` accordingly.

- [ ] **Step 5: Point `injection_extract` at `vendor/bin`**

In `hsc/injection_extract.py` change:

```python
CPP_EXE = HERE / ("injection_scan.exe" if os.name == "nt" else "injection_scan")
```

to:

```python
CPP_EXE = HERE / "bin" / ("injection_scan.exe" if os.name == "nt" else "injection_scan")
```

- [ ] **Step 6: Fix the scanner build script paths** (`native/build_injection_scan.bat`)

```bat
@echo off
REM Build the fast injection motion-signal scanner.
REM Requires MinGW g++ on PATH (g++ --version). Static-linked so it runs
REM without extra MinGW DLLs. Python falls back to NumPy/PIL if this is absent.

cd /d "%~dp0.."
if not exist vendor\bin mkdir vendor\bin

g++ -O3 -fopenmp -std=c++17 -static -static-libgcc -static-libstdc++ ^
    native\injection_scan.cpp -o vendor\bin\injection_scan.exe

if %ERRORLEVEL%==0 (
    echo Built vendor\bin\injection_scan.exe
) else (
    echo Build failed - Python will use its NumPy/PIL fallback instead.
)
```

- [ ] **Step 7: Write the failing vendor-layout test** (`tests/test_vendor_layout.py`)

```python
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
```

(If the wrapper's API file is not named exactly `IMVApi.py`, list `vendor/Development/Samples/Python/IMV/MVSDK/` and assert on the actual filename.)

- [ ] **Step 8: Run the full suite**

Run: `python -m pytest -v`
Expected: all PASS, including the new vendor tests and the Task 1 characterization tests.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "refactor: isolate vendor SDK under vendor/, native scanner under native/"
```

---

### Task 4: Move runtime data into `data/` (gitignored)

**Files:**
- Move: `captures/`, `injection images/`, `measure/`, `reference line/`, `calibration.json`, `reference_lines.json` → `data/`
- Modify: `hsc/app_paths.py` (`data_root`), `.gitignore`
- Test: `tests/test_data_root.py`

**Interfaces:**
- Consumes: `data_root()` from Task 2 (repo root in source mode).
- Produces: source-mode `data_root()` = `<root>/data` (auto-created). Frozen behavior is **unchanged** (output next to the .exe — deployed rigs keep their current layout). All callers (`capture_gui`, `calibrate_scale`, `reference_lines`) already build paths on top of `data_root()` and need no edits.

- [ ] **Step 1: Confirm nothing references the moved folders by literal path**

```bash
grep -rnE "reference line|calibration\.json|reference_lines\.json|injection images|captures" hsc/*.py | grep -vE "data_root|resource_root" | head -30
```

Review each hit: path strings composed onto `data_root()` (e.g. `data_root() / "captures"`) are fine; a hit that hardcodes the repo root or a path NOT rooted at `data_root()` must be updated to use `data_root()`. Expected: no such hardcoded absolute references exist.

- [ ] **Step 2: Move the data (tracked JSON/dirs via git, gitignored dirs via plain mv)**

```bash
mkdir -p data
git rm --cached calibration.json reference_lines.json
git rm -r --cached "reference line"
mv calibration.json reference_lines.json "reference line" data/
mv captures "injection images" measure data/    # untracked (gitignored) - plain move
```

- [ ] **Step 3: Update `data_root()`** in `hsc/app_paths.py`:

```python
def data_root() -> Path:
    """Base folder for user output written at runtime (``captures``,
    ``injection images``, ``measure``, calibration/reference JSON). Next to the
    .exe when frozen; ``<root>/data`` from source (created on demand)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    root = Path(__file__).resolve().parents[1] / "data"
    root.mkdir(exist_ok=True)
    return root
```

- [ ] **Step 4: Replace `.gitignore`**

```gitignore
# PyInstaller build output (large, regenerable)
build/
dist/

# Python caches
__pycache__/
*.pyc
.pytest_cache/

# Runtime data: captures, injection images, measure output, calibration and
# reference JSON. Machine-specific, often gigabytes - never committed.
data/
```

- [ ] **Step 5: Write the data-root test** (`tests/test_data_root.py`)

```python
from hsc.app_paths import data_root


def test_data_root_is_data_dir():
    d = data_root()
    assert d.name == "data"
    assert d.is_dir()


def test_moved_configs_still_found():
    d = data_root()
    assert (d / "calibration.json").is_file()
    assert (d / "reference_lines.json").is_file()
```

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -v`
Expected: all PASS — in particular `tests/test_calibration.py::test_load_calibration_found` proves `load_calibration()` follows `data_root()` to the moved `data/calibration.json`.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: gather runtime output and rig config under gitignored data/"
```

---

### Task 5: Docs into `docs/`, archive `C version/`, purge build artifacts

**Files:**
- Move: `AH7040MU000.pdf`, `工业相机SDK开发手册(C篇)_Ver2.3.pdf`, `工业相机SDK开发手册(Python篇)_Ver1.1.pdf`, `Documentations/`, `DISTRIBUTION.md` → `docs/`
- Move OUT of repo: `C version/` → `../C version/`
- Delete: `build/`, `dist/`, `__pycache__/` (regenerable, gitignored)

**Interfaces:**
- Consumes: nothing from other tasks (pure file moves — no code references any of these paths).
- Produces: clean repo root; Task 7 updates README/CLAUDE.md references to `DISTRIBUTION.md` → `docs/DISTRIBUTION.md`.

- [ ] **Step 1: Verify no code references these paths**

```bash
grep -rnE "Documentations|DISTRIBUTION|AH7040|C version|工业相机" hsc/*.py run_gui.py
```

Expected: no output. (If anything matches, update that reference as part of the move.)

- [ ] **Step 2: Move the documentation**

```bash
mkdir -p docs
git mv AH7040MU000.pdf "工业相机SDK开发手册(C篇)_Ver2.3.pdf" "工业相机SDK开发手册(Python篇)_Ver1.1.pdf" docs/
git mv Documentations docs/Documentations
git mv DISTRIBUTION.md docs/DISTRIBUTION.md
```

- [ ] **Step 3: Move the abandoned C implementation out of this repo**

```bash
mv "C version" "../C version"
git add -A   # stages deletion of the tracked "C version" files (they now live at spray-angle-test/C version)
```

- [ ] **Step 4: Delete regenerable build artifacts**

```bash
rm -rf build dist __pycache__
```

(All three are gitignored and fully regenerable — `build/`/`dist/` by Task 6, `__pycache__` automatically.)

- [ ] **Step 5: Run the suite + inspect the root**

Run: `python -m pytest -v` — expected: all PASS.
Run: `ls` — expected root contents exactly: `.claude .git .gitignore CLAUDE.md README.md data docs hsc native packaging(after task 6: not yet) pyproject.toml run_gui.py tests vendor HighSpeedCamera.spec build_exe.bat` (the last two move in Task 6).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: move docs into docs/, archive C version outside repo, drop build artifacts"
```

---

### Task 6: Packaging — rewrite the PyInstaller spec for the new layout and verify a real build

**Files:**
- Move + rewrite: `HighSpeedCamera.spec` → `packaging/HighSpeedCamera.spec`
- Move + rewrite: `build_exe.bat` → `packaging/build_exe.bat`

**Interfaces:**
- Consumes: `run_gui.py` entry point (Task 2), `vendor/` layout + `resource_root() = <base>/vendor` contract (Task 3), frozen `data_root()` = exe dir (Task 4).
- Produces: `dist/HighSpeedCamera/HighSpeedCamera.exe` with `vendor/Runtime/x64`, `vendor/Development/.../MVSDK`, `vendor/bin/injection_scan.exe` inside the bundle — matching what frozen `resource_root()` expects.

- [ ] **Step 1: Move the files**

```bash
mkdir -p packaging
git mv HighSpeedCamera.spec packaging/HighSpeedCamera.spec
git mv build_exe.bat packaging/build_exe.bat
```

- [ ] **Step 2: Rewrite `packaging/HighSpeedCamera.spec`**

```python
# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for the High Speed Camera GUI.

Produces a one-folder distribution in ``dist/HighSpeedCamera`` that can be
zipped and copied to another Windows PC. Build from the project root with:

    packaging\\build_exe.bat

The vendor camera SDK loads ``MVSDKmd.dll`` by a path *relative* to the SDK
wrapper folder (``../../../../../Runtime/x64/MVSDKmd.dll``), so ``Development``
and ``Runtime`` are bundled as siblings under a ``vendor/`` prefix - exactly
mirroring the source tree. ``hsc.app_paths.resource_root()`` resolves to
``<_MEIPASS>/vendor`` at runtime; user output is written next to the .exe via
``hsc.app_paths.data_root()``.
"""

import os

from PyInstaller.building.datastruct import Tree
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# SPECPATH is the directory holding this spec (packaging/); the project root is
# its parent. All input paths are anchored there so the build works no matter
# where pyinstaller is invoked from.
ROOT = os.path.dirname(SPECPATH)  # noqa: F821 - SPECPATH injected by PyInstaller

# scikit-learn pulls modules in lazily; collect them explicitly. scipy / numpy /
# cv2 / PIL are handled by their bundled hooks.
hiddenimports = collect_submodules("sklearn")
datas = collect_data_files("sklearn")
datas += [(os.path.join(ROOT, "vendor", "bin", "injection_scan.exe"), "vendor/bin")]

a = Analysis(
    [os.path.join(ROOT, "run_gui.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "pytest"],
    noarchive=False,
)

# Bundle the vendor SDK wrapper + Runtime DLLs, preserving relative structure
# under the same vendor/ prefix used in the source tree.
a.datas += Tree(os.path.join(ROOT, "vendor", "Runtime", "x64"),
                prefix="vendor/Runtime/x64")
a.datas += Tree(
    os.path.join(ROOT, "vendor", "Development", "Samples", "Python", "IMV", "MVSDK"),
    prefix="vendor/Development/Samples/Python/IMV/MVSDK",
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HighSpeedCamera",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="HighSpeedCamera",
)
```

- [ ] **Step 3: Rewrite `packaging/build_exe.bat`**

```bat
@echo off
REM Build the High Speed Camera GUI into a transferable Windows folder app.
REM Output: dist\HighSpeedCamera\  (zip this folder and copy it to another PC).
REM
REM Requires: pip install pyinstaller  (one time).

cd /d "%~dp0.."

python -m PyInstaller packaging\HighSpeedCamera.spec --noconfirm --clean
if errorlevel 1 (
    echo.
    echo BUILD FAILED.
    exit /b 1
)

echo.
echo Build complete: dist\HighSpeedCamera\HighSpeedCamera.exe
echo Zip the dist\HighSpeedCamera folder to transfer the app.
```

- [ ] **Step 4: Headless selftest from source (before building)**

Pick any existing run under `data/injection images/` (glob — do not assume a specific name):

```bash
FOLDER=$(ls -d "data/injection images"/*/ | head -1)
python run_gui.py --selftest "$FOLDER"; echo "selftest exit: $?"
```

Expected: exit 0 (annotated frames + `angles.csv` written to a new `data/measure/...` folder, `slowmo` video created). Nonzero = fix before proceeding.

- [ ] **Step 5: Build the exe**

```powershell
& "packaging\build_exe.bat"
```

Expected: `Build complete: dist\HighSpeedCamera\HighSpeedCamera.exe`, and inside `dist\HighSpeedCamera\` (or its `_internal\`) the paths `vendor\Runtime\x64\MVSDKmd.dll`, `vendor\Development\Samples\Python\IMV\MVSDK\`, `vendor\bin\injection_scan.exe` all exist.

- [ ] **Step 6: Selftest the frozen exe**

```powershell
$folder = (Get-ChildItem "data\injection images" -Directory | Select-Object -First 1).FullName
& "dist\HighSpeedCamera\HighSpeedCamera.exe" --selftest $folder
Get-Content "dist\HighSpeedCamera\selftest.log" -Tail 20
```

Expected: `selftest.log` (written next to the exe; the app is windowed, so there is no console output) reports the measure + video steps succeeded.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "build: move packaging into packaging/, target new vendor/ + hsc/ layout"
```

---

### Task 7: Update the documentation to the new layout

**Files:**
- Modify: `README.md`, `CLAUDE.md`, `docs/DISTRIBUTION.md`

**Interfaces:**
- Consumes: the final layout from Tasks 1–6.
- Produces: docs that match reality (CLAUDE.md is the AI-agent contract for this repo — it MUST be accurate).

- [ ] **Step 1: Update `CLAUDE.md`**

Apply these changes (keep all algorithm/design-decision text untouched):

- Module map: every `capture_gui.py` → `hsc/capture_gui.py` style path (all 11 modules + `app_paths.py`); entry point `python capture_gui.py` → `python run_gui.py`; `injection_scan.cpp/.exe` → `native/injection_scan.cpp` + `vendor/bin/injection_scan.exe`, built via `native/build_injection_scan.bat`.
- `app_paths.py` description: `resource_root()` returns `vendor/` (source: `<root>/vendor`; frozen: `<_MEIPASS>/vendor`); `data_root()` returns `<root>/data` from source, exe folder when frozen.
- Packaging section: spec + bat now in `packaging/`; build with `packaging\build_exe.bat`; selftest via `python run_gui.py --selftest "<injection folder>"`.
- Data flow section: paths become `data\captures\...`, `data\injection images\...`, `data\measure\...`; `calibration.json` / `reference_lines.json` live in `data/`.
- "How to verify changes": `python -m py_compile ...` list → `python -m pytest` plus `python -m py_compile hsc/*.py run_gui.py`; module CLIs run as `python -m hsc.measure_angle ...` (not `python measure_angle.py`).
- Add one line to Conventions: "Run module CLIs with `python -m hsc.<module>` from the repo root; the package is never pip-installed."

- [ ] **Step 2: Update `README.md`**

Same path substitutions as CLAUDE.md wherever module files, `captures/`, `injection images/`, `measure/`, the spec, or the CLI invocations are mentioned; the GUI is started with `python run_gui.py`.

- [ ] **Step 3: Update `docs/DISTRIBUTION.md`**

Build command becomes `packaging\build_exe.bat`; note that deployed-exe behavior is unchanged (output next to the exe).

- [ ] **Step 4: Verify no stale references anywhere**

```bash
grep -rnE "python capture_gui\.py|^\s*import (measure_angle|injection_extract|capture_image)\b" README.md CLAUDE.md docs/DISTRIBUTION.md
python -m pytest -q
```

Expected: no grep hits; tests PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md CLAUDE.md docs/DISTRIBUTION.md
git commit -m "docs: update module map and commands for the restructured layout"
```

---

## Final acceptance checklist (run after Task 7)

1. `python -m pytest -v` → all green.
2. `python run_gui.py --selftest "<any data/injection images run>"` → exit 0.
3. `dist\HighSpeedCamera\HighSpeedCamera.exe --selftest <same folder>` → selftest.log OK.
4. Repo root contains only: `.claude/ .git/ .gitignore CLAUDE.md README.md data/ docs/ hsc/ native/ packaging/ pyproject.toml run_gui.py tests/ vendor/`.
5. **Ask the user** to launch the GUI on the rig and confirm: live preview works (proves the vendor DLL relative-path move), Capture chain runs, Calibrate/Reference dialogs open. This cannot be verified headless.

## Out of scope (deliberately)

- Splitting the 57 KB `capture_gui.py` into smaller modules — behavior-risky, separate effort.
- Rewriting git history to shrink the pack (the `C version` / SDK blobs stay in history; optional later via `git filter-repo`).
- Raising test coverage to 80% — this suite is a characterization safety net for the restructure, not a full test effort.
- Renaming modules or changing any measurement/tuning constant.
