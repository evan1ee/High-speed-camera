# Edge Detection v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make spray-edge detection accurate, stable and robust — specifically fixing the "one edge fits well, the other doesn't" failure — via a benchmark-gated upgrade: pre-onset background, a per-side error-function (blurred-step) edge estimator, per-edge confidence with trust gating, and temporal pooling.

**Architecture:** Everything is additive and flag-gated. The current gradient/visible-crossing detector stays intact as `EDGE_MODEL = "legacy"`; the new erf estimator is a third candidate locus selected by the existing straightness contest. A synthetic benchmark with exact ground truth is built FIRST and scores the current pipeline as the baseline; each subsequent task must beat or match the baseline before its flag default flips. No tuned constant changes value; new constants are added alongside.

**Tech Stack:** Python 3.13 via uv (`uv run ...`), NumPy/SciPy/OpenCV/scikit-learn (already locked), pytest. No new dependencies.

## Global Constraints

- Work on a branch: `git checkout -b edge-v2` from `main`. Commit after every task, conventional-commits format.
- **Never change existing tuned constants** (`EDGE_*`, `RANSAC_*`, `QUALITY_*`, `NOZZLE_*`, `MEASURE_START/END`, `GAUSS_KSIZE`, `SAVGOL_*`, `MIN_*`, `ROI_FRAC`). New behavior arrives only through NEW constants/flags added next to them.
- **Preserve GUI contracts exactly:** `measure_folder(source_dir, dest_base=None, start, end, start_x=None, end_x=None, line_frac=None, progress=None)` and its return-dict keys (new keys may be ADDED, none removed/renamed); `injection_extract.build_result(files, signal, method, start, end, peak, source_dir, dest_base, before, after, copy)` signature unchanged; `injection_extract.detect_bounds_with_presence(...)` untouched.
- **`calibrate_scale.py` / `measure_block.py` must be unaffected**: they call `extract_edges` WITHOUT `return_candidates=True` — that default gradient-only path must return exactly what it returns today.
- The default behavior of the shipped app must be **bit-identical to today until Task 8 flips the flags** (`EDGE_MODEL`, `BG_MODE`, `ANGLE_POLICY`, `POOLED_FIT`), and each flip requires its benchmark gate to pass.
- All commands run from the repo root `D:\01_Data\code\spray-angle-test\High speed camera` (quote the path — it contains spaces). Tests: `uv run python -m pytest ...`. Existing suite (25 tests) must stay green after every task.
- `annotate()`'s drawn output must not gain new text/graphics (the operator asked for minimal overlays). New diagnostics go to `angles.csv` and the result dict only.
- Performance budget: `measure_frame` on a 320×240 frame must stay under **1.5 s** with all new features on (it currently runs ~50 ms; the erf fits are the risk — Task 5 includes a perf test).
- Don't commit `benchmark/results/` run outputs; DO commit `benchmark/baseline.csv` (Task 2).

## Files overview

- Create: `benchmark/__init__.py`, `benchmark/synthetic.py`, `benchmark/score.py`, `benchmark/run_benchmark.py`, `benchmark/baseline.csv` (generated), `benchmark/annotate_frames.py` (optional tool)
- Create: `tests/test_synthetic_wedges.py`, `tests/test_pre_onset_bg.py`, `tests/test_erf_edge.py`, `tests/test_edge_quality.py`, `tests/test_pooled_fit.py`
- Modify: `hsc/measure_angle.py` (new constants + `_erf_edge` + `extract_edges` candidates + selection + per-edge quality + trust gating + pooled fit), `hsc/injection_extract.py` (`build_result` writes `injection_meta.json`), `.gitignore` (benchmark results), `CLAUDE.md`/`README.md` (Task 8)

---

### Task 1: Synthetic benchmark — generator, scorer, runner

Ground truth first. A wedge renderer whose true edge lines are known exactly, a scorer that measures per-edge angle error and line distance, and a CLI runner that sweeps the failure conditions (thin jets, blur, noise, asymmetric skirt) and writes a CSV.

**Files:**
- Create: `benchmark/__init__.py` (empty), `benchmark/synthetic.py`, `benchmark/score.py`, `benchmark/run_benchmark.py`
- Create: `tests/test_synthetic_wedges.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `synthetic.make_wedge(...) -> (img, truth)` and `synthetic.make_sequence(...) -> (frames, truth)` where `truth = {"k_up","b_up","k_lo","b_lo","x_lo","x_hi"}` (image coords, y = k·x + b); `score.score_frame(result, truth) -> dict` with keys `ang_err_up, ang_err_lo, dist_up, dist_lo`; `run_benchmark.run(tag) -> Path` writing `benchmark/results/<tag>.csv`. Tasks 2–8 consume all of these.

- [ ] **Step 1: `.gitignore` — add benchmark run outputs**

Append to `.gitignore`:

```gitignore

# Benchmark run outputs (regenerable; baseline.csv IS committed)
benchmark/results/
```

- [ ] **Step 2: Write the failing generator test** (`tests/test_synthetic_wedges.py`)

```python
"""The synthetic wedge generator must produce frames whose true edges are known."""
import numpy as np

from benchmark.synthetic import make_wedge, make_sequence


def test_wedge_edges_are_where_truth_says():
    img, truth = make_wedge(half_angle_deg=3.0, blur_sigma=1.0, noise_sigma=0.0,
                            skirt_scale=0.0, brightness=230, seed=0)
    assert img.shape == (240, 320) and img.dtype == np.uint8
    # At mid-ROI, the column must be bright between the true lines and dark
    # well outside them.
    x = int((truth["x_lo"] + truth["x_hi"]) / 2)
    y_up = truth["k_up"] * x + truth["b_up"]
    y_lo = truth["k_lo"] * x + truth["b_lo"]
    assert y_lo > y_up  # image coords: upper edge has the smaller y
    mid = int(round((y_up + y_lo) / 2))
    assert img[mid, x] > 180
    assert img[int(round(y_up)) - 5, x] < 40
    assert img[int(round(y_lo)) + 5, x] < 40


def test_skirt_only_affects_the_lower_side():
    a, truth = make_wedge(half_angle_deg=3.0, blur_sigma=1.0, noise_sigma=0.0,
                          skirt_scale=0.0, brightness=230, seed=0)
    b, _ = make_wedge(half_angle_deg=3.0, blur_sigma=1.0, noise_sigma=0.0,
                      skirt_scale=3.0, brightness=230, seed=0)
    x = int((truth["x_lo"] + truth["x_hi"]) / 2)
    y_up = int(round(truth["k_up"] * x + truth["b_up"]))
    y_lo = int(round(truth["k_lo"] * x + truth["b_lo"]))
    # Below the lower edge the skirted image is brighter (the tail)...
    assert int(b[y_lo + 3, x]) > int(a[y_lo + 3, x]) + 5
    # ...above the upper edge the two are (nearly) identical.
    assert abs(int(b[y_up - 3, x]) - int(a[y_up - 3, x])) <= 2


def test_sequence_has_jet_free_head():
    frames, truth = make_sequence(n_pre=12, n_jet=15, half_angle_deg=3.0,
                                  residual_level=60, seed=0)
    assert len(frames) == 27
    # Pre-onset frames contain the static scene but no jet.
    x = int((truth["x_lo"] + truth["x_hi"]) / 2)
    y_mid = int(round((truth["k_up"] * x + truth["b_up"]
                       + truth["k_lo"] * x + truth["b_lo"]) / 2))
    assert frames[5][y_mid, x] < 100      # only the faint residual streak
    assert frames[20][y_mid, x] > 180     # jet present
```

- [ ] **Step 3: Run — must fail** (`uv run python -m pytest tests/test_synthetic_wedges.py -v` → ModuleNotFoundError)

- [ ] **Step 4: Implement `benchmark/synthetic.py`**

```python
"""Synthetic spray frames with exactly known edge lines.

Frames are rendered at 8x supersampling then area-downscaled, so the true
edges land at genuine subpixel positions. Geometry mirrors the rig: nozzle on
the RIGHT, jet travelling left, near-horizontal edges.
"""
import cv2
import numpy as np

W, H, SS = 320, 240, 8
APEX = (300.0, 120.0)          # nozzle tip (x, y) in image coords
JET_LEN = 270.0                # wedge length in px
APEX_HALF_W = 2.0              # half-width of the jet at the apex (px)


def _truth(half_angle_deg):
    """True upper/lower line params for a wedge opening by half_angle each side."""
    k = np.tan(np.radians(half_angle_deg))
    ax, ay = APEX
    # upper edge: y decreases going left from (ax, ay - APEX_HALF_W)
    k_up, b_up = k, (ay - APEX_HALF_W) - k * ax
    k_lo, b_lo = -k, (ay + APEX_HALF_W) + k * ax
    return {"k_up": k_up, "b_up": b_up, "k_lo": k_lo, "b_lo": b_lo,
            "x_lo": ax - JET_LEN, "x_hi": ax - 20.0}


def _render_wedge(half_angle_deg, brightness):
    truth = _truth(half_angle_deg)
    big = np.zeros((H * SS, W * SS), np.float64)
    ax, ay = APEX
    x0 = ax - JET_LEN
    pts = np.array([
        [ax, truth["k_up"] * ax + truth["b_up"]],
        [x0, truth["k_up"] * x0 + truth["b_up"]],
        [x0, truth["k_lo"] * x0 + truth["b_lo"]],
        [ax, truth["k_lo"] * ax + truth["b_lo"]],
    ]) * SS
    cv2.fillConvexPoly(big, np.round(pts).astype(np.int32), float(brightness))
    img = cv2.resize(big, (W, H), interpolation=cv2.INTER_AREA)
    return img, truth


def _apply_skirt(img, skirt_scale):
    """One-sided exponential tail downward: brightens BELOW edges only."""
    if skirt_scale <= 0:
        return img
    n = int(np.ceil(skirt_scale * 4))
    out = img.copy()
    for d in range(1, n + 1):
        shifted = np.zeros_like(img)
        shifted[d:, :] = img[:-d, :]
        out = np.maximum(out, shifted * np.exp(-d / skirt_scale))
    return out


def make_wedge(half_angle_deg=3.0, blur_sigma=1.0, noise_sigma=3.0,
               skirt_scale=0.0, brightness=230, base_level=12, seed=0):
    """One frame + ground-truth lines. Skirt is applied to the LOWER side only
    (physically: reflection/spray fallout below the jet)."""
    img, truth = _render_wedge(half_angle_deg, brightness)
    img = _apply_skirt(img, skirt_scale)
    if blur_sigma > 0:
        img = cv2.GaussianBlur(img, (0, 0), blur_sigma)
    rng = np.random.default_rng(seed)
    img = img + base_level + rng.normal(0.0, noise_sigma, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8), truth


def _static_scene(residual_level, rng):
    """Static background: bright nozzle block on the right + faint horizontal
    residual streak along the jet axis (the background-leak scenario)."""
    scene = np.full((H, W), 12.0)
    scene[100:140, 302:320] = 200.0                       # nozzle/holder
    if residual_level > 0:
        scene[117:124, 60:300] = float(residual_level)    # residual stream
    return cv2.GaussianBlur(scene, (0, 0), 1.0)


def make_sequence(n_pre=12, n_jet=15, half_angle_deg=3.0, blur_sigma=1.0,
                  noise_sigma=3.0, skirt_scale=2.0, brightness=230,
                  residual_level=60, seed=0):
    """n_pre jet-free frames then n_jet steady-jet frames, same static scene."""
    rng = np.random.default_rng(seed)
    scene = _static_scene(residual_level, rng)
    jet, truth = _render_wedge(half_angle_deg, brightness)
    jet = _apply_skirt(jet, skirt_scale)
    frames = []
    for i in range(n_pre + n_jet):
        f = scene + (jet if i >= n_pre else 0.0)
        if blur_sigma > 0:
            f = cv2.GaussianBlur(f, (0, 0), blur_sigma)
        f = f + rng.normal(0.0, noise_sigma, f.shape)
        frames.append(np.clip(f, 0, 255).astype(np.uint8))
    return frames, truth
```

- [ ] **Step 5: Implement `benchmark/score.py`**

```python
"""Score a measure_frame result against synthetic ground truth."""
from math import atan, degrees

import numpy as np


def _line_of(result, which):
    """(k, b) of the fitted upper/lower line from the result's endpoints."""
    p0, p1 = result[f"{which}0"], result[f"{which}1"]
    k = (p1[1] - p0[1]) / (p1[0] - p0[0])
    return float(k), float(p0[1] - k * p0[0])


def score_frame(result, truth):
    """Per-edge |angle error| (deg) and mean perpendicular distance (px)
    sampled over the truth ROI columns."""
    xs = np.linspace(truth["x_lo"], truth["x_hi"], 50)
    out = {}
    for which, kt, bt in (("up", truth["k_up"], truth["b_up"]),
                          ("lo", truth["k_lo"], truth["b_lo"])):
        kf, bf = _line_of(result, which)
        out[f"ang_err_{which}"] = abs(degrees(atan(kf)) - degrees(atan(kt)))
        d = np.abs((kf * xs + bf) - (kt * xs + bt)) / np.sqrt(1.0 + kf * kf)
        out[f"dist_{which}"] = float(d.mean())
    return out
```

- [ ] **Step 6: Implement `benchmark/run_benchmark.py`**

```python
"""Sweep the failure conditions, score the current pipeline, write a CSV.

Usage:  uv run python -m benchmark.run_benchmark <tag>
Writes: benchmark/results/<tag>.csv  (one row per case, plus a summary row)

Two suites:
  single : make_wedge -> measure_frame(bg=None)  (estimator accuracy)
  seq    : make_sequence -> BMPs in a temp dir -> measure_folder  (pipeline)
"""
import csv
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

from hsc import measure_angle as ma
from benchmark.synthetic import make_wedge, make_sequence
from benchmark.score import score_frame

SINGLE_CASES = [
    # (name, half_angle, blur, noise, skirt, brightness)
    ("sharp",        3.0, 0.7,  2.0, 0.0, 230),
    ("blurry",       3.0, 2.0,  3.0, 0.0, 230),
    ("noisy",        3.0, 1.0,  8.0, 0.0, 230),
    ("skirt_mild",   3.0, 1.0,  3.0, 2.0, 230),
    ("skirt_heavy",  3.0, 1.0,  3.0, 4.0, 230),
    ("thin_narrow",  1.0, 0.8,  3.0, 0.0, 230),
    ("faint",        3.0, 1.0,  3.0, 2.0, 120),
    ("worst",        1.5, 1.5,  6.0, 3.0, 150),
]
SEQ_CASES = [
    # (name, residual_level, skirt)
    ("seq_clean",    0,  0.0),
    ("seq_residual", 60, 2.0),   # the background-leak scenario
]
SEEDS = (0, 1, 2)


def run(tag):
    rows = []
    for name, ha, blur, noise, skirt, bright in SINGLE_CASES:
        for seed in SEEDS:
            img, truth = make_wedge(ha, blur, noise, skirt, bright, seed=seed)
            res = ma.measure_frame(img, bg=None,
                                   start_x=truth["x_lo"], end_x=truth["x_hi"])
            if res is None:
                rows.append({"suite": "single", "case": name, "seed": seed,
                             "ang_err_up": 99.0, "ang_err_lo": 99.0,
                             "dist_up": 99.0, "dist_lo": 99.0})
                continue
            rows.append({"suite": "single", "case": name, "seed": seed,
                         **score_frame(res, truth)})
    for name, residual, skirt in SEQ_CASES:
        frames, truth = make_sequence(residual_level=residual,
                                      skirt_scale=skirt, seed=0)
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "run"
            src.mkdir()
            for i, f in enumerate(frames):
                cv2.imwrite(str(src / f"frame_{i:06d}.bmp"), f)
            out = ma.measure_folder(src, dest_base=Path(td) / "measure",
                                    start=3, end=10,
                                    start_x=truth["x_lo"], end_x=truth["x_hi"])
            # Rescore each measured frame against the truth via a re-measure of
            # the mean: use the folder's per-frame results indirectly through
            # the returned mean angle vs the true full angle.
            true_angle = abs(np.degrees(np.arctan(truth["k_up"]))
                             - np.degrees(np.arctan(truth["k_lo"])))
            rows.append({"suite": "seq", "case": name, "seed": 0,
                         "ang_err_up": abs(out["mean_angle"] - true_angle),
                         "ang_err_lo": abs(out["mean_angle"] - true_angle),
                         "dist_up": out["angle_std"], "dist_lo": out["angle_std"]})
    dest = Path(__file__).parent / "results"
    dest.mkdir(exist_ok=True)
    out_path = dest / f"{tag}.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["suite", "case", "seed",
                                           "ang_err_up", "ang_err_lo",
                                           "dist_up", "dist_lo"])
        w.writeheader()
        for r in rows:
            w.writerow({k: (f"{v:.4f}" if isinstance(v, float) else v)
                        for k, v in r.items()})
        worst = max(max(r["ang_err_up"], r["ang_err_lo"]) for r in rows)
        mean = np.mean([[r["ang_err_up"], r["ang_err_lo"]] for r in rows])
        w.writerow({"suite": "summary", "case": "mean_ang_err", "seed": "",
                    "ang_err_up": f"{mean:.4f}", "ang_err_lo": "",
                    "dist_up": f"{worst:.4f}", "dist_lo": "worst"})
    print(f"wrote {out_path}")
    return out_path


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "run")
```

NOTE for the implementer: the seq-suite scoring above compares the *reported mean angle* to the true wedge angle — but when a nozzle reference is set on the dev machine (`data/reference_lines.json` exists), `measure_folder` reports the angle **vs the centerline** instead (`angle = max(angle_upper, angle_lower)`), which would corrupt the comparison. Guard the seq suite: monkeypatch/parameterize `reference_lines.load_reference` to return `None` during benchmark runs (e.g. `ma.reference_lines.load_reference = lambda: None` at the top of `run()`, restoring after). Implement that guard — it is required for correct scores.

- [ ] **Step 7: Run tests + a smoke run**

`uv run python -m pytest tests/test_synthetic_wedges.py -v` → 3 PASS.
`uv run python -m benchmark.run_benchmark smoke` → writes `benchmark/results/smoke.csv`; open it and sanity-check: `sharp` case ang_err ≲ 0.3°, `skirt_heavy`/`worst` visibly worse (that is the point).

- [ ] **Step 8: Full suite + commit**

`uv run python -m pytest -q` → 28 passed (25 + 3).

```bash
git add benchmark/ tests/test_synthetic_wedges.py .gitignore
git commit -m "feat: synthetic edge-accuracy benchmark with exact ground truth"
```

---

### Task 2: Baseline snapshot

**Files:** Create: `benchmark/baseline.csv` (committed)

- [ ] **Step 1:** `uv run python -m benchmark.run_benchmark baseline_tmp` then copy `benchmark/results/baseline_tmp.csv` → `benchmark/baseline.csv`.
- [ ] **Step 2:** Record in the commit message body the summary row (mean and worst ang_err). These numbers are the gates for Tasks 3–8.
- [ ] **Step 3:** Commit:

```bash
git add benchmark/baseline.csv
git commit -m "chore: record edge-detection baseline benchmark scores"
```

---

### Task 3: Pre-onset background

The temporal-median background currently includes the steady jet (bright-side edge clipping — the root cause of one-sided misfits over the residual stream). The injection folder's leading `before`-padding frames are jet-free by construction; use them.

**Files:**
- Modify: `hsc/injection_extract.py` (`build_result` — write `injection_meta.json`)
- Modify: `hsc/measure_angle.py` (`measure_folder` — background selection; new constants)
- Test: `tests/test_pre_onset_bg.py`

**Interfaces:**
- Produces: `injection_meta.json` in every new injection folder: `{"pre_frames": int, "onset_index": int, "copy_start": int, "copy_end": int, "method": str}`. `measure_angle` gains `BG_MODE` (`"window"` = legacy default until Task 8, `"pre-onset"`), `BG_MIN_PRE_FRAMES = 8`, and helper `_pre_onset_background(files, source_dir) -> bg | None`.

- [ ] **Step 1: Failing tests** (`tests/test_pre_onset_bg.py`)

```python
"""Pre-onset background: built only from the jet-free frames at folder start."""
import json

import cv2
import numpy as np
import pytest

from benchmark.synthetic import make_sequence
from hsc import measure_angle as ma


def _write_frames(frames, folder):
    folder.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(frames):
        cv2.imwrite(str(folder / f"frame_{i:06d}.bmp"), f)


def test_build_result_writes_meta(tmp_path):
    from hsc import injection_extract as ie
    frames, _ = make_sequence(n_pre=6, n_jet=6, seed=0)
    src = tmp_path / "burst"
    _write_frames(frames, src)
    files = ie.list_frames(src)
    signal = np.zeros(len(files))
    res = ie.build_result(files, signal, "test", start=6, end=11, peak=8,
                          source_dir=src, dest_base=tmp_path / "inj",
                          before=4, after=0, copy=True)
    meta_path = next((tmp_path / "inj").rglob("injection_meta.json"))
    meta = json.loads(meta_path.read_text())
    assert meta["pre_frames"] == 4          # start(6) - copy_start(2)
    assert meta["onset_index"] == 6
    assert meta["copy_start"] == 2


def test_pre_onset_bg_excludes_the_jet(tmp_path):
    frames, truth = make_sequence(n_pre=10, n_jet=10, residual_level=60, seed=0)
    src = tmp_path / "inj"
    _write_frames(frames, src)
    (src / "injection_meta.json").write_text(json.dumps(
        {"pre_frames": 10, "onset_index": 10, "copy_start": 0,
         "copy_end": 19, "method": "test"}))
    files = ma.list_frames(src)
    bg = ma._pre_onset_background(files, src)
    assert bg is not None
    # Background must NOT contain the jet: at jet mid-height it stays at the
    # residual-streak level, far below the jet brightness.
    x = int((truth["x_lo"] + truth["x_hi"]) / 2)
    y = int(round((truth["k_up"] * x + truth["b_up"]
                   + truth["k_lo"] * x + truth["b_lo"]) / 2))
    assert bg[y, x] < 100


def test_pre_onset_bg_falls_back_without_enough_frames(tmp_path):
    frames, _ = make_sequence(n_pre=3, n_jet=8, seed=0)   # 3 < BG_MIN_PRE_FRAMES
    src = tmp_path / "inj"
    _write_frames(frames, src)
    (src / "injection_meta.json").write_text(json.dumps(
        {"pre_frames": 3, "onset_index": 3, "copy_start": 0,
         "copy_end": 10, "method": "test"}))
    assert ma._pre_onset_background(ma.list_frames(src), src) is None
```

- [ ] **Step 2: Run — fail** (`uv run python -m pytest tests/test_pre_onset_bg.py -v` → AttributeError / missing meta)

- [ ] **Step 3: Implement the meta write in `hsc/injection_extract.py`**

In `build_result`, right after the `if copy:` block copies the files (and only when `copy` is true), add:

```python
    if copy:
        meta = {
            "pre_frames": int(start - copy_start),
            "onset_index": int(start),
            "copy_start": int(copy_start),
            "copy_end": int(copy_end),
            "method": str(method),
        }
        try:
            (dest_dir / "injection_meta.json").write_text(
                json.dumps(meta, indent=2), encoding="utf-8")
        except OSError:
            pass    # metadata is an optimization, never a failure
```

(`import json` at the top of the module; merge into the existing `if copy:` block rather than testing `copy` twice.) Also verify `list_frames`' extension filter ignores `.json` (it does — `IMAGE_EXTENSIONS`), so the meta file can live inside the injection folder without affecting frame listing anywhere.

- [ ] **Step 4: Implement background selection in `hsc/measure_angle.py`**

New constants next to the other pipeline parameters:

```python
# ---- Background construction ----------------------------------------------
# "window"   : temporal median over the whole injection window (legacy). When
#              the jet is steady it leaks into the median and subtraction clips
#              the bright-side edge ramp (the EDGE_BAND_* walk-out compensates).
# "pre-onset": median over ONLY the jet-free padding frames at the folder start
#              (count from injection_meta.json, written by injection_extract),
#              so the background never contains the jet. Falls back to "window"
#              when the meta file is absent or too few pre-frames exist.
BG_MODE = "window"           # flipped to "pre-onset" by the Task 8 gate
BG_MIN_PRE_FRAMES = 8        # need at least this many jet-free frames
```

New helper (place next to `compute_background`):

```python
def _pre_onset_background(files, source_dir):
    """Median background from the jet-free head of an injection folder, using
    injection_meta.json's pre_frames count. None if unavailable/insufficient."""
    meta_path = Path(source_dir) / "injection_meta.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        pre = int(meta["pre_frames"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if pre < BG_MIN_PRE_FRAMES or pre > len(files):
        return None
    stack = np.stack([load_gray(f) for f in files[:pre]])
    return np.median(stack, axis=0).astype(np.int16)
```

(`import json` at the top of the module.) In `measure_folder`, replace the single line `bg = compute_background(files)` with:

```python
    bg = None
    if BG_MODE == "pre-onset":
        bg = _pre_onset_background(files, source_dir)
    if bg is None:
        bg = compute_background(files)
```

- [ ] **Step 5: Run tests** — the three new tests PASS; full suite `uv run python -m pytest -q` → 31 passed. (Default `BG_MODE="window"` means shipped behavior unchanged.)

- [ ] **Step 6: Benchmark the flag** — temporarily set `ma.BG_MODE = "pre-onset"` inside a throwaway run: `uv run python -c "from hsc import measure_angle as ma; ma.BG_MODE='pre-onset'; from benchmark.run_benchmark import run; run('preonset')"`. Gate: `seq_residual` ang_err must improve vs `benchmark/baseline.csv` and `seq_clean` must not regress by more than 0.05°. Record both numbers in the commit body. NOTE: the seq suite writes frames to a temp burst folder directly — for the meta file to exist there, extend `run_benchmark.run`'s seq branch (right after the `cv2.imwrite` loop) with:

```python
            (src / "injection_meta.json").write_text(json.dumps(
                {"pre_frames": 12, "onset_index": 12, "copy_start": 0,
                 "copy_end": len(frames) - 1, "method": "synthetic"}))
```

(and `import json` at the top of `run_benchmark.py`). Do it in this task and re-run.

- [ ] **Step 7: Commit**

```bash
git add hsc/injection_extract.py hsc/measure_angle.py tests/test_pre_onset_bg.py benchmark/run_benchmark.py
git commit -m "feat: pre-onset background mode (BG_MODE) with injection_meta.json"
```

---

### Task 4: Per-side error-function edge estimator (the core fix)

A blurred step edge is `I(y) = base + amp·Φ((y−μ)/σ)`; fitting it per column, per side gives the true edge center `μ` independent of how slow that side's falloff is — the skirt becomes the model's `σ` instead of a bias. Each side gets its OWN base/amp/σ, which is what finally treats the two edges as the physically different problems they are.

**Files:**
- Modify: `hsc/measure_angle.py` (new constants, `_erf_edge`, `extract_edges` third candidate, `_pick_best_locus`, `measure_frame` integration)
- Test: `tests/test_erf_edge.py`

**Interfaces:**
- Produces: `EDGE_MODEL` (`"legacy"` default / `"erf"`), `_erf_edge(raw_seg, peak, core, is_top) -> (subpixel_row|None, confidence 0..1)`, `extract_edges(..., return_candidates=True)` return extended to `(xs, top, bot)` where `top`/`bot` are dicts `{"grad": arr, "vis": arr, "erf": arr|None, "conf": arr|None}`; `_pick_best_locus(xr, cands) -> (key, y_full)` choosing the straightest candidate. `measure_frame` result dict gains `"edge_conf_upper"`, `"edge_conf_lower"` (floats 0..1; 1.0 in legacy mode). Consumed by Task 5.

- [ ] **Step 1: Failing tests** (`tests/test_erf_edge.py`)

```python
"""erf edge model: accurate on clean steps AND on one-sided skirts."""
import numpy as np
import pytest
from scipy.special import erf as _sperf

from benchmark.synthetic import make_wedge
from benchmark.score import score_frame
from hsc import measure_angle as ma


def _step(mu, sigma, base, amp, n=25, flip=False):
    y = np.arange(n, dtype=float)
    v = base + amp * 0.5 * (1.0 + _sperf((y - mu) / (sigma * np.sqrt(2.0))))
    return v[::-1].copy() if flip else v


def test_erf_edge_recovers_known_center():
    seg = _step(mu=11.35, sigma=1.2, base=15, amp=200)
    pos, conf = ma._erf_edge(seg, peak=11, core=22, is_top=True)
    assert pos is not None and abs(pos - 11.35) < 0.15
    assert conf > 0.8


def test_erf_edge_center_unbiased_by_skirt_width():
    # Same center, very different sigma (sharp vs skirt): mu must not move.
    sharp = _step(mu=12.0, sigma=0.7, base=15, amp=200)
    skirt = _step(mu=12.0, sigma=3.0, base=15, amp=200)
    p1, _ = ma._erf_edge(sharp, peak=12, core=24, is_top=True)
    p2, _ = ma._erf_edge(skirt, peak=12, core=24, is_top=True)
    assert abs(p1 - 12.0) < 0.2 and abs(p2 - 12.0) < 0.35


def test_erf_edge_fails_gracefully_on_flat_column():
    seg = np.full(25, 20.0)
    pos, conf = ma._erf_edge(seg, peak=12, core=20, is_top=True)
    assert pos is None and conf == 0.0


def test_erf_model_beats_or_matches_legacy_on_heavy_skirt():
    img, truth = make_wedge(half_angle_deg=3.0, blur_sigma=1.0, noise_sigma=3.0,
                            skirt_scale=4.0, brightness=230, seed=1)
    kwargs = dict(bg=None, start_x=truth["x_lo"], end_x=truth["x_hi"])
    old_mode = ma.EDGE_MODEL
    try:
        ma.EDGE_MODEL = "legacy"
        s_legacy = score_frame(ma.measure_frame(img, **kwargs), truth)
        ma.EDGE_MODEL = "erf"
        s_erf = score_frame(ma.measure_frame(img, **kwargs), truth)
    finally:
        ma.EDGE_MODEL = old_mode
    # The skirted LOWER edge is where legacy fails; erf must do at least as well.
    assert s_erf["ang_err_lo"] <= s_legacy["ang_err_lo"] + 0.05
    assert s_erf["ang_err_up"] <= s_legacy["ang_err_up"] + 0.05


def test_legacy_mode_is_bit_identical_to_today():
    img, truth = make_wedge(seed=0)
    kwargs = dict(bg=None, start_x=truth["x_lo"], end_x=truth["x_hi"])
    r = ma.measure_frame(img, **kwargs)     # EDGE_MODEL defaults to "legacy"
    assert r is not None and "edge_conf_upper" in r
    assert r["edge_conf_upper"] == 1.0 and r["edge_conf_lower"] == 1.0
```

- [ ] **Step 2: Run — fail** (no `_erf_edge`, no `EDGE_MODEL`)

- [ ] **Step 3: Implement in `hsc/measure_angle.py`**

Imports: add `from scipy.optimize import curve_fit` and `from scipy.special import erf as _scipy_erf` at the top. New constants (next to `EDGE_PICK_TOL`):

```python
# ---- erf (blurred-step) edge model ------------------------------------------
# The gradient peak marks the ~50% ramp point and the visible-crossing walks a
# fixed fraction -- both are biased when one side has a slow skirt/reflection
# falloff. Fitting I(y) = base + amp*Phi((y-mu)/sigma) per column PER SIDE gives
# the true step center mu with that side's own base/amp/sigma, so a skirted
# lower edge no longer drags its fitted line. Selected per edge by the same
# straightness contest as the visible locus (EDGE_PICK_TOL).
EDGE_MODEL = "legacy"        # "erf" enabled by the Task 8 gate
ERF_FIT_HALF = 5             # fit window: peak +/- this many px
ERF_SIGMA_MAX = 5.0          # reject wider ramps as "no edge here"
ERF_MIN_AMP = 8.0            # reject fits with less contrast than this
```

New function (after `_visible_edge_crossing`):

```python
def _erf_edge(seg, peak, core, is_top):
    """Fit a blurred-step model around the gradient peak of one column side.

    ``seg`` is the column segment (float array), ``peak`` the integer gradient
    peak index within it, ``core`` the bright-core index, ``is_top`` selects the
    ramp orientation (top edge: intensity RISES with row index toward the core;
    bottom edge: falls). Returns ``(subpixel_row_in_seg | None, confidence)``
    where confidence in [0, 1] reflects the residual vs the fitted amplitude.
    """
    lo = max(0, peak - ERF_FIT_HALF)
    hi = min(len(seg) - 1, peak + ERF_FIT_HALF)
    if hi - lo < 4:
        return None, 0.0
    y = np.arange(lo, hi + 1, dtype=float)
    v = np.asarray(seg[lo : hi + 1], dtype=float)
    vmin, vmax = float(v.min()), float(v.max())
    if vmax - vmin < ERF_MIN_AMP:
        return None, 0.0
    sign = 1.0 if is_top else -1.0

    def model(yy, mu, sigma, base, amp):
        return base + amp * 0.5 * (1.0 + _scipy_erf(sign * (yy - mu)
                                                    / (sigma * np.sqrt(2.0))))

    p0 = (float(peak), 1.0, vmin, vmax - vmin)
    bounds = ((lo, 0.3, 0.0, ERF_MIN_AMP), (hi, ERF_SIGMA_MAX, 255.0, 255.0))
    try:
        popt, _ = curve_fit(model, y, v, p0=p0, bounds=bounds, maxfev=200)
    except (RuntimeError, ValueError):
        return None, 0.0
    mu, sigma, base, amp = popt
    resid = float(np.sqrt(np.mean((model(y, *popt) - v) ** 2)))
    conf = float(np.clip(1.0 - resid / max(amp, 1e-6), 0.0, 1.0))
    if conf <= 0.0:
        return None, 0.0
    return float(mu), conf
```

- [ ] **Step 4: Extend `extract_edges`**

Inside the per-column loop, after the existing visible-crossing block, add (fitting on the RAW column, not the smoothed one — the model handles noise, and smoothing would inflate σ):

```python
        if want_erf:
            raw_seg = gray[r0 : r1 + 1, x].astype(np.float64)
            te, tc = _erf_edge(raw_seg, it, core, True) if core >= 1 else (None, 0.0)
            be, bc = _erf_edge(raw_seg, ib, core, False) \
                if core < seg.size - 1 else (None, 0.0)
            y_top_e.append(float(r0 + te) if te is not None else float(top))
            conf_top.append(tc)
            y_bot_e.append(float(r0 + be) if be is not None else float(bot))
            conf_bot.append(bc)
```

with `want_erf = return_candidates and EDGE_MODEL == "erf"` computed next to `want_vis`, and the four new lists initialized alongside the others. Change the candidate return (only the `return_candidates=True` paths — the plain 3-tuple default path is UNTOUCHED) to dicts:

```python
    top = {"grad": y_top, "vis": np.array(y_top_v) if want_vis else y_top.copy(),
           "erf": np.array(y_top_e) if want_erf else None,
           "conf": np.array(conf_top) if want_erf else None}
    bot = {"grad": y_bot, "vis": np.array(y_bot_v) if want_vis else y_bot.copy(),
           "erf": np.array(y_bot_e) if want_erf else None,
           "conf": np.array(conf_bot) if want_erf else None}
    return xs, top, bot
```

- [ ] **Step 5: Generalize the selection + wire `measure_frame`**

Replace `_pick_edge_locus` usage in `measure_frame` with a new selector (keep `_pick_edge_locus` itself — `tests` or callers may reference it; mark its docstring "superseded by _pick_best_locus"):

```python
def _pick_best_locus(xr, cands):
    """Choose the straightest candidate locus for one edge.

    ``cands`` is a list of (name, roi_points, full_array); straightness is the
    robust sigma around each candidate's own least-squares line (as in
    _pick_edge_locus). Later entries win ties within EDGE_PICK_TOL, so order
    candidates from most conservative to most preferred: grad, vis, erf.
    Returns (name, full_array).
    """
    if xr.size < 2:
        return cands[0][0], cands[0][2]
    def sig(y):
        k, b = np.polyfit(xr, y, 1)
        return _robust_sigma(y - (k * xr + b))
    best_name, best_full, best_sig = cands[0][0], cands[0][2], sig(cands[0][1])
    for name, roi_pts, full in cands[1:]:
        s = sig(roi_pts)
        if s <= EDGE_PICK_TOL * best_sig:
            best_name, best_full, best_sig = name, full, min(s, best_sig)
    return best_name, best_full
```

In `measure_frame`, replace the two `_pick_edge_locus` selections with:

```python
    def _cands(c):
        lst = [("grad", c["grad"][roi], c["grad"]),
               ("vis", c["vis"][roi], c["vis"])]
        if c["erf"] is not None:
            lst.append(("erf", c["erf"][roi], c["erf"]))
        return lst

    top_name, y_top = _pick_best_locus(xr.astype(float), _cands(top_cands))
    bot_name, y_bot = _pick_best_locus(xr.astype(float), _cands(bot_cands))
```

and add to the returned dict:

```python
        "edge_conf_upper": float(np.mean(top_cands["conf"][roi]))
                           if top_cands["conf"] is not None else 1.0,
        "edge_conf_lower": float(np.mean(bot_cands["conf"][roi]))
                           if bot_cands["conf"] is not None else 1.0,
        "locus_upper": top_name,
        "locus_lower": bot_name,
```

CAREFUL: `measure_frame` currently indexes `top_cands[0]/[1]` (tuple) — update those accesses to the dict form; `extract_edges`'s `return_candidates=True` contract changes shape, and `measure_frame` is its ONLY caller with that flag (verify with grep: `grep -n "return_candidates" hsc/*.py`).

- [ ] **Step 6: Run tests** — `uv run python -m pytest tests/test_erf_edge.py -v` → 5 PASS; full suite → 36 passed. Tuning latitude: if `test_erf_edge_center_unbiased_by_skirt_width` misses tolerance, adjust `ERF_FIT_HALF` (5→7) — widening the fit window is the intended knob; do NOT loosen the test beyond 0.35 px.

- [ ] **Step 7: Perf test** — append to `tests/test_erf_edge.py`:

```python
def test_erf_mode_meets_perf_budget():
    import time
    img, truth = make_wedge(seed=0)
    old = ma.EDGE_MODEL
    try:
        ma.EDGE_MODEL = "erf"
        t0 = time.perf_counter()
        ma.measure_frame(img, bg=None, start_x=truth["x_lo"], end_x=truth["x_hi"])
        dt = time.perf_counter() - t0
    finally:
        ma.EDGE_MODEL = old
    assert dt < 1.5, f"measure_frame took {dt:.2f}s in erf mode"
```

If it fails: vectorize by fitting only every column (they already are one fit per column ×2) with `maxfev=100` and a cheaper 3-parameter fit (fix `base` to the window minimum). Only optimize if the budget fails.

- [ ] **Step 8: Benchmark + commit** — `uv run python -c "from hsc import measure_angle as ma; ma.EDGE_MODEL='erf'; from benchmark.run_benchmark import run; run('erf')"`. Gate: `skirt_heavy`, `worst`, `faint` mean ang_err strictly better than baseline; `sharp`/`blurry` within +0.05° of baseline. Record numbers in the commit body.

```bash
git add hsc/measure_angle.py tests/test_erf_edge.py
git commit -m "feat: per-side erf blurred-step edge estimator (EDGE_MODEL) with per-column confidence"
```

---

### Task 5: Per-edge quality + trust gating

Today `angle = max(angle_upper, angle_lower)` when a reference is set — so a badly-fitted edge *becomes* the reported number. Score each edge separately and, when exactly one edge is untrusted, report the trusted edge's deviation instead (flagged in the CSV).

**Files:**
- Modify: `hsc/measure_angle.py` (per-edge scores in pass 2 of `measure_folder`; `ANGLE_POLICY`; CSV columns)
- Test: `tests/test_edge_quality.py`

**Interfaces:**
- Produces: result-dict keys per measured frame: `quality_upper`, `quality_lower` (0–100), `confidence_upper`, `confidence_lower` (High/Medium/Low), `angle_policy` (`"max"` or `"upper-only"`/`"lower-only"`). New constant `ANGLE_POLICY = "max"` (legacy default; `"trusted"` enabled by Task 8 gate). New pure helper `edge_quality(rms, edge_conf) -> float` and `resolve_angle(angle_upper, angle_lower, conf_upper, conf_lower) -> (angle, policy)` so the logic is unit-testable without a folder run. `angles.csv` gains columns `q_up,q_lo,policy` appended AFTER the existing columns (the GUI does not parse the CSV — verify with `grep -n "angles.csv" hsc/capture_gui.py` — it only opens the folder; safe to extend).

- [ ] **Step 1: Failing tests** (`tests/test_edge_quality.py`)

```python
"""Per-edge quality scores and the trusted-edge angle policy."""
from hsc import measure_angle as ma


def test_edge_quality_combines_rms_and_confidence():
    good = ma.edge_quality(rms=0.15, edge_conf=0.95)
    bad_fit = ma.edge_quality(rms=1.2, edge_conf=0.95)
    bad_conf = ma.edge_quality(rms=0.15, edge_conf=0.05)
    assert good > 75
    assert bad_fit < 25 and bad_conf < 25


def test_resolve_angle_max_policy_is_legacy():
    old = ma.ANGLE_POLICY
    try:
        ma.ANGLE_POLICY = "max"
        angle, policy = ma.resolve_angle(0.5, 2.0, "High", "Low")
        assert angle == 2.0 and policy == "max"
    finally:
        ma.ANGLE_POLICY = old


def test_resolve_angle_trusted_policy_drops_the_bad_edge():
    old = ma.ANGLE_POLICY
    try:
        ma.ANGLE_POLICY = "trusted"
        angle, policy = ma.resolve_angle(0.5, 2.0, "High", "Low")
        assert angle == 0.5 and policy == "upper-only"
        angle, policy = ma.resolve_angle(2.0, 0.5, "Low", "Medium")
        assert angle == 0.5 and policy == "lower-only"
        # Both trusted (or both untrusted): fall back to max.
        angle, policy = ma.resolve_angle(0.5, 2.0, "High", "High")
        assert angle == 2.0 and policy == "max"
        angle, policy = ma.resolve_angle(0.5, 2.0, "Low", "Low")
        assert angle == 2.0 and policy == "max"
    finally:
        ma.ANGLE_POLICY = old
```

- [ ] **Step 2: Run — fail.**

- [ ] **Step 3: Implement in `hsc/measure_angle.py`**

Constant (next to the quality constants):

```python
# Angle policy when a nozzle reference is set: "max" reports the worse edge's
# deviation (legacy -- a badly-fitted edge becomes the number); "trusted"
# reports the trusted edge alone when exactly one edge is Low-confidence.
ANGLE_POLICY = "max"         # "trusted" enabled by the Task 8 gate
```

Helpers (after `frame_quality`):

```python
def edge_quality(rms, edge_conf):
    """0-100 score for ONE edge: fit straightness AND estimator confidence."""
    s_fit = _ramp_score(rms, QUALITY_RMS_GOOD, QUALITY_RMS_BAD)
    s_conf = float(np.clip(edge_conf, 0.0, 1.0)) * 100.0
    return min(s_fit, s_conf)


def resolve_angle(angle_upper, angle_lower, conf_upper, conf_lower):
    """Reported angle + policy tag. Under "trusted", when exactly one edge is
    Low-confidence the other edge's deviation is reported alone."""
    if ANGLE_POLICY == "trusted":
        if conf_upper != "Low" and conf_lower == "Low":
            return angle_upper, "upper-only"
        if conf_lower != "Low" and conf_upper == "Low":
            return angle_lower, "lower-only"
    return max(angle_upper, angle_lower), "max"
```

In `measure_folder` pass 2, inside the loop right after `r["confidence"] = confidence_level(score)`, add:

```python
        q_up = edge_quality(r["rms_upper"], r.get("edge_conf_upper", 1.0))
        q_lo = edge_quality(r["rms_lower"], r.get("edge_conf_lower", 1.0))
        r["quality_upper"], r["quality_lower"] = q_up, q_lo
        r["confidence_upper"] = confidence_level(q_up)
        r["confidence_lower"] = confidence_level(q_lo)
        r["angle_policy"] = "max"
```

and change the reference-angle block from `r["angle"] = max(...)` to:

```python
        if has_ref and blue_dir is not None:
            r["angle_upper"] = line_angle_deg(blue_dir, r["dir_upper"])
            r["angle_lower"] = line_angle_deg(blue_dir, r["dir_lower"])
            r["angle"], r["angle_policy"] = resolve_angle(
                r["angle_upper"], r["angle_lower"],
                r["confidence_upper"], r["confidence_lower"])
```

CSV: extend the header line to `...,quality,confidence,q_up,q_lo,policy\n` and the row write with `f"...,{r['quality_upper']:.0f},{r['quality_lower']:.0f},{r['angle_policy']}\n"` (keep the summary rows' comma counts consistent — add three commas to each).

- [ ] **Step 4: Run tests** — new tests PASS; full suite green (`ANGLE_POLICY="max"` keeps behavior identical; the CSV gains columns — if any existing test asserts the exact header, update it in the same commit and say so).

- [ ] **Step 5: Commit**

```bash
git add hsc/measure_angle.py tests/test_edge_quality.py
git commit -m "feat: per-edge quality scores and trusted-edge angle policy (ANGLE_POLICY)"
```

---

### Task 6: Temporal pooled fit

Frames 10–20 image the same steady jet; pooling their raw edge samples into one fit per edge gives ~11× the data and makes droplet/locus jitter statistically irrelevant. Reported ALONGSIDE the per-frame angles (new summary row + result keys), never replacing them.

**Files:**
- Modify: `hsc/measure_angle.py` (`measure_frame` stores raw chosen ROI points; `measure_folder` pooled fit + CSV row + result keys; `POOLED_FIT` flag)
- Test: `tests/test_pooled_fit.py`

**Interfaces:**
- Produces: `POOLED_FIT = True` (pure addition — always safe to compute; flag exists to disable in an emergency), `measure_frame` result gains `"raw_roi"` = `(xr, y_up_raw_roi, y_lo_raw_roi)` (float arrays), `measure_folder` return dict gains `"pooled_angle"` (float) and `"pooled_n"` (int), `angles.csv` gains a `pooled_angle` summary row.

- [ ] **Step 1: Failing test** (`tests/test_pooled_fit.py`)

```python
"""Pooled fit across frames must be at least as stable as per-frame angles."""
import cv2
import numpy as np

from benchmark.synthetic import make_sequence
from hsc import measure_angle as ma


def test_pooled_angle_close_to_truth_and_reported(tmp_path):
    frames, truth = make_sequence(n_pre=10, n_jet=12, noise_sigma=6.0, seed=2)
    src = tmp_path / "inj"
    src.mkdir()
    for i, f in enumerate(frames):
        cv2.imwrite(str(src / f"frame_{i:06d}.bmp"), f)
    old = ma.reference_lines.load_reference
    ma.reference_lines.load_reference = lambda: None
    try:
        out = ma.measure_folder(src, dest_base=tmp_path / "m", start=2, end=9,
                                start_x=truth["x_lo"], end_x=truth["x_hi"])
    finally:
        ma.reference_lines.load_reference = old
    true_angle = abs(np.degrees(np.arctan(truth["k_up"]))
                     - np.degrees(np.arctan(truth["k_lo"])))
    assert "pooled_angle" in out and out["pooled_n"] > 0
    assert abs(out["pooled_angle"] - true_angle) <= \
        abs(out["mean_angle"] - true_angle) + 0.15
    csv_text = (tmp_path / "m").rglob("angles.csv").__next__().read_text()
    assert "pooled_angle" in csv_text
```

- [ ] **Step 2: Run — fail.**

- [ ] **Step 3: Implement**

Constant: `POOLED_FIT = True` (next to `ANGLE_POLICY`). In `measure_frame`, add to the returned dict (xr and the CHOSEN raw loci are already in scope):

```python
        "raw_roi": (xr.astype(float), y_top[roi].astype(float),
                    y_bot[roi].astype(float)),
```

In `measure_folder`, after the `angles = [...]` line, add:

```python
    pooled_angle, pooled_n = float("nan"), 0
    if POOLED_FIT:
        px = np.concatenate([r["raw_roi"][0] for _, _, r in measured])
        pu = np.concatenate([r["raw_roi"][1] for _, _, r in measured])
        pl = np.concatenate([r["raw_roi"][2] for _, _, r in measured])
        if px.size >= MIN_POINTS:
            k_u, b_u, _, vx_u, vy_u = tls_fit(px, pu)
            k_l, b_l, _, vx_l, vy_l = tls_fit(px, pl)
            if blue_dir is not None:
                pooled_angle = max(line_angle_deg(blue_dir, (vx_u, vy_u)),
                                   line_angle_deg(blue_dir, (vx_l, vy_l)))
            else:
                pooled_angle = spray_angle(k_u, k_l)
            pooled_n = int(px.size)
```

(Place it AFTER pass 2 so `blue_dir` is in scope; it already is — it's computed at the top of pass 2.) CSV summary row (next to the `trusted_mean` row, matching its comma count):

```python
        fh.write(f"pooled_angle,{pooled_angle:.2f},,,{pooled_n},,,,,,,,,"
                 f"all-frame fit\n")
```

Return dict: add `"pooled_angle": pooled_angle, "pooled_n": pooled_n`.

- [ ] **Step 4: Run** — new test PASS; full suite green.

- [ ] **Step 5: Commit**

```bash
git add hsc/measure_angle.py tests/test_pooled_fit.py
git commit -m "feat: temporal pooled edge fit across measured frames (POOLED_FIT)"
```

---

### Task 7 (OPTIONAL): Real-frame annotation tool

Skip unless the user wants hand-labeled real-frame scoring now. Complete tool; the labeling itself is a user action.

**Files:** Create: `benchmark/annotate_frames.py`

- [ ] **Step 1: Implement**

```python
"""Hand-mark true edges on real frames -> ground-truth JSON for the benchmark.

Usage: uv run python -m benchmark.annotate_frames "data\\injection images\\<run>\\frame_XXXX.bmp"
Left-click points along the UPPER edge, press SPACE, click the LOWER edge,
press SPACE again. Writes <frame>_truth.json with least-squares line params
in the same {"k_up","b_up","k_lo","b_lo","x_lo","x_hi"} format score.py uses.
Press ESC to abort. Requires a desktop session (cv2.imshow).
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

def main(path):
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise SystemExit(f"cannot read {path}")
    disp = cv2.cvtColor(cv2.resize(img, None, fx=3, fy=3,
                                   interpolation=cv2.INTER_NEAREST),
                        cv2.COLOR_GRAY2BGR)
    clicks, stage = [[], []], [0]

    def on_mouse(event, x, y, flags, _):
        if event == cv2.EVENT_LBUTTONDOWN:
            clicks[stage[0]].append((x / 3.0, y / 3.0))
            cv2.circle(disp, (x, y), 3, (0, 0, 255) if stage[0] == 0
                       else (255, 0, 0), -1)

    cv2.namedWindow("annotate")
    cv2.setMouseCallback("annotate", on_mouse)
    while True:
        cv2.imshow("annotate", disp)
        key = cv2.waitKey(30) & 0xFF
        if key == 27:
            raise SystemExit("aborted")
        if key == ord(" "):
            if stage[0] == 0 and len(clicks[0]) >= 2:
                stage[0] = 1
            elif stage[0] == 1 and len(clicks[1]) >= 2:
                break
    cv2.destroyAllWindows()
    truth = {}
    for name, pts in (("up", clicks[0]), ("lo", clicks[1])):
        xs = np.array([p[0] for p in pts]); ys = np.array([p[1] for p in pts])
        k, b = np.polyfit(xs, ys, 1)
        truth[f"k_{name}"], truth[f"b_{name}"] = float(k), float(b)
    allx = [p[0] for p in clicks[0] + clicks[1]]
    truth["x_lo"], truth["x_hi"] = float(min(allx)), float(max(allx))
    out = Path(path).with_name(Path(path).stem + "_truth.json")
    out.write_text(json.dumps(truth, indent=2))
    print(f"wrote {out}")

if __name__ == "__main__":
    main(sys.argv[1])
```

- [ ] **Step 2:** Smoke-test only that it imports (`uv run python -c "import benchmark.annotate_frames"`) — the interactive window needs the user. Commit: `git add benchmark/annotate_frames.py && git commit -m "feat: real-frame edge annotation tool for the benchmark"`.

---

### Task 8: Benchmark gate — flip the defaults, update docs

**Files:** Modify: `hsc/measure_angle.py` (flag defaults), `CLAUDE.md`, `README.md`

- [ ] **Step 1: Full benchmark with everything on**

`uv run python -c "from hsc import measure_angle as ma; ma.EDGE_MODEL='erf'; ma.BG_MODE='pre-onset'; ma.ANGLE_POLICY='trusted'; from benchmark.run_benchmark import run; run('candidate')"`

**Gate (all must hold vs `benchmark/baseline.csv`):**
1. `skirt_heavy`, `worst`, `faint`, `seq_residual`: mean ang_err strictly improved.
2. `sharp`, `blurry`, `noisy`, `thin_narrow`, `seq_clean`: within +0.05° of baseline.
3. Full pytest suite green; perf test green.

If any gate fails: do NOT flip that flag's default; record the numbers in the plan-completion report and stop for the user's decision — the flags still allow opt-in use.

- [ ] **Step 2: Flip defaults** — `EDGE_MODEL = "erf"`, `BG_MODE = "pre-onset"`, `ANGLE_POLICY = "trusted"` (each only if its gate passed; `POOLED_FIT` already defaults True).

- [ ] **Step 3: Real-data regression** — run on an actual rig capture: `uv run python -m hsc.measure_angle "data\injection images\<glob the first run>" --start 10 --end 20`; open two annotated frames and visually confirm the green lines sit on BOTH jet edges; compare mean/std vs a pre-change run of the same folder (re-run with `EDGE_MODEL="legacy"` via a one-liner for the comparison). The angle may legitimately shift a little (that's the fix); flag any shift > 0.3° to the user rather than assuming.

- [ ] **Step 4: Update docs**
- `CLAUDE.md` → measure_angle pipeline section: add 4–6 lines describing the erf per-side locus (third candidate in the straightness contest), pre-onset background via `injection_meta.json` (legacy median as fallback), per-edge confidence + `ANGLE_POLICY="trusted"`, pooled fit; note the new flags and that `"legacy"`/`"window"`/`"max"` restore the old behavior exactly. Extend "How to verify changes" with: `uv run python -m benchmark.run_benchmark <tag>` compared against `benchmark/baseline.csv`.
- `README.md` → "How it works §3": one sentence on the per-side step-model edges and the pooled angle row in `angles.csv`.

- [ ] **Step 5: Final verification + commit**

`uv run python -m pytest -q` (all green) and the source selftest:
`FOLDER=$(ls -d "data/injection images"/*/ | head -1); uv run python run_gui.py --selftest "$FOLDER"` → exit 0.

```bash
git add -A
git commit -m "feat: enable erf edge model, pre-onset background and trusted-edge policy by default"
```

---

## Explicitly out of scope (needs a follow-up plan only if the benchmark shows the above plateaus)

- Oriented/elongated derivative-of-Gaussian gradient (SNR gain for very faint edges).
- Joint wedge fit with a soft apex prior at the nozzle tip.
- Dynamic-programming edge tracking / Radon global line fit.
- Any learned detector.
- Rebuilding the frozen exe (do after merge, via `packaging\build_exe.bat` + frozen selftest, as one step).

## Final acceptance checklist

1. `uv run python -m pytest -q` → all green (expect ~38 tests).
2. `benchmark/results/candidate.csv` beats `benchmark/baseline.csv` per the Task 8 gate; both referenced in the final commit message.
3. Real-run visual check (Task 8 Step 3) confirmed by the user on frames that previously showed the one-edge-bad failure.
4. Legacy escape hatch verified: setting the three flags back to `"legacy"`/`"window"`/`"max"` reproduces today's numbers on the benchmark.
