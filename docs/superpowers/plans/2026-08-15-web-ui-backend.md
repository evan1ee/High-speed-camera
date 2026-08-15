# Web UI Backend Implementation Plan (slices 0–2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Tkinter app's backend with a testable rig service exposed over HTTP and WebSocket, so a browser can drive the piston pipeline and read results from SQLite.

**Architecture:** Three new packages beneath the untouched analysis core. `hsc/hardware/` puts a protocol between the code and the vendor SDK so everything above it can run against a fake camera. `hsc/rig/` owns the single camera thread, the job pipeline, the control lease and the SQLite store, and imports no web framework. `hsc/api/` is a thin FastAPI translation layer over `hsc/rig/`.

**Tech Stack:** Python 3.13, uv, FastAPI, uvicorn, SQLite (stdlib `sqlite3`), pytest, pytest-asyncio, pytest-cov, httpx. Existing: numpy, opencv-python, scipy, scikit-learn, pillow.

## Global Constraints

- **Do not modify any module in `hsc/` outside `hsc/hardware/`, `hsc/rig/`, `hsc/api/`.** The analysis modules are validated against rig data from 4 U to 40 U on two injectors. If a change there seems necessary, stop and ask. The single exception is **Task 16**, which deletes the Tk layer (`hsc/gui/`, `hsc/capture_gui.py`, `hsc/calibrate_ui.py`, `hsc/reference_ui.py`) — deletion of the UI layer, never an edit to an analysis module. Tasks 1–15 modify nothing in `hsc/` outside the three new packages.
- **`hsc/rig/` must not import `fastapi`, `starlette`, `uvicorn`, or `hsc.api`.** Enforced by a test.
- **`hsc/hardware/imv.py` must contain no logic** — no `if`, `for`, `while`, comprehension, or arithmetic. Enforced by a test. It is the only file excluded from coverage.
- **Coverage: 100%** for `hsc/hardware/`, `hsc/rig/`, `hsc/api/`, enforced with `--cov-fail-under=100`.
- **The whole suite runs with no camera attached and no server started.**
- Run commands with `uv run` from the repo root. Windows paths; PowerShell.
- Existing suite must stay green: `uv run python -m pytest` (202 tests at plan time).
- Timestamps are recorded in **raw SDK ticks**; unit inference belongs to `measure_piston.resolve_timebase`. Never convert ticks in the rig layer.

---

## File Structure

| file | responsibility |
|---|---|
| `hsc/hardware/device.py` | `Frame`, `CaptureConfig`, `CameraDevice` protocol, `CameraError` |
| `hsc/hardware/fake.py` | `FakeCamera` — replays a burst folder, synthesises ids/timestamps |
| `hsc/hardware/imv.py` | real SDK adapter, pure delegation, coverage-excluded |
| `hsc/rig/store.py` | SQLite schema, `RunStore` (insert/query), settings |
| `hsc/rig/importer.py` | scan `data/measure/*` into `runs` |
| `hsc/rig/lease.py` | single-controller lease with TTL |
| `hsc/rig/events.py` | event dataclasses + in-process pub/sub |
| `hsc/rig/worker.py` | the one camera thread: preview + piston burst |
| `hsc/rig/jobs.py` | job registry, piston pipeline, phases, cancellation |
| `hsc/api/app.py` | FastAPI factory, CORS, SPA mount |
| `hsc/api/errors.py` | `RuntimeError` → typed code mapping |
| `hsc/api/routes_runs.py` | runs, csv, media, import, summary |
| `hsc/api/routes_control.py` | jobs, lease, settings, camera status |
| `hsc/api/ws_events.py` | JSON event socket |
| `hsc/api/ws_preview.py` | binary preview socket |

Tests mirror the structure under `tests/hardware/`, `tests/rig/`, `tests/api/`.

---

### Task 1: Hardware protocol and value types

**Files:**
- Create: `hsc/hardware/__init__.py`, `hsc/hardware/device.py`
- Test: `tests/hardware/__init__.py`, `tests/hardware/test_device.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Frame(width, height, block_id, timestamp, pixels)`, `CaptureConfig(width, height, exposure_us, pixel_format, center_roi, frame_rate)`, `CameraDevice` protocol, `CameraError`.

- [ ] **Step 1: Write the failing test**

```python
# tests/hardware/test_device.py
"""The value types the rig layer passes around, independent of any SDK."""
import numpy as np
import pytest

from hsc.hardware.device import CameraConfigError, CaptureConfig, Frame


def test_frame_exposes_size_and_timing():
    pixels = np.zeros((4, 8), dtype=np.uint8)
    frame = Frame(width=8, height=4, block_id=7, timestamp=1234, pixels=pixels)
    assert (frame.width, frame.height) == (8, 4)
    assert frame.block_id == 7
    assert frame.timestamp == 1234
    assert frame.shape == (4, 8)


def test_frame_is_immutable():
    frame = Frame(8, 4, 0, 0, np.zeros((4, 8), dtype=np.uint8))
    with pytest.raises(AttributeError):
        frame.width = 9


def test_capture_config_rejects_a_size_the_sensor_cannot_produce():
    """Width and height must follow the camera's 4 px increment; a request the
    sensor silently rounds is how a burst ends up a different size than the
    calibration it will be measured against."""
    with pytest.raises(CameraConfigError, match="multiple of 4"):
        CaptureConfig(width=321, height=120, exposure_us=500.0)


def test_capture_config_rejects_a_non_positive_exposure():
    with pytest.raises(CameraConfigError, match="exposure"):
        CaptureConfig(width=320, height=120, exposure_us=0.0)


def test_capture_config_defaults_match_the_rig():
    cfg = CaptureConfig(width=320, height=120, exposure_us=500.0)
    assert cfg.pixel_format == "Mono8"
    assert cfg.center_roi is True
    assert cfg.frame_rate is None      # the camera free-runs; see CLAUDE.md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/hardware/test_device.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hsc.hardware'`

- [ ] **Step 3: Write minimal implementation**

```python
# hsc/hardware/__init__.py
"""Hardware seam: everything above this package runs against a fake camera."""
```

```python
# hsc/hardware/device.py
#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""The boundary between the rig code and the vendor SDK.

Everything above this module is tested against :class:`~hsc.hardware.fake.
FakeCamera`; the only implementation that touches the DLL is
:mod:`hsc.hardware.imv`, which holds no logic and is excluded from coverage.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np


class CameraError(RuntimeError):
    """The camera or SDK refused an operation."""


class CameraConfigError(CameraError):
    """A capture configuration the sensor cannot honour."""


#: The sensor's ROI increment. A request off this grid is silently rounded by
#: the camera, which would produce a burst of a different size than the
#: calibration it is measured against.
ROI_INCREMENT = 4


@dataclass(frozen=True)
class Frame:
    """One grabbed frame.

    ``block_id`` and ``timestamp`` are carried because the entire speed axis
    depends on them: the camera free-runs, ``AcquisitionFrameRate`` reports a
    stale stored value, and gaps in ``block_id`` are the only evidence of a
    dropped frame. ``timestamp`` is in RAW SDK TICKS -- the unit is inferred
    later by ``measure_piston.resolve_timebase``; never convert it here.
    """

    width: int
    height: int
    block_id: int
    timestamp: int
    pixels: np.ndarray

    @property
    def shape(self):
        return (self.height, self.width)


@dataclass(frozen=True)
class CaptureConfig:
    """What to program onto the camera before grabbing."""

    width: int
    height: int
    exposure_us: float
    pixel_format: str = "Mono8"
    center_roi: bool = True
    frame_rate: float | None = None      # None: free-run at the sensor maximum

    def __post_init__(self):
        for name in ("width", "height"):
            value = getattr(self, name)
            if value <= 0 or value % ROI_INCREMENT:
                raise CameraConfigError(
                    f"{name} must be a positive multiple of {ROI_INCREMENT}, "
                    f"got {value}")
        if self.exposure_us <= 0:
            raise CameraConfigError(
                f"exposure must be positive, got {self.exposure_us}")


@runtime_checkable
class CameraDevice(Protocol):
    """The camera operations the rig needs. See fake.py for the reference."""

    def open(self, index: int) -> None: ...
    def configure(self, cfg: CaptureConfig) -> None: ...
    def start(self) -> None: ...
    def grab(self, timeout_ms: int) -> Frame | None: ...
    def clone(self, frame: Frame) -> Frame: ...
    def release(self, frame: Frame) -> None: ...
    def save(self, frame: Frame, path: Path) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/hardware/test_device.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add hsc/hardware tests/hardware
git commit -m "feat: camera device protocol and value types"
```

---

### Task 2: FakeCamera

**Files:**
- Create: `hsc/hardware/fake.py`
- Create: `tests/fixtures/burst_320x120/` (12 BMP frames, see Step 0)
- Test: `tests/hardware/test_fake.py`

**Interfaces:**
- Consumes: `Frame`, `CaptureConfig`, `CameraError` from Task 1.
- Produces: `FakeCamera(source_dir, fps=1738.7, drop_after=None, roi_override=None)` implementing `CameraDevice`, plus `FakeCamera.saved` (list of paths written) and `FakeCamera.configs` (list of `CaptureConfig` programmed, in order).

- [ ] **Step 0: Create the fixture burst**

The fake replays real rig pixels so tests exercise true content. Copy 12 consecutive frames from an existing run:

```powershell
$src = "data\injection images\piston_2026-08-13-10-32-48_320x120"
$dst = "tests\fixtures\burst_320x120"
New-Item -ItemType Directory -Force $dst | Out-Null
Get-ChildItem $src -Filter *.bmp | Select-Object -First 12 |
    Copy-Item -Destination $dst
```

Verify: `(Get-ChildItem tests\fixtures\burst_320x120 -Filter *.bmp).Count` → 12

- [ ] **Step 1: Write the failing test**

```python
# tests/hardware/test_fake.py
"""FakeCamera replays a real burst, so tests above the seam run on rig pixels."""
from pathlib import Path

import numpy as np
import pytest

from hsc.hardware.device import CaptureConfig, CameraError
from hsc.hardware.fake import FakeCamera

BURST = Path(__file__).resolve().parents[1] / "fixtures" / "burst_320x120"
CFG = CaptureConfig(width=320, height=120, exposure_us=500.0)


def _started(**kwargs):
    cam = FakeCamera(BURST, **kwargs)
    cam.open(1)
    cam.configure(CFG)
    cam.start()
    return cam


def test_grab_returns_frames_in_order_with_real_pixels():
    cam = _started()
    first = cam.grab(1000)
    second = cam.grab(1000)
    assert first.shape == (120, 320)
    assert first.pixels.dtype == np.uint8
    assert first.pixels.max() > 200      # the bright barrel is really there
    assert not np.array_equal(first.pixels, second.pixels)


def test_block_ids_are_consecutive_and_timestamps_advance_at_the_given_fps():
    cam = _started(fps=1000.0)
    frames = [cam.grab(1000) for _ in range(3)]
    assert [f.block_id for f in frames] == [1, 2, 3]
    deltas = np.diff([f.timestamp for f in frames])
    assert set(deltas) == {1_000_000}    # 1 ms in nanosecond ticks


def test_dropped_frames_show_as_a_block_id_gap():
    """A dropped frame is invisible in the pixels; only blockId reveals it."""
    cam = _started(drop_after=2)
    ids = [cam.grab(1000).block_id for _ in range(4)]
    assert ids == [1, 2, 4, 5]


def test_grab_returns_none_when_the_burst_is_exhausted():
    cam = _started()
    for _ in range(12):
        assert cam.grab(1000) is not None
    assert cam.grab(1000) is None


def test_roi_override_lets_a_test_reproduce_the_wrong_size_burst():
    """Run 2026-08-13-09-18-35 delivered correctly-shaped frames at the wrong
    frame period. The guard that catches a size mismatch needs a camera that
    can lie about its size."""
    cam = _started(roi_override=(320, 240))
    frame = cam.grab(1000)
    assert (frame.width, frame.height) == (320, 240)


def test_configure_is_recorded_so_the_pre_burst_reprogram_can_be_asserted():
    cam = FakeCamera(BURST)
    cam.open(1)
    cam.configure(CFG)
    cam.start()
    cam.stop()
    cam.configure(CaptureConfig(320, 240, 500.0))
    cam.start()
    assert [(c.width, c.height) for c in cam.configs] == [(320, 120), (320, 240)]


def test_save_writes_a_byte_identical_copy_of_the_source_frame():
    cam = _started()
    frame = cam.grab(1000)
    out = BURST.parent / "tmp_saved.bmp"
    try:
        cam.save(frame, out)
        assert out.read_bytes() == sorted(BURST.glob("*.bmp"))[0].read_bytes()
        assert cam.saved == [out]
    finally:
        out.unlink(missing_ok=True)


def test_clone_survives_release_of_the_original():
    cam = _started()
    frame = cam.grab(1000)
    clone = cam.clone(frame)
    original = frame.pixels.copy()
    cam.release(frame)
    assert np.array_equal(clone.pixels, original)


def test_grab_before_start_is_an_error():
    cam = FakeCamera(BURST)
    cam.open(1)
    cam.configure(CFG)
    with pytest.raises(CameraError, match="not grabbing"):
        cam.grab(1000)


def test_open_rejects_a_folder_with_no_frames(tmp_path):
    with pytest.raises(CameraError, match="no frames"):
        FakeCamera(tmp_path).open(1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/hardware/test_fake.py -v`
Expected: FAIL — `No module named 'hsc.hardware.fake'`

- [ ] **Step 3: Write minimal implementation**

```python
# hsc/hardware/fake.py
#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""A camera that replays a saved burst.

Every test above the hardware seam runs against this, on REAL rig pixels --
the same data that exposed the collar, the illumination falloff and the small
dose drift. That matters more than it sounds: a synthetic gradient would have
passed detectors that the actual frames break.

It can also misbehave on purpose, because the rig's failures are what need
covering: dropped frames (a ``block_id`` gap), and a camera streaming a
different ROI than was programmed.
"""

import shutil
from pathlib import Path

import numpy as np

from hsc import injection_extract
from hsc.hardware.device import CameraError, CaptureConfig, Frame

#: Nanoseconds, matching the SDK ticks the rig records (measured 2026-08-07:
#: 954320 ticks between frames at 1047.9 fps).
TICKS_PER_SECOND = 1_000_000_000


class FakeCamera:
    """Replays *source_dir* frame by frame. See module docstring."""

    def __init__(self, source_dir, fps=1738.7, drop_after=None,
                 roi_override=None):
        self._source = Path(source_dir)
        self._fps = float(fps)
        self._drop_after = drop_after
        self._roi_override = roi_override
        self._files = []
        self._index = 0
        self._block = 0
        self._grabbing = False
        self._open = False
        self.configs = []
        self.saved = []

    # -- lifecycle ---------------------------------------------------------
    def open(self, index):
        self._files = injection_extract.list_frames(self._source)
        if not self._files:
            raise CameraError(f"no frames to replay in {self._source}")
        self._open = True

    def configure(self, cfg):
        if not isinstance(cfg, CaptureConfig):
            raise CameraError("configure needs a CaptureConfig")
        self.configs.append(cfg)

    def start(self):
        self._grabbing = True

    def stop(self):
        self._grabbing = False

    def close(self):
        self._grabbing = False
        self._open = False

    # -- frames ------------------------------------------------------------
    def grab(self, timeout_ms):
        if not self._grabbing:
            raise CameraError("camera is not grabbing")
        if self._index >= len(self._files):
            return None
        path = self._files[self._index]
        self._index += 1
        self._block += 1
        if self._drop_after is not None and self._block == self._drop_after + 1:
            self._block += 1                     # the gap a dropped frame leaves
        pixels = load_gray(path)   # from hsc.measure_angle, NOT injection_extract
        height, width = pixels.shape
        if self._roi_override is not None:
            width, height = self._roi_override
        ticks = int(round((self._block - 1) * TICKS_PER_SECOND / self._fps))
        frame = Frame(width=width, height=height, block_id=self._block,
                      timestamp=ticks, pixels=pixels)
        self._sources = getattr(self, "_sources", {})
        self._sources[id(frame)] = path
        return frame

    def clone(self, frame):
        clone = Frame(frame.width, frame.height, frame.block_id,
                      frame.timestamp, frame.pixels.copy())
        self._sources[id(clone)] = self._sources[id(frame)]
        return clone

    def release(self, frame):
        self._sources.pop(id(frame), None)

    def save(self, frame, path):
        source = self._sources.get(id(frame))
        if source is None:
            raise CameraError("frame was released before saving")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, path)
        self.saved.append(Path(path))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/hardware/test_fake.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add hsc/hardware/fake.py tests/hardware/test_fake.py tests/fixtures
git commit -m "feat: FakeCamera replaying a real burst, with drop and ROI faults"
```

---

### Task 3: Real SDK adapter and the honest exclusion

**Files:**
- Create: `hsc/hardware/imv.py`
- Modify: `pyproject.toml` (coverage config)
- Test: `tests/hardware/test_imv_has_no_logic.py`

**Interfaces:**
- Consumes: `Frame`, `CaptureConfig`, `CameraError`, and existing `hsc.capture_image` helpers (`load_sdk`, `check`, `configure_camera`, `save_frame`, `save_type_for`).
- Produces: `ImvCamera()` implementing `CameraDevice`.

- [ ] **Step 1: Write the failing test**

```python
# tests/hardware/test_imv_has_no_logic.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/hardware/test_imv_has_no_logic.py -v`
Expected: FAIL — `No module named 'hsc.hardware.imv'`

- [ ] **Step 3: Write minimal implementation**

Note the constraint this creates: because no `if` is permitted, every decision
(is it grabbing? did the size change?) lives in `hsc/rig/worker.py`.

```python
# hsc/hardware/imv.py
#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""The real camera, via the IMV SDK.

EXCLUDED FROM COVERAGE -- it cannot run without hardware. In exchange it holds
NO logic: no branching, no computation, only delegation. A test parses this
file and fails if that stops being true, so anything that could be wrong is
somewhere it can be tested.
"""

from ctypes import byref, c_void_p, string_at
from types import SimpleNamespace

import numpy as np

from hsc import capture_image
from hsc.hardware.device import CameraError, Frame


class ImvCamera:
    """See module docstring. Every method is one SDK call plus a check."""

    def __init__(self):
        self._sdk = capture_image.load_sdk()
        self._cam = None

    def open(self, index):
        self._cam = self._sdk["MvCamera"]()
        capture_image.check(
            self._cam.IMV_CreateHandle(
                self._sdk["IMV_ECreateHandleMode"].modeByIndex,
                byref(c_void_p(index - 1))),
            self._sdk["IMV_OK"], "Create camera handle")
        capture_image.check(self._cam.IMV_Open(), self._sdk["IMV_OK"],
                            "Open camera")

    def configure(self, cfg):
        capture_image.configure_camera(self._cam, self._sdk, SimpleNamespace(
            pixel_format=cfg.pixel_format, width=cfg.width, height=cfg.height,
            center_roi=cfg.center_roi, offset_x=None, offset_y=None,
            exposure_us=cfg.exposure_us, frame_rate=cfg.frame_rate))

    def start(self):
        capture_image.check(self._cam.IMV_StartGrabbing(),
                            self._sdk["IMV_OK"], "Start grabbing")

    def grab(self, timeout_ms):
        raw = self._sdk["IMV_Frame"]()
        return self._wrap(raw, self._cam.IMV_GetFrame(raw, timeout_ms))

    def _wrap(self, raw, status):
        return _FRAME_BY_STATUS[status == self._sdk["IMV_OK"]](self._sdk, raw)

    def clone(self, frame):
        raw = self._sdk["IMV_Frame"]()
        capture_image.check(self._cam.IMV_CloneFrame(frame.handle, raw),
                            self._sdk["IMV_OK"], "Clone frame")
        return _to_frame(self._sdk, raw)

    def release(self, frame):
        self._cam.IMV_ReleaseFrame(frame.handle)

    def save(self, frame, path):
        capture_image.save_frame(self._cam, frame.handle, path, self._sdk)

    def stop(self):
        self._cam.IMV_StopGrabbing()

    def close(self):
        self._cam.IMV_Close()
        self._cam.IMV_DestroyHandle()


def _to_frame(sdk, raw):
    info = raw.frameInfo
    return _ImvFrame(
        width=info.width, height=info.height, block_id=info.blockId,
        timestamp=info.timeStamp, handle=raw,
        pixels=np.frombuffer(
            string_at(raw.pData, info.width * info.height),
            dtype=np.uint8).reshape(info.height, info.width))


def _to_none(sdk, raw):
    return None


_FRAME_BY_STATUS = {True: _to_frame, False: _to_none}


class _ImvFrame(Frame):
    """A Frame that also carries the SDK handle for release/clone/save."""

    def __init__(self, width, height, block_id, timestamp, pixels, handle):
        object.__setattr__(self, "handle", handle)
        super().__init__(width, height, block_id, timestamp, pixels)
```

Add to `pyproject.toml`:

```toml
[tool.coverage.run]
source = ["hsc/hardware", "hsc/rig", "hsc/api"]
omit = ["hsc/hardware/imv.py"]

[tool.coverage.report]
fail_under = 100
show_missing = true
```

Add dev dependencies:

```bash
uv add --dev pytest-cov pytest-asyncio
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/hardware/ -v`
Expected: all pass. If `test_adapter_contains_no_branching_or_computation` fails, the offending construct must move into `hsc/rig/` — do not weaken the test.

- [ ] **Step 5: Commit**

```bash
git add hsc/hardware/imv.py tests/hardware/test_imv_has_no_logic.py pyproject.toml
git commit -m "feat: IMV adapter with a structural no-logic guard"
```

---

### Task 4: SQLite store

**Files:**
- Create: `hsc/rig/__init__.py`, `hsc/rig/store.py`
- Test: `tests/rig/__init__.py`, `tests/rig/test_store.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `RunStore(db_path)` with `add_run(RunRecord) -> int`, `get_run(id) -> RunRecord | None`, `list_runs(kind=None, label=None, limit=100) -> list[RunRecord]`, `run_by_measure_dir(path) -> RunRecord | None`, `set_setting(key, value)`, `get_settings() -> dict`; dataclass `RunRecord` with fields listed below.

- [ ] **Step 1: Write the failing test**

```python
# tests/rig/test_store.py
"""SQLite holds one row per measured run; per-frame data stays in the CSV."""
import pytest

from hsc.rig.store import RunRecord, RunStore


def _record(**over):
    base = dict(
        label="IN37-30U", kind="piston", captured_at="2026-08-14T14:28:09",
        source_dir=r"data\captures\piston_x", injection_dir=r"data\injection images\piston_x",
        measure_dir=r"data\measure\piston_x", roi="320x120", fps=1738.77,
        exposure_us=500.0, timebase="timestamps (ns)", mm_per_px=0.059385,
        scale_source="calibration.json", barrel_mm=6.12, orifice_mm=0.155,
        density=1000.0, stroke_px=172.6, stroke_mm=10.254, duration_ms=112.1,
        mean_speed_mm_s=91.5, peak_speed_mm_s=194.0,
        peak_jet_speed_m_s=302.4, peak_jet_pressure_MPa=45.7,
        unstable_frames=1, measured_count=268)
    base.update(over)
    return RunRecord(**base)


def test_add_and_get_round_trip(tmp_path):
    store = RunStore(tmp_path / "rig.db")
    run_id = store.add_run(_record())
    got = store.get_run(run_id)
    assert got.label == "IN37-30U"
    assert got.stroke_mm == pytest.approx(10.254)
    assert got.id == run_id


def test_get_returns_none_for_an_unknown_id(tmp_path):
    assert RunStore(tmp_path / "rig.db").get_run(999) is None


def test_list_is_newest_first_and_filterable(tmp_path):
    store = RunStore(tmp_path / "rig.db")
    store.add_run(_record(captured_at="2026-08-14T10:00:00", label="A"))
    store.add_run(_record(captured_at="2026-08-14T14:00:00", label="B"))
    store.add_run(_record(captured_at="2026-08-14T12:00:00", label="C",
                          kind="spray"))
    assert [r.label for r in store.list_runs()] == ["B", "C", "A"]
    assert [r.label for r in store.list_runs(kind="piston")] == ["B", "A"]
    assert [r.label for r in store.list_runs(label="A")] == ["A"]
    assert len(store.list_runs(limit=1)) == 1


def test_measure_dir_is_unique_so_import_is_idempotent(tmp_path):
    """The importer re-scans folders on every start; a run must not double."""
    store = RunStore(tmp_path / "rig.db")
    store.add_run(_record(measure_dir=r"data\measure\same"))
    store.add_run(_record(measure_dir=r"data\measure\same", stroke_mm=99.0))
    runs = store.list_runs()
    assert len(runs) == 1
    assert runs[0].stroke_mm == pytest.approx(99.0)   # upsert, latest wins


def test_optional_metrics_may_be_missing(tmp_path):
    """Runs measured before the jet columns existed still import."""
    store = RunStore(tmp_path / "rig.db")
    run_id = store.add_run(_record(peak_jet_speed_m_s=None,
                                   peak_jet_pressure_MPa=None))
    got = store.get_run(run_id)
    assert got.peak_jet_speed_m_s is None


def test_settings_round_trip(tmp_path):
    store = RunStore(tmp_path / "rig.db")
    store.set_setting("roi", "320x120")
    store.set_setting("exposure_us", "500")
    store.set_setting("roi", "320x240")
    assert store.get_settings() == {"roi": "320x240", "exposure_us": "500"}


def test_schema_survives_reopening(tmp_path):
    path = tmp_path / "rig.db"
    RunStore(path).add_run(_record())
    assert len(RunStore(path).list_runs()) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/rig/test_store.py -v`
Expected: FAIL — `No module named 'hsc.rig'`

- [ ] **Step 3: Write minimal implementation**

```python
# hsc/rig/__init__.py
"""Rig service: camera worker, jobs, lease, persistence. No web framework here."""
```

```python
# hsc/rig/store.py
#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""SQLite persistence for measured runs, jobs and rig settings.

Summary metrics only: the per-frame series stays in the CSV each run already
writes, which is why importing the existing folders needs no translation --
``hsc.summary.read_run`` already parses exactly these fields.

``measure_dir`` is UNIQUE and inserts upsert on it, because the importer
re-scans on every start and a run must not appear twice.
"""

import sqlite3
from dataclasses import asdict, dataclass, fields
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT, kind TEXT NOT NULL, captured_at TEXT NOT NULL,
    source_dir TEXT, injection_dir TEXT, measure_dir TEXT NOT NULL UNIQUE,
    roi TEXT, fps REAL, exposure_us REAL, timebase TEXT,
    mm_per_px REAL, scale_source TEXT,
    barrel_mm REAL, orifice_mm REAL, density REAL,
    stroke_px REAL, stroke_mm REAL, duration_ms REAL,
    mean_speed_mm_s REAL, peak_speed_mm_s REAL,
    peak_jet_speed_m_s REAL, peak_jet_pressure_MPa REAL,
    unstable_frames INTEGER, measured_count INTEGER
);
CREATE INDEX IF NOT EXISTS runs_captured_at ON runs (captured_at DESC);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


@dataclass
class RunRecord:
    kind: str
    captured_at: str
    measure_dir: str
    label: str | None = None
    source_dir: str | None = None
    injection_dir: str | None = None
    roi: str | None = None
    fps: float | None = None
    exposure_us: float | None = None
    timebase: str | None = None
    mm_per_px: float | None = None
    scale_source: str | None = None
    barrel_mm: float | None = None
    orifice_mm: float | None = None
    density: float | None = None
    stroke_px: float | None = None
    stroke_mm: float | None = None
    duration_ms: float | None = None
    mean_speed_mm_s: float | None = None
    peak_speed_mm_s: float | None = None
    peak_jet_speed_m_s: float | None = None
    peak_jet_pressure_MPa: float | None = None
    unstable_frames: int | None = None
    measured_count: int | None = None
    id: int | None = None


_COLUMNS = [f.name for f in fields(RunRecord) if f.name != "id"]


class RunStore:
    """Opens (and creates) the database at *db_path*."""

    def __init__(self, db_path):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self):
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def add_run(self, record):
        payload = {name: getattr(record, name) for name in _COLUMNS}
        placeholders = ", ".join(f":{name}" for name in _COLUMNS)
        updates = ", ".join(f"{name}=excluded.{name}" for name in _COLUMNS)
        with self._connect() as conn:
            cur = conn.execute(
                f"INSERT INTO runs ({', '.join(_COLUMNS)}) "
                f"VALUES ({placeholders}) "
                f"ON CONFLICT(measure_dir) DO UPDATE SET {updates}", payload)
            row = conn.execute(
                "SELECT id FROM runs WHERE measure_dir = ?",
                (record.measure_dir,)).fetchone()
        return int(row["id"])

    def get_run(self, run_id):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?",
                               (run_id,)).fetchone()
        return self._record(row)

    def run_by_measure_dir(self, measure_dir):
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE measure_dir = ?",
                               (str(measure_dir),)).fetchone()
        return self._record(row)

    def list_runs(self, kind=None, label=None, limit=100):
        clauses, params = [], []
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if label is not None:
            clauses.append("label = ?")
            params.append(label)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM runs {where} ORDER BY captured_at DESC "
                f"LIMIT ?", params).fetchall()
        return [self._record(row) for row in rows]

    def set_setting(self, key, value):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)))

    def get_settings(self):
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {row["key"]: row["value"] for row in rows}

    @staticmethod
    def _record(row):
        return RunRecord(**dict(row)) if row is not None else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/rig/test_store.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add hsc/rig tests/rig
git commit -m "feat: SQLite run store with idempotent upsert on measure_dir"
```

---

### Task 5: Importer over existing run folders

**Files:**
- Create: `hsc/rig/importer.py`
- Test: `tests/rig/test_importer.py`

**Interfaces:**
- Consumes: `RunStore`, `RunRecord` (Task 4); `hsc.summary.read_run`, `hsc.summary.find_csv`.
- Produces: `import_measure_root(measure_root, store) -> ImportResult(imported, skipped)` where `skipped` is `list[tuple[str, str]]` of `(folder_name, reason)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/rig/test_importer.py
"""Existing run folders import without translation: hsc.summary already parses
exactly the summary block the store keeps."""
import json

from hsc.rig.importer import import_measure_root
from hsc.rig.store import RunStore

CSV = """frame,time_ms,x_px,distance_px,distance_mm,speed_mm_s,speed_m_s,k,n_points,rms_px,coverage,at_border,stable
frame_000001.bmp,0.000,117.0,0.000,0.0000,0.00,0.0000,-0.02,50,0.30,1.000,no,yes
frame_000002.bmp,0.575,117.6,0.600,0.0356,62.00,0.0620,-0.02,50,0.30,1.000,no,yes

unstable_frames,1
stroke_px,172.600
stroke_mm,10.2540
duration_ms,112.1000
mean_speed_mm_s,91.5000
peak_speed_mm_s,194.0000
peak_jet_speed_m_s,302.4000
peak_jet_pressure_MPa,45.7000
barrel_mm,6.1200
orifice_mm,0.1550
area_ratio,1558.9761
fluid_density,1000.0000
mm_per_px,0.0594
scale_source,calibration.json
fps,1738.7676
timebase,timestamps (ns)
reference_frame,frame_000001.bmp
"""


def _run_folder(root, name, csv=CSV, meta=True):
    folder = root / name
    folder.mkdir(parents=True)
    (folder / f"{name}_speed.csv").write_text(csv, encoding="utf-8")
    if meta:
        (folder / "piston_meta.json").write_text(
            json.dumps({"fps": 1738.7676, "pre_frames": 30}), encoding="utf-8")
    return folder


def test_imports_a_measured_run(tmp_path):
    root = tmp_path / "measure"
    _run_folder(root, "piston_2026-08-14-14-28-09_320x120_IN37-30U")
    store = RunStore(tmp_path / "rig.db")

    result = import_measure_root(root, store)

    assert result.imported == 1
    run = store.list_runs()[0]
    assert run.kind == "piston"
    assert run.label == "IN37-30U"
    assert run.roi == "320x120"
    assert run.stroke_mm == 10.254
    assert run.peak_jet_pressure_MPa == 45.7
    assert run.fps == 1738.7676
    assert run.timebase == "timestamps (ns)"


def test_is_idempotent(tmp_path):
    root = tmp_path / "measure"
    _run_folder(root, "piston_2026-08-14-14-28-09_320x120_IN37-30U")
    store = RunStore(tmp_path / "rig.db")
    import_measure_root(root, store)
    second = import_measure_root(root, store)
    assert second.imported == 1
    assert len(store.list_runs()) == 1


def test_folder_without_a_csv_is_skipped_with_a_reason(tmp_path):
    root = tmp_path / "measure"
    (root / "not_a_run").mkdir(parents=True)
    result = import_measure_root(root, RunStore(tmp_path / "rig.db"))
    assert result.imported == 0
    assert result.skipped == [("not_a_run", "no piston speed CSV")]


def test_run_measured_before_the_jet_columns_still_imports(tmp_path):
    root = tmp_path / "measure"
    older = "\n".join(line for line in CSV.splitlines()
                      if not line.startswith("peak_jet"))
    _run_folder(root, "piston_2026-08-01-10-00-00_320x240", csv=older)
    store = RunStore(tmp_path / "rig.db")
    assert import_measure_root(root, store).imported == 1
    run = store.list_runs()[0]
    assert run.stroke_mm == 10.254
    assert run.peak_jet_speed_m_s is None


def test_missing_measure_root_is_not_an_error(tmp_path):
    result = import_measure_root(tmp_path / "absent", RunStore(tmp_path / "d.db"))
    assert result.imported == 0 and result.skipped == []


def test_label_and_roi_are_parsed_from_the_folder_name(tmp_path):
    root = tmp_path / "measure"
    _run_folder(root, "piston_2026-08-14-10-27-10_320x120_IN38-4U")
    store = RunStore(tmp_path / "rig.db")
    import_measure_root(root, store)
    run = store.list_runs()[0]
    assert run.label == "IN38-4U"
    assert run.captured_at == "2026-08-14T10:27:10"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/rig/test_importer.py -v`
Expected: FAIL — `No module named 'hsc.rig.importer'`

- [ ] **Step 3: Write minimal implementation**

```python
# hsc/rig/importer.py
#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Bring existing run folders into the database.

Runs made before this service existed -- and any made by a CLI afterwards --
appear in the web UI because this scans the measure root and reads the summary
block each run already wrote. ``hsc.summary.read_run`` does the parsing, so
there is one implementation of "what a run's numbers are".

Idempotent: keyed on the measure folder, so it runs at every start.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from hsc import summary
from hsc.rig.store import RunRecord

#: piston_2026-08-14-14-28-09_320x120_IN37-30U
NAME = re.compile(
    r"^(?P<kind>piston|monitor)?_?"
    r"(?P<stamp>\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})"
    r"(?:_(?P<roi>\d+x\d+))?"
    r"(?:_(?P<label>.+))?$")


@dataclass
class ImportResult:
    imported: int = 0
    skipped: list = field(default_factory=list)


def parse_folder_name(name):
    """``(kind, captured_at, roi, label)`` from a run folder name."""
    match = NAME.match(name)
    if match is None:
        return "piston", None, None, None
    stamp = match.group("stamp")
    date, _, clock = stamp.partition("-")
    parts = stamp.split("-")
    captured = f"{parts[0]}-{parts[1]}-{parts[2]}T{parts[3]}:{parts[4]}:{parts[5]}"
    return (match.group("kind") or "piston", captured,
            match.group("roi"), match.group("label"))


def _meta(folder):
    for name in ("piston_meta.json", "injection_meta.json"):
        try:
            return json.loads((folder / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return {}


def import_measure_root(measure_root, store):
    """Scan *measure_root* for measured runs and upsert them into *store*."""
    result = ImportResult()
    root = Path(measure_root)
    if not root.exists():
        return result
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        if summary.find_csv(folder) is None:
            result.skipped.append((folder.name, "no piston speed CSV"))
            continue
        try:
            values = summary.read_run(folder)
        except (RuntimeError, OSError) as exc:
            result.skipped.append((folder.name, str(exc)))
            continue
        kind, captured_at, roi, label = parse_folder_name(folder.name)
        meta = _meta(folder)
        store.add_run(RunRecord(
            kind=kind, captured_at=captured_at or "", measure_dir=str(folder),
            label=label, roi=roi, fps=_number(values, meta, "fps"),
            timebase=_text(folder, "timebase"),
            mm_per_px=values.get("mm_per_px"),
            scale_source=_text(folder, "scale_source"),
            barrel_mm=values.get("barrel_mm"),
            orifice_mm=values.get("orifice_mm"),
            density=values.get("fluid_density"),
            stroke_px=values.get("stroke_px"),
            stroke_mm=values.get("stroke_mm"),
            duration_ms=values.get("duration_ms"),
            mean_speed_mm_s=values.get("mean_speed_mm_s"),
            peak_speed_mm_s=values.get("peak_speed_mm_s"),
            peak_jet_speed_m_s=values.get("peak_jet_speed_m_s"),
            peak_jet_pressure_MPa=values.get("peak_jet_pressure_MPa"),
            unstable_frames=_int(values.get("unstable_frames"))))
        result.imported += 1
    return result


def _number(values, meta, key):
    return values.get(key, meta.get(key))


def _int(value):
    return None if value is None else int(value)


def _text(folder, key):
    """Read a non-numeric summary line (timebase, scale_source) from the CSV."""
    csv_path = summary.find_csv(folder)
    for line in csv_path.read_text(encoding="utf-8").splitlines():
        name, _, rest = line.partition(",")
        if name == key:
            return rest.strip() or None
    return None
```

**Note for the implementer:** `summary.read_run` only returns keys listed in
`summary.METRICS` plus the numeric summary lines it can parse. If a needed key
(`barrel_mm`, `mm_per_px`, `fps`, `fluid_density`) is absent from its `KEYS`
tuple, do **not** edit `hsc/summary.py` — read those lines here with `_text`/a
numeric variant instead. Confirm by running:
`uv run python -c "from hsc import summary; print(summary.KEYS)"`

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/rig/test_importer.py -v`
Expected: 6 passed

- [ ] **Step 5: Verify against real data**

```powershell
uv run python -c "from pathlib import Path; from hsc.rig.store import RunStore; from hsc.rig.importer import import_measure_root; r = import_measure_root(Path('data/measure'), RunStore('data/rig.db')); print(r.imported, 'imported,', len(r.skipped), 'skipped')"
```
Expected: ~90 imported. Spot-check one row matches its CSV.

- [ ] **Step 6: Commit**

```bash
git add hsc/rig/importer.py tests/rig/test_importer.py
git commit -m "feat: import existing measure folders into the run store"
```

---

### Task 6: Control lease

**Files:**
- Create: `hsc/rig/lease.py`
- Test: `tests/rig/test_lease.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ControlLease(ttl_s=30.0, clock=time.monotonic)` with `claim(client_id) -> bool`, `release(client_id) -> bool`, `heartbeat(client_id) -> bool`, `holder -> str | None`, `require(client_id)` raising `LeaseError`, `handover(from_id, to_id) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/rig/test_lease.py
"""One controller, many observers. A stale browser tab must not keep the rig."""
import pytest

from hsc.rig.lease import ControlLease, LeaseError


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_first_claim_wins_and_second_is_refused():
    lease = ControlLease()
    assert lease.claim("a") is True
    assert lease.claim("b") is False
    assert lease.holder == "a"


def test_reclaim_by_the_holder_is_allowed():
    lease = ControlLease()
    lease.claim("a")
    assert lease.claim("a") is True


def test_release_frees_the_rig():
    lease = ControlLease()
    lease.claim("a")
    assert lease.release("a") is True
    assert lease.holder is None
    assert lease.claim("b") is True


def test_a_non_holder_cannot_release():
    lease = ControlLease()
    lease.claim("a")
    assert lease.release("b") is False
    assert lease.holder == "a"


def test_lease_expires_without_a_heartbeat():
    clock = Clock()
    lease = ControlLease(ttl_s=30.0, clock=clock)
    lease.claim("a")
    clock.now = 31.0
    assert lease.holder is None
    assert lease.claim("b") is True


def test_heartbeat_keeps_it():
    clock = Clock()
    lease = ControlLease(ttl_s=30.0, clock=clock)
    lease.claim("a")
    clock.now = 20.0
    assert lease.heartbeat("a") is True
    clock.now = 45.0
    assert lease.holder == "a"


def test_heartbeat_from_a_non_holder_is_refused():
    lease = ControlLease()
    lease.claim("a")
    assert lease.heartbeat("b") is False


def test_require_raises_for_a_non_holder():
    lease = ControlLease()
    lease.claim("a")
    with pytest.raises(LeaseError, match="held by a"):
        lease.require("b")
    lease.require("a")          # no raise


def test_require_raises_when_nobody_holds_it():
    with pytest.raises(LeaseError, match="no client holds"):
        ControlLease().require("a")


def test_handover_transfers_without_a_gap():
    lease = ControlLease()
    lease.claim("a")
    assert lease.handover("a", "b") is True
    assert lease.holder == "b"
    assert lease.handover("a", "c") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/rig/test_lease.py -v`
Expected: FAIL — `No module named 'hsc.rig.lease'`

- [ ] **Step 3: Write minimal implementation**

```python
# hsc/rig/lease.py
#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Single-controller lease over the rig.

The camera is one piece of hardware and a browser invites a second tab, so
control is explicit: one client holds it, everyone else observes. A holder that
goes away without releasing (closed laptop, dropped tailnet) must not lock the
rig, hence the TTL -- the client heartbeats while it wants control.

Lives in the rig layer, not the API layer, so it is testable without a server.
``clock`` is injectable for the same reason.
"""

import threading
import time


class LeaseError(RuntimeError):
    """A control command from a client that does not hold the lease."""


class ControlLease:
    def __init__(self, ttl_s=30.0, clock=time.monotonic):
        self._ttl = float(ttl_s)
        self._clock = clock
        self._holder = None
        self._expires = 0.0
        self._guard = threading.Lock()

    @property
    def holder(self):
        with self._guard:
            return self._live_holder()

    def _live_holder(self):
        if self._holder is not None and self._clock() >= self._expires:
            self._holder = None
        return self._holder

    def claim(self, client_id):
        with self._guard:
            current = self._live_holder()
            if current is not None and current != client_id:
                return False
            self._holder = client_id
            self._expires = self._clock() + self._ttl
            return True

    def release(self, client_id):
        with self._guard:
            if self._live_holder() != client_id:
                return False
            self._holder = None
            return True

    def heartbeat(self, client_id):
        with self._guard:
            if self._live_holder() != client_id:
                return False
            self._expires = self._clock() + self._ttl
            return True

    def handover(self, from_id, to_id):
        with self._guard:
            if self._live_holder() != from_id:
                return False
            self._holder = to_id
            self._expires = self._clock() + self._ttl
            return True

    def require(self, client_id):
        """Raise unless *client_id* holds the lease."""
        current = self.holder
        if current is None:
            raise LeaseError(
                "this command needs rig control, but no client holds it -- "
                "claim control first")
        if current != client_id:
            raise LeaseError(
                f"this command needs rig control, which is held by {current}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/rig/test_lease.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add hsc/rig/lease.py tests/rig/test_lease.py
git commit -m "feat: single-controller lease with TTL"
```

---

### Task 7: Events

**Files:**
- Create: `hsc/rig/events.py`
- Test: `tests/rig/test_events.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Event(kind, payload)`, `EventBus()` with `subscribe() -> Queue`, `unsubscribe(q)`, `publish(kind, **payload)`, `history(limit)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/rig/test_events.py
"""Fan-out of rig events to every connected client, controller or observer."""
import queue

from hsc.rig.events import EventBus


def test_every_subscriber_receives_a_published_event():
    bus = EventBus()
    a, b = bus.subscribe(), bus.subscribe()
    bus.publish("status", text="Capturing")
    assert a.get_nowait().kind == "status"
    assert b.get_nowait().payload == {"text": "Capturing"}


def test_unsubscribed_queue_stops_receiving():
    bus = EventBus()
    a = bus.subscribe()
    bus.unsubscribe(a)
    bus.publish("status", text="x")
    with_raises = queue.Empty
    try:
        a.get_nowait()
        assert False, "expected no event"
    except with_raises:
        pass


def test_a_full_subscriber_queue_drops_instead_of_blocking():
    """A slow observer must never stall the grab thread."""
    bus = EventBus(maxsize=2)
    slow = bus.subscribe()
    for i in range(5):
        bus.publish("log", text=str(i))
    assert slow.qsize() == 2


def test_history_returns_recent_events_for_a_late_joiner():
    bus = EventBus()
    bus.publish("log", text="one")
    bus.publish("log", text="two")
    assert [e.payload["text"] for e in bus.history(10)] == ["one", "two"]
    assert len(bus.history(1)) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/rig/test_events.py -v`
Expected: FAIL — `No module named 'hsc.rig.events'`

- [ ] **Step 3: Write minimal implementation**

```python
# hsc/rig/events.py
#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""In-process fan-out of rig events.

Publishing NEVER blocks: a subscriber that stops draining loses events rather
than stalling the publisher, because the publisher is the camera grab thread
and a stalled grab loop drops frames from a running capture.
"""

import queue
import threading
from collections import deque
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Event:
    kind: str
    payload: dict = field(default_factory=dict)


class EventBus:
    def __init__(self, maxsize=256, history=200):
        self._maxsize = maxsize
        self._subscribers = []
        self._history = deque(maxlen=history)
        self._guard = threading.Lock()

    def subscribe(self):
        q = queue.Queue(maxsize=self._maxsize)
        with self._guard:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q):
        with self._guard:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def publish(self, kind, **payload):
        event = Event(kind, payload)
        with self._guard:
            self._history.append(event)
            targets = list(self._subscribers)
        for q in targets:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass                # see module docstring
        return event

    def history(self, limit=50):
        with self._guard:
            return list(self._history)[-int(limit):]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/rig/test_events.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add hsc/rig/events.py tests/rig/test_events.py
git commit -m "feat: non-blocking rig event bus"
```

---

### Task 8: Camera worker — piston burst

This is the risky task: it moves behaviour earned from rig failures. Every one
of those behaviours gets a test **before** the Tk code is touched.

**Files:**
- Create: `hsc/rig/worker.py`
- Test: `tests/rig/test_worker.py`
- Read for reference (do not modify): `hsc/gui/camera_worker.py:319-470`

**Interfaces:**
- Consumes: `CameraDevice`, `Frame`, `CaptureConfig` (Tasks 1–3); `EventBus` (Task 7); `hsc.capture_image.with_label`, `hsc.injection_extract.make_dest_dir`, `hsc.piston_track.CAPTURE_META_NAME`.
- Produces: `CameraWorker(device, bus, burst_dir)` with `capture_piston(cfg, duration_s, label="", prefix="frame", ext=".bmp", cancel=None) -> BurstResult(output_dir, frames, fps, dropped, elapsed_s)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/rig/test_worker.py
"""The piston burst, finally testable.

Each test here pins a behaviour that was learned from a failed rig run and
previously had no coverage at all -- the frame-rate bug of 2026-08-13 was
invisible because nothing could execute this path.
"""
import json
from pathlib import Path

import pytest

from hsc.hardware.device import CaptureConfig
from hsc.hardware.fake import FakeCamera
from hsc.rig.events import EventBus
from hsc.rig.worker import CameraWorker, WrongFrameSize

BURST = Path(__file__).resolve().parents[1] / "fixtures" / "burst_320x120"
CFG = CaptureConfig(width=320, height=120, exposure_us=500.0)


def _worker(tmp_path, **kwargs):
    cam = FakeCamera(BURST, **kwargs)
    return CameraWorker(cam, EventBus(), tmp_path / "captures"), cam


def test_burst_saves_every_frame_it_grabbed(tmp_path):
    worker, cam = _worker(tmp_path)
    result = worker.capture_piston(CFG, duration_s=10.0)
    saved = sorted(result.output_dir.glob("frame_*.bmp"))
    assert len(saved) == result.frames == 12
    assert cam.saved == saved


def test_camera_is_reprogrammed_before_the_burst(tmp_path):
    """configure_camera otherwise runs only at grab-thread start, so a burst
    inherits the preview's ROI timing: run 2026-08-13-09-18-35 delivered
    correct 320x64 frames at the 320x120 period, 1798 fps instead of 2624."""
    worker, cam = _worker(tmp_path)
    cam.open(1)
    cam.configure(CaptureConfig(320, 240, 500.0))     # a stale preview config
    cam.start()
    worker.capture_piston(CFG, duration_s=10.0)
    assert (cam.configs[-1].width, cam.configs[-1].height) == (320, 120)


def test_a_frame_of_the_wrong_size_aborts_the_burst(tmp_path):
    """mm/px is calibrated at one ROI; a burst at another would be measured
    against the wrong magnification, so refuse rather than report wrong mm."""
    worker, _cam = _worker(tmp_path, roi_override=(320, 240))
    with pytest.raises(WrongFrameSize, match="320x240"):
        worker.capture_piston(CFG, duration_s=10.0)


def test_timing_file_records_ticks_relative_to_the_first_frame(tmp_path):
    from hsc import piston_track
    worker, _cam = _worker(tmp_path, fps=1000.0)
    result = worker.capture_piston(CFG, duration_s=10.0)
    meta = json.loads(
        (result.output_dir / piston_track.CAPTURE_META_NAME
         ).read_text(encoding="utf-8"))
    assert meta["frame_times_us"][0] == 0
    assert meta["frame_times_us"][1] == 1_000_000      # raw ticks, not converted
    assert meta["captured"] == 12
    assert meta["fps"] == pytest.approx(result.fps)


def test_dropped_frames_are_counted_from_block_id_gaps(tmp_path):
    worker, _cam = _worker(tmp_path, drop_after=3)
    result = worker.capture_piston(CFG, duration_s=10.0)
    assert result.dropped == 1


def test_run_folder_carries_the_label_and_size(tmp_path):
    worker, _cam = _worker(tmp_path)
    result = worker.capture_piston(CFG, duration_s=10.0, label="IN37 30U")
    assert result.output_dir.name.endswith("_320x120_IN37-30U")


def test_cancel_stops_the_burst_and_keeps_what_was_grabbed(tmp_path):
    worker, _cam = _worker(tmp_path)
    stop_after = {"n": 0}

    def cancel():
        stop_after["n"] += 1
        return stop_after["n"] > 4

    result = worker.capture_piston(CFG, duration_s=10.0, cancel=cancel)
    assert 0 < result.frames < 12
    assert len(list(result.output_dir.glob("frame_*.bmp"))) == result.frames


def test_a_burst_that_grabbed_nothing_is_an_error(tmp_path):
    worker, _cam = _worker(tmp_path)
    with pytest.raises(RuntimeError, match="No frames"):
        worker.capture_piston(CFG, duration_s=10.0, cancel=lambda: True)


def test_progress_and_completion_are_published(tmp_path):
    bus = EventBus()
    worker = CameraWorker(FakeCamera(BURST), bus, tmp_path / "captures")
    q = bus.subscribe()
    worker.capture_piston(CFG, duration_s=10.0)
    kinds = []
    while not q.empty():
        kinds.append(q.get_nowait().kind)
    assert "capture_started" in kinds and "capture_done" in kinds
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/rig/test_worker.py -v`
Expected: FAIL — `No module named 'hsc.rig.worker'`

- [ ] **Step 3: Write minimal implementation**

Port from `hsc/gui/camera_worker.py:319-470`, replacing SDK calls with
`CameraDevice` and Tk queues with the bus. Keep the comments explaining *why*
each guard exists — they are the record of the failures that produced them.

```python
# hsc/rig/worker.py
#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""The single camera thread's work, independent of any UI.

Ported from ``hsc/gui/camera_worker.py``. Three behaviours here were each
learned from a failed rig run and are now covered for the first time:

* the camera is REPROGRAMMED before the burst -- otherwise it keeps the frame
  period of whatever the preview last set, and run 2026-08-13-09-18-35
  delivered correctly-shaped 320x64 frames at the 320x120 period (1798 fps
  instead of 2624), which the size check cannot catch;
* every frame's size is verified, because mm/px is calibrated at one ROI and a
  burst at another would be measured against the wrong magnification;
* every frame's ``block_id`` and ``timestamp`` are recorded, because frame
  index is not time when the camera free-runs, and gaps are the only evidence
  of a dropped frame.

Timestamps are stored as RAW TICKS relative to the first frame. The unit is
inferred later by ``measure_piston.resolve_timebase``; converting here would
throw away the evidence it uses.
"""

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from hsc import capture_image, injection_extract, piston_track


class WrongFrameSize(RuntimeError):
    """The camera streamed a size other than the one programmed."""


@dataclass(frozen=True)
class BurstResult:
    output_dir: Path
    frames: int
    fps: float
    dropped: int
    elapsed_s: float


class CameraWorker:
    def __init__(self, device, bus, burst_dir):
        self._device = device
        self._bus = bus
        self._burst_dir = Path(burst_dir)

    def capture_piston(self, cfg, duration_s, label="", prefix="frame",
                       ext=".bmp", cancel=None):
        self._device.open(1)
        self._device.stop()
        self._device.configure(cfg)     # see module docstring
        self._device.start()

        stamp = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        run_name = capture_image.with_label(
            f"piston_{stamp}_{cfg.width}x{cfg.height}", label)
        output_dir = injection_extract.make_dest_dir(
            Path(run_name), self._burst_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        self._bus.publish("capture_started", output_dir=str(output_dir),
                          duration_s=duration_s,
                          size=f"{cfg.width}x{cfg.height}")

        clones, ticks, block_ids = [], [], []
        started = time.perf_counter()
        deadline = started + duration_s
        try:
            while time.perf_counter() < deadline:
                if cancel is not None and cancel():
                    break
                frame = self._device.grab(1000)
                if frame is None:
                    break
                try:
                    self._check_size(frame, cfg)
                    clones.append(self._device.clone(frame))
                    ticks.append(frame.timestamp)
                    block_ids.append(frame.block_id)
                finally:
                    self._device.release(frame)

            elapsed = time.perf_counter() - started
            self._require_frames(clones, output_dir)
            fps = len(clones) / elapsed if elapsed > 0 else 0.0
            for number, clone in enumerate(clones, start=1):
                self._device.save(clone, capture_image.make_frame_path(
                    output_dir, prefix, number, ext))
            dropped = _dropped(block_ids)
            _write_meta(output_dir, fps, ticks, len(clones), dropped, elapsed,
                        cfg)
        finally:
            for clone in clones:
                self._device.release(clone)

        result = BurstResult(output_dir, len(clones), fps, dropped, elapsed)
        self._bus.publish("capture_done", output_dir=str(output_dir),
                          frames=result.frames, fps=fps, dropped=dropped)
        return result

    @staticmethod
    def _check_size(frame, cfg):
        if (frame.width, frame.height) != (cfg.width, cfg.height):
            raise WrongFrameSize(
                f"The camera is streaming {frame.width}x{frame.height}, but "
                f"this capture must be {cfg.width}x{cfg.height} (the size the "
                "scale calibration was made at).")

    @staticmethod
    def _require_frames(clones, output_dir):
        if not clones:
            raise RuntimeError(
                "No frames were grabbed - check the camera and lighting.")


def _dropped(block_ids):
    if len(block_ids) < 2:
        return 0
    return max(0, (block_ids[-1] - block_ids[0] + 1) - len(block_ids))


def _write_meta(output_dir, fps, ticks, captured, dropped, elapsed, cfg):
    base = ticks[0] if ticks else 0
    (output_dir / piston_track.CAPTURE_META_NAME).write_text(json.dumps({
        "fps": fps,
        # Raw SDK ticks relative to the first frame -- see module docstring.
        "frame_times_us": [tick - base for tick in ticks],
        "captured": captured, "dropped": dropped, "elapsed_s": elapsed,
        "aspect": f"{cfg.width}x{cfg.height}",
        "width": cfg.width, "height": cfg.height,
    }), encoding="utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/rig/test_worker.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add hsc/rig/worker.py tests/rig/test_worker.py
git commit -m "feat: camera worker piston burst, covered against a fake camera"
```

---

### Task 9: Piston pipeline jobs

**Files:**
- Create: `hsc/rig/jobs.py`
- Test: `tests/rig/test_jobs.py`

**Interfaces:**
- Consumes: `CameraWorker`, `BurstResult` (Task 8); `EventBus` (Task 7); `RunStore`, `RunRecord` (Task 4); `hsc.piston_track.extract_piston_event`, `hsc.measure_piston.measure_folder`, `hsc.make_video.make_video`.
- Produces: `JobManager(worker, store, bus, paths)` with `submit(kind, params) -> str`, `get(job_id) -> Job`, `cancel(job_id) -> bool`, `wait(job_id, timeout)`; `Job(id, kind, state, phase, progress, error, run_id)`; states `queued|running|done|failed|cancelled`.

- [ ] **Step 1: Write the failing test**

```python
# tests/rig/test_jobs.py
"""Pipeline jobs with phases, plus the same steps standalone for re-analysis."""
from pathlib import Path

import pytest

from hsc.hardware.device import CaptureConfig
from hsc.hardware.fake import FakeCamera
from hsc.rig.events import EventBus
from hsc.rig.jobs import JobManager, RigPaths
from hsc.rig.store import RunStore
from hsc.rig.worker import CameraWorker

BURST = Path(__file__).resolve().parents[1] / "fixtures" / "burst_320x120"
CFG = dict(width=320, height=120, exposure_us=500.0, duration_s=10.0)


def _manager(tmp_path, **cam):
    paths = RigPaths(captures=tmp_path / "captures",
                     injections=tmp_path / "injection images",
                     measures=tmp_path / "measure")
    worker = CameraWorker(FakeCamera(BURST, **cam), EventBus(), paths.captures)
    bus = EventBus()
    return JobManager(worker, RunStore(tmp_path / "rig.db"), bus, paths), bus


def test_capture_step_job_completes_and_reports_its_folder(tmp_path):
    manager, _bus = _manager(tmp_path)
    job_id = manager.submit("capture", CFG)
    job = manager.wait(job_id, timeout=30)
    assert job.state == "done"
    assert Path(job.result["output_dir"]).exists()


def test_unknown_job_kind_is_rejected(tmp_path):
    manager, _bus = _manager(tmp_path)
    with pytest.raises(ValueError, match="unknown job kind"):
        manager.submit("teleport", {})


def test_pipeline_emits_each_phase_in_order(tmp_path):
    manager, bus = _manager(tmp_path)
    q = bus.subscribe()
    job_id = manager.submit("piston_run", CFG)
    manager.wait(job_id, timeout=60)
    phases = [e.payload["phase"] for e in _drain(q)
              if e.kind == "job" and e.payload.get("phase")]
    assert phases[:1] == ["capture"]
    assert set(phases) <= {"capture", "find", "measure", "video"}


def test_pipeline_failure_stops_the_chain_and_records_the_reason(tmp_path):
    """The 12-frame fixture holds no injection, so `find` must fail -- and the
    chain must not go on to measure a window that does not exist."""
    manager, bus = _manager(tmp_path)
    q = bus.subscribe()
    job = manager.wait(manager.submit("piston_run", CFG), timeout=60)
    assert job.state == "failed"
    assert "injection" in job.error.lower()
    phases = [e.payload["phase"] for e in _drain(q)
              if e.kind == "job" and e.payload.get("phase")]
    assert "measure" not in phases


def test_cancel_marks_the_job_cancelled(tmp_path):
    manager, _bus = _manager(tmp_path)
    job_id = manager.submit("piston_run", dict(CFG, duration_s=30.0))
    manager.cancel(job_id)
    job = manager.wait(job_id, timeout=30)
    assert job.state == "cancelled"


def test_cancelling_an_unknown_job_returns_false(tmp_path):
    manager, _bus = _manager(tmp_path)
    assert manager.cancel("nope") is False


def test_get_returns_none_for_an_unknown_job(tmp_path):
    manager, _bus = _manager(tmp_path)
    assert manager.get("nope") is None


def _drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out
```

**Note:** the 12-frame fixture cannot produce a measurable stroke, so
`piston_run` is expected to fail at `find`. That is deliberate — it covers the
failure path. A success-path pipeline test needs a longer fixture; add it in
Task 10 using a synthetic burst generated by `tests/test_piston_track.py`'s
`make_frame` helper rather than committing thousands of BMPs.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/rig/test_jobs.py -v`
Expected: FAIL — `No module named 'hsc.rig.jobs'`

- [ ] **Step 3: Write minimal implementation**

```python
# hsc/rig/jobs.py
#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Jobs: one pipeline that chains the piston workflow, and the same steps
standalone.

The chain mirrors what the Tk app did (capture -> find -> measure -> video),
because that is the workflow the rig is operated with. The steps are also
available alone, because re-measuring an existing folder without re-capturing
is a daily operation.

Cancellation reuses something that already exists: every long operation in
``hsc/`` takes a ``progress(done, total)`` callback, so that is where a job
checks whether it has been cancelled. No analysis module needs to change.
"""

import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from hsc import make_video, measure_piston, piston_track
from hsc.hardware.device import CaptureConfig
from hsc.rig.store import RunRecord

PIPELINE_PHASES = ("capture", "find", "measure", "video")


class JobCancelled(RuntimeError):
    """Raised inside a progress callback to unwind a cancelled job."""


@dataclass
class RigPaths:
    captures: Path
    injections: Path
    measures: Path


@dataclass
class Job:
    id: str
    kind: str
    params: dict
    state: str = "queued"
    phase: str | None = None
    progress: float = 0.0
    error: str | None = None
    run_id: int | None = None
    result: dict = field(default_factory=dict)


class JobManager:
    def __init__(self, worker, store, bus, paths):
        self._worker = worker
        self._store = store
        self._bus = bus
        self._paths = paths
        self._jobs = {}
        self._cancels = {}
        self._threads = {}
        self._guard = threading.Lock()

    # -- public ------------------------------------------------------------
    def submit(self, kind, params):
        if kind not in _RUNNERS:
            raise ValueError(f"unknown job kind: {kind}")
        job = Job(id=uuid.uuid4().hex, kind=kind, params=dict(params))
        with self._guard:
            self._jobs[job.id] = job
            self._cancels[job.id] = threading.Event()
        thread = threading.Thread(target=self._run, args=(job,), daemon=True)
        self._threads[job.id] = thread
        thread.start()
        return job.id

    def get(self, job_id):
        with self._guard:
            return self._jobs.get(job_id)

    def cancel(self, job_id):
        with self._guard:
            event = self._cancels.get(job_id)
        if event is None:
            return False
        event.set()
        return True

    def wait(self, job_id, timeout=60):
        thread = self._threads.get(job_id)
        if thread is not None:
            thread.join(timeout)
        return self.get(job_id)

    # -- internals ---------------------------------------------------------
    def _run(self, job):
        self._set(job, state="running")
        try:
            _RUNNERS[job.kind](self, job)
            self._set(job, state="done", progress=1.0)
        except JobCancelled:
            self._set(job, state="cancelled")
        except Exception as exc:
            self._set(job, state="failed", error=str(exc))

    def _set(self, job, **changes):
        for key, value in changes.items():
            setattr(job, key, value)
        self._bus.publish("job", id=job.id, kind=job.kind, state=job.state,
                          phase=job.phase, progress=job.progress,
                          error=job.error, run_id=job.run_id)

    def _cancelled(self, job):
        return self._cancels[job.id].is_set()

    def _progress(self, job):
        def report(done, total):
            if self._cancelled(job):
                raise JobCancelled()
            job.progress = (done / total) if total else 0.0
        return report

    def _config(self, job):
        params = job.params
        return CaptureConfig(width=int(params["width"]),
                             height=int(params["height"]),
                             exposure_us=float(params["exposure_us"]))

    # -- steps -------------------------------------------------------------
    def _capture(self, job):
        self._set(job, phase="capture")
        result = self._worker.capture_piston(
            self._config(job), float(job.params.get("duration_s", 4.0)),
            label=job.params.get("label", ""),
            cancel=lambda: self._cancelled(job))
        if self._cancelled(job):
            raise JobCancelled()
        job.result["output_dir"] = str(result.output_dir)
        return result.output_dir

    def _find(self, job, source_dir):
        self._set(job, phase="find")
        found = piston_track.extract_piston_event(
            source_dir, dest_base=self._paths.injections,
            before=30, after=30, fast=True, progress=self._progress(job))
        job.result["injection_dir"] = found["dest_dir"]
        return Path(found["dest_dir"])

    def _measure(self, job, injection_dir):
        self._set(job, phase="measure")
        result = measure_piston.measure_folder(
            injection_dir, dest_base=self._paths.measures,
            progress=self._progress(job),
            log=lambda text: self._bus.publish("log", text=text))
        job.result["measure_dir"] = result["dest_dir"]
        job.run_id = self._store.add_run(_record_from(result, job))
        return Path(result["dest_dir"])

    def _video(self, job, measure_dir):
        self._set(job, phase="video")
        made = make_video.make_video(measure_dir, progress=self._progress(job))
        job.result["video"] = made["out_path"]


def _capture_only(manager, job):
    manager._capture(job)


def _find_only(manager, job):
    manager._find(job, Path(job.params["source_dir"]))


def _measure_only(manager, job):
    manager._measure(job, Path(job.params["injection_dir"]))


def _video_only(manager, job):
    manager._video(job, Path(job.params["measure_dir"]))


def _pipeline(manager, job):
    source = manager._capture(job)
    injection = manager._find(job, source)
    measure = manager._measure(job, injection)
    manager._video(job, measure)


_RUNNERS = {
    "capture": _capture_only,
    "find": _find_only,
    "measure": _measure_only,
    "video": _video_only,
    "piston_run": _pipeline,
}


def _record_from(result, job):
    return RunRecord(
        kind="piston",
        captured_at=str(job.params.get("captured_at", "")),
        measure_dir=result["dest_dir"],
        label=job.params.get("label") or None,
        source_dir=job.result.get("output_dir"),
        injection_dir=job.result.get("injection_dir"),
        roi=f"{job.params.get('width')}x{job.params.get('height')}",
        fps=result.get("fps"), timebase=result.get("timebase"),
        exposure_us=job.params.get("exposure_us"),
        mm_per_px=result.get("mm_per_px"),
        scale_source=result.get("scale_source"),
        stroke_px=result.get("stroke_px"), stroke_mm=result.get("stroke_mm"),
        duration_ms=result.get("duration_ms"),
        mean_speed_mm_s=result.get("mean_speed_mm_s"),
        peak_speed_mm_s=result.get("peak_speed_mm_s"),
        peak_jet_speed_m_s=result.get("peak_jet_speed_m_s"),
        peak_jet_pressure_MPa=result.get("peak_jet_pressure_MPa"),
        measured_count=result.get("measured_count"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/rig/test_jobs.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add hsc/rig/jobs.py tests/rig/test_jobs.py
git commit -m "feat: piston pipeline and step jobs with cancellation"
```

---

### Task 10: Pipeline success path on a synthetic burst

**Files:**
- Create: `tests/rig/test_pipeline_end_to_end.py`
- Create: `tests/rig/conftest.py`

**Interfaces:**
- Consumes: everything from Tasks 1–9; `tests/test_piston_track.py::make_frame`.
- Produces: pytest fixture `synthetic_burst(tmp_path) -> Path` — a 400-frame burst with a real stroke.

- [ ] **Step 1: Write the failing test**

```python
# tests/rig/conftest.py
"""A burst long enough to contain a measurable stroke, generated rather than
committed -- thousands of BMPs do not belong in git."""
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_piston_track import make_frame        # noqa: E402


@pytest.fixture
def synthetic_burst(tmp_path):
    folder = tmp_path / "burst"
    folder.mkdir()
    rest, move, tail = 120, 120, 120
    x0, step = 40.0, 1.2
    positions = ([x0] * rest
                 + [x0 + step * (i + 1) for i in range(move)])
    positions += [positions[-1]] * tail
    for i, x in enumerate(positions, start=1):
        cv2.imwrite(str(folder / f"frame_{i:06d}.bmp"),
                    make_frame(edge_x=x, noise=1.0, seed=i))
    return folder
```

```python
# tests/rig/test_pipeline_end_to_end.py
"""The whole pipeline against a fake camera: capture, find, measure, persist.

This is the first coverage the capture path has ever had end to end.
"""
from pathlib import Path

from hsc.hardware.fake import FakeCamera
from hsc.rig.events import EventBus
from hsc.rig.jobs import JobManager, RigPaths
from hsc.rig.store import RunStore
from hsc.rig.worker import CameraWorker

PARAMS = dict(width=320, height=240, exposure_us=500.0, duration_s=60.0,
              label="TEST-4U")


def test_pipeline_measures_and_persists_a_run(tmp_path, synthetic_burst):
    paths = RigPaths(captures=tmp_path / "captures",
                     injections=tmp_path / "injection images",
                     measures=tmp_path / "measure")
    store = RunStore(tmp_path / "rig.db")
    bus = EventBus()
    worker = CameraWorker(FakeCamera(synthetic_burst, fps=1000.0), bus,
                          paths.captures)
    manager = JobManager(worker, store, bus, paths)

    job = manager.wait(manager.submit("piston_run", PARAMS), timeout=300)

    assert job.state == "done", job.error
    assert job.run_id is not None

    run = store.get_run(job.run_id)
    assert run.kind == "piston"
    assert run.label == "TEST-4U"
    # 120 frames x 1.2 px at the synthetic scale; the exact mm depend on the
    # stored calibration, so assert the px stroke which does not.
    assert run.stroke_px == pytest.approx(144.0, rel=0.05)
    assert Path(run.measure_dir).exists()
    assert list(Path(run.measure_dir).glob("*_speed.csv"))


def test_measure_step_can_be_rerun_standalone(tmp_path, synthetic_burst):
    """Re-measuring an existing folder without re-capturing is a daily task."""
    paths = RigPaths(captures=tmp_path / "captures",
                     injections=tmp_path / "injection images",
                     measures=tmp_path / "measure")
    store = RunStore(tmp_path / "rig.db")
    bus = EventBus()
    worker = CameraWorker(FakeCamera(synthetic_burst, fps=1000.0), bus,
                          paths.captures)
    manager = JobManager(worker, store, bus, paths)
    first = manager.wait(manager.submit("piston_run", PARAMS), timeout=300)

    again = manager.wait(manager.submit(
        "measure", {"injection_dir": first.result["injection_dir"],
                    "width": 320, "height": 240}), timeout=300)

    assert again.state == "done"
    assert len(store.list_runs()) == 2      # a second measure folder
```

Add `import pytest` to the top of the end-to-end test file.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/rig/test_pipeline_end_to_end.py -v`
Expected: FAIL — fixture missing, then assertions.

- [ ] **Step 3: Make it pass**

No new production code should be needed. If a test fails, fix `hsc/rig/`, not
`hsc/`. If a genuine gap appears in an analysis module, stop and ask.

- [ ] **Step 4: Run the full suite**

Run: `uv run python -m pytest -q`
Expected: all pass, existing 202 included.

- [ ] **Step 5: Commit**

```bash
git add tests/rig/conftest.py tests/rig/test_pipeline_end_to_end.py
git commit -m "test: pipeline end to end against a fake camera"
```

---

### Task 11: FastAPI app, settings, health

**Files:**
- Create: `hsc/api/__init__.py`, `hsc/api/app.py`, `hsc/api/errors.py`, `hsc/api/deps.py`
- Modify: `pyproject.toml` (fastapi, uvicorn, httpx)
- Test: `tests/api/__init__.py`, `tests/api/conftest.py`, `tests/api/test_app.py`

**Interfaces:**
- Consumes: `JobManager`, `RunStore`, `ControlLease`, `EventBus`, `RigPaths`.
- Produces: `create_app(services: RigServices) -> FastAPI`; `RigServices(store, jobs, lease, bus, paths, spa_dir=None, cors_origins=())`; `to_error_code(exc) -> tuple[str, int]`.

- [ ] **Step 1: Add dependencies**

```bash
uv add fastapi uvicorn
uv add --dev httpx
```

- [ ] **Step 2: Write the failing test**

```python
# tests/api/conftest.py
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hsc.hardware.fake import FakeCamera
from hsc.api.app import RigServices, create_app
from hsc.rig.events import EventBus
from hsc.rig.jobs import JobManager, RigPaths
from hsc.rig.lease import ControlLease
from hsc.rig.store import RunStore
from hsc.rig.worker import CameraWorker

BURST = Path(__file__).resolve().parents[1] / "fixtures" / "burst_320x120"


@pytest.fixture
def services(tmp_path):
    paths = RigPaths(captures=tmp_path / "captures",
                     injections=tmp_path / "injection images",
                     measures=tmp_path / "measure")
    bus = EventBus()
    store = RunStore(tmp_path / "rig.db")
    worker = CameraWorker(FakeCamera(BURST), bus, paths.captures)
    return RigServices(store=store, jobs=JobManager(worker, store, bus, paths),
                       lease=ControlLease(), bus=bus, paths=paths)


@pytest.fixture
def client(services):
    return TestClient(create_app(services))
```

```python
# tests/api/test_app.py
"""App wiring: health, settings, CORS, SPA mount, error translation."""
from hsc.api.errors import to_error_code
from hsc.api.app import RigServices, create_app
from hsc.rig.lease import LeaseError


def test_health_reports_ok(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_settings_round_trip(client):
    assert client.get("/api/settings").json() == {}
    client.put("/api/settings", json={"roi": "320x120", "exposure_us": "500"})
    assert client.get("/api/settings").json()["roi"] == "320x120"


def test_camera_status_reports_the_lease(client, services):
    body = client.get("/api/camera/status").json()
    assert body["lease_holder"] is None
    services.lease.claim("someone")
    assert client.get("/api/camera/status").json()["lease_holder"] == "someone"


def test_lease_error_maps_to_409(client, services):
    services.lease.claim("other")
    response = client.post("/api/jobs", json={
        "kind": "capture", "params": {}, "client_id": "me"})
    assert response.status_code == 409
    assert response.json()["code"] == "LEASE_REQUIRED"


def test_error_codes_carry_the_diagnostic_text():
    code, status = to_error_code(RuntimeError(
        "The piston never gets blacker than 18 grey (needs <= 10)."))
    assert code == "CONTRAST_TOO_LOW"
    assert status == 422
    assert to_error_code(RuntimeError("No measurable injection in this burst"))[0] == "NO_INJECTION"
    assert to_error_code(LeaseError("x"))[0] == "LEASE_REQUIRED"
    assert to_error_code(RuntimeError("something else"))[0] == "INTERNAL"


def test_cors_headers_are_present_for_a_configured_origin(services):
    from fastapi.testclient import TestClient
    services.cors_origins = ("https://rig.vercel.app",)
    client = TestClient(create_app(services))
    response = client.get("/api/health",
                          headers={"Origin": "https://rig.vercel.app"})
    assert response.headers["access-control-allow-origin"] == \
        "https://rig.vercel.app"


def test_spa_is_served_when_a_build_exists(tmp_path, services):
    from fastapi.testclient import TestClient
    spa = tmp_path / "dist"
    spa.mkdir()
    (spa / "index.html").write_text("<html>rig</html>", encoding="utf-8")
    services.spa_dir = spa
    client = TestClient(create_app(services))
    assert "rig" in client.get("/").text


def test_missing_spa_directory_is_not_fatal(client):
    assert client.get("/api/health").status_code == 200
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run python -m pytest tests/api/test_app.py -v`
Expected: FAIL — `No module named 'hsc.api'`

- [ ] **Step 4: Write minimal implementation**

```python
# hsc/api/errors.py
#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Turn the rig's diagnostics into codes a UI can act on.

``hsc/`` raises messages written for a person -- "the piston never gets
blacker than 18 grey", "no measurable injection in this burst". Those stay as
the human fallback, but the frontend needs to branch (show the lighting
numbers, offer a recapture), so each maps to a stable code.
"""

from hsc.rig.lease import LeaseError

_PATTERNS = (
    ("blacker than", "CONTRAST_TOO_LOW", 422),
    ("contrast too low", "CONTRAST_TOO_LOW", 422),
    ("no measurable injection", "NO_INJECTION", 422),
    ("no piston movement", "NO_INJECTION", 422),
    ("no barrel interior", "NO_BARREL", 422),
    ("no frame timing", "NO_TIMEBASE", 422),
    ("camera is streaming", "WRONG_FRAME_SIZE", 422),
    ("no frames were grabbed", "NO_CAMERA", 503),
    ("no image frames found", "EMPTY_FOLDER", 404),
)


def to_error_code(exc):
    """``(code, http_status)`` for an exception raised by the rig layer."""
    if isinstance(exc, LeaseError):
        return "LEASE_REQUIRED", 409
    text = str(exc).lower()
    for needle, code, status in _PATTERNS:
        if needle in text:
            return code, status
    return "INTERNAL", 500
```

```python
# hsc/api/app.py
#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""FastAPI application over the rig service.

Thin on purpose: everything it exposes is implemented and tested in
``hsc/rig/``. This layer translates HTTP to those calls and exceptions to
codes, and serves the built SPA when one is present so the rig works from a
single process.
"""

from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from hsc.api.errors import to_error_code


@dataclass
class RigServices:
    store: object
    jobs: object
    lease: object
    bus: object
    paths: object
    spa_dir: Path | None = None
    cors_origins: tuple = field(default_factory=tuple)


def create_app(services):
    app = FastAPI(title="High Speed Camera Rig")
    app.state.services = services

    if services.cors_origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=list(services.cors_origins),
            allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(Exception)
    async def _errors(request: Request, exc: Exception):
        code, status = to_error_code(exc)
        return JSONResponse(status_code=status,
                            content={"code": code, "message": str(exc)})

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/camera/status")
    async def camera_status():
        return {"lease_holder": services.lease.holder}

    @app.get("/api/settings")
    async def get_settings():
        return services.store.get_settings()

    @app.put("/api/settings")
    async def put_settings(values: dict):
        for key, value in values.items():
            services.store.set_setting(key, value)
        return services.store.get_settings()

    from hsc.api import routes_control, routes_runs, ws_events, ws_preview
    routes_runs.register(app, services)
    routes_control.register(app, services)
    ws_events.register(app, services)
    ws_preview.register(app, services)

    if services.spa_dir is not None and Path(services.spa_dir).exists():
        app.mount("/", StaticFiles(directory=str(services.spa_dir),
                                   html=True), name="spa")
    return app
```

```python
# hsc/api/deps.py
"""Shared helpers for the route modules."""


def services_of(app):
    return app.state.services
```

Create empty stubs so the imports resolve; they are filled in Tasks 12–14:

```python
# hsc/api/routes_runs.py, routes_control.py, ws_events.py, ws_preview.py
def register(app, services):
    """Filled in by a later task."""
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run python -m pytest tests/api/test_app.py -v`
Expected: FAIL on `test_lease_error_maps_to_409` until Task 13 adds
`/api/jobs`. Mark that one `@pytest.mark.xfail(reason="Task 13")` and remove
the marker in Task 13.

- [ ] **Step 6: Commit**

```bash
git add hsc/api tests/api pyproject.toml
git commit -m "feat: FastAPI app, settings, typed error codes"
```

---

### Task 12: Runs, CSV and media endpoints

**Files:**
- Modify: `hsc/api/routes_runs.py`
- Test: `tests/api/test_routes_runs.py`

**Interfaces:**
- Consumes: `RunStore`, `import_measure_root`, `hsc.summary.summarize`.
- Produces: `register(app, services)` adding `GET /api/runs`, `GET /api/runs/{id}`, `GET /api/runs/{id}/csv`, `GET /api/runs/{id}/media/{name}`, `POST /api/runs/import`, `POST /api/summary`.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_routes_runs.py
"""Reading results: list, detail, the per-frame CSV, and media files."""
import pytest

from hsc.rig.store import RunRecord


def _add(services, tmp_path, name="piston_run", **over):
    folder = tmp_path / "measure" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}_speed.csv").write_text("frame,time_ms\na,1\n",
                                              encoding="utf-8")
    (folder / f"{name}_speed_time.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    record = RunRecord(kind="piston", captured_at="2026-08-14T10:00:00",
                       measure_dir=str(folder), label="L", stroke_mm=1.0)
    for key, value in over.items():
        setattr(record, key, value)
    return services.store.add_run(record)


def test_list_and_detail(client, services, tmp_path):
    run_id = _add(services, tmp_path)
    listed = client.get("/api/runs").json()
    assert listed[0]["id"] == run_id
    assert client.get(f"/api/runs/{run_id}").json()["label"] == "L"


def test_detail_404_for_unknown_run(client):
    assert client.get("/api/runs/999").status_code == 404


def test_list_filters_by_kind_and_limit(client, services, tmp_path):
    _add(services, tmp_path, name="a")
    _add(services, tmp_path, name="b", kind="spray")
    assert len(client.get("/api/runs?kind=piston").json()) == 1
    assert len(client.get("/api/runs?limit=1").json()) == 1


def test_csv_is_streamed(client, services, tmp_path):
    run_id = _add(services, tmp_path)
    response = client.get(f"/api/runs/{run_id}/csv")
    assert response.status_code == 200
    assert "frame,time_ms" in response.text


def test_csv_404_when_the_folder_has_none(client, services, tmp_path):
    folder = tmp_path / "measure" / "empty"
    folder.mkdir(parents=True)
    run_id = services.store.add_run(RunRecord(
        kind="piston", captured_at="x", measure_dir=str(folder)))
    assert client.get(f"/api/runs/{run_id}/csv").status_code == 404


def test_media_serves_a_file_from_the_run_folder(client, services, tmp_path):
    run_id = _add(services, tmp_path)
    response = client.get(
        f"/api/runs/{run_id}/media/piston_run_speed_time.png")
    assert response.status_code == 200
    assert response.content.startswith(b"\x89PNG")


def test_media_refuses_a_path_outside_the_run_folder(client, services, tmp_path):
    """A run id plus a crafted name must not read arbitrary files."""
    run_id = _add(services, tmp_path)
    response = client.get(f"/api/runs/{run_id}/media/..%2F..%2Frig.db")
    assert response.status_code in (400, 404)


def test_import_scans_the_measure_root(client, services, tmp_path):
    name = "piston_2026-08-14-10-00-00_320x120_X"
    folder = services.paths.measures / name
    folder.mkdir(parents=True)
    (folder / f"{name}_speed.csv").write_text(
        "frame,time_ms\n\nstroke_mm,1.0\n", encoding="utf-8")
    body = client.post("/api/runs/import").json()
    assert body["imported"] == 1


def test_summary_over_selected_runs(client, services, tmp_path):
    ids = [_add(services, tmp_path, name=f"r{i}") for i in range(2)]
    response = client.post("/api/summary", json={"run_ids": ids})
    assert response.status_code in (200, 422)   # 422 if folders lack metrics
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/api/test_routes_runs.py -v`
Expected: FAIL — 404s, `register` is a stub.

- [ ] **Step 3: Write minimal implementation**

```python
# hsc/api/routes_runs.py
#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Reading results: runs, their per-frame CSV, and their media files."""

from dataclasses import asdict
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse

from hsc import summary
from hsc.rig.importer import import_measure_root


def register(app, services):

    def _run_or_404(run_id):
        run = services.store.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="unknown run")
        return run

    @app.get("/api/runs")
    async def list_runs(kind: str | None = None, label: str | None = None,
                        limit: int = 100):
        return [asdict(r) for r in services.store.list_runs(kind, label, limit)]

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: int):
        return asdict(_run_or_404(run_id))

    @app.get("/api/runs/{run_id}/csv")
    async def get_csv(run_id: int):
        run = _run_or_404(run_id)
        path = summary.find_csv(Path(run.measure_dir))
        if path is None:
            raise HTTPException(status_code=404, detail="no CSV for this run")
        return FileResponse(path, media_type="text/csv")

    @app.get("/api/runs/{run_id}/media/{name}")
    async def get_media(run_id: int, name: str):
        run = _run_or_404(run_id)
        folder = Path(run.measure_dir).resolve()
        target = (folder / name).resolve()
        # A run id plus a crafted name must not read outside the run folder.
        if folder not in target.parents or not target.is_file():
            raise HTTPException(status_code=404, detail="no such file")
        return FileResponse(target)

    @app.post("/api/runs/import")
    async def import_runs():
        result = import_measure_root(services.paths.measures, services.store)
        return {"imported": result.imported, "skipped": result.skipped}

    @app.post("/api/summary")
    async def make_summary(body: dict):
        folders = []
        for run_id in body.get("run_ids", []):
            folders.append(Path(_run_or_404(int(run_id)).measure_dir))
        result = summary.summarize(folders, services.paths.measures)
        return {"path": result["path"],
                "stats": result["stats"],
                "skipped": result["skipped"]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/api/test_routes_runs.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add hsc/api/routes_runs.py tests/api/test_routes_runs.py
git commit -m "feat: runs, csv and media endpoints"
```

---

### Task 13: Jobs and lease endpoints

**Files:**
- Modify: `hsc/api/routes_control.py`, `tests/api/test_app.py` (remove the xfail)
- Test: `tests/api/test_routes_control.py`

**Interfaces:**
- Consumes: `JobManager`, `ControlLease`.
- Produces: `register(app, services)` adding `POST /api/jobs`, `GET /api/jobs/{id}`, `POST /api/jobs/{id}/cancel`, `POST /api/lease/claim|release|heartbeat`.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_routes_control.py
"""Driving the rig: lease first, then jobs."""
from dataclasses import asdict


def _claim(client, client_id="me"):
    return client.post("/api/lease/claim", json={"client_id": client_id})


def test_claim_and_release(client):
    assert _claim(client).json()["holder"] == "me"
    assert client.post("/api/lease/release",
                       json={"client_id": "me"}).json()["holder"] is None


def test_second_claim_is_refused(client):
    _claim(client, "a")
    response = _claim(client, "b")
    assert response.status_code == 409
    assert response.json()["code"] == "LEASE_REQUIRED"


def test_heartbeat_from_a_non_holder_is_refused(client):
    _claim(client, "a")
    assert client.post("/api/lease/heartbeat",
                       json={"client_id": "b"}).status_code == 409


def test_submitting_a_job_requires_the_lease(client):
    response = client.post("/api/jobs", json={
        "kind": "capture", "params": {}, "client_id": "me"})
    assert response.status_code == 409


def test_job_submit_get_and_cancel(client):
    _claim(client)
    submitted = client.post("/api/jobs", json={
        "kind": "capture", "client_id": "me",
        "params": {"width": 320, "height": 120, "exposure_us": 500.0,
                   "duration_s": 30.0}})
    job_id = submitted.json()["id"]
    assert client.get(f"/api/jobs/{job_id}").json()["kind"] == "capture"
    assert client.post(f"/api/jobs/{job_id}/cancel").json()["cancelled"] is True


def test_unknown_job_is_404(client):
    assert client.get("/api/jobs/nope").status_code == 404


def test_unknown_job_kind_is_400(client):
    _claim(client)
    response = client.post("/api/jobs", json={
        "kind": "teleport", "params": {}, "client_id": "me"})
    assert response.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/api/test_routes_control.py -v`
Expected: FAIL — routes missing.

- [ ] **Step 3: Write minimal implementation**

```python
# hsc/api/routes_control.py
#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Driving the rig: the control lease, and the jobs it gates.

Every command that touches hardware requires the lease. A refusal is a typed
409, never a silent no-op -- an operator who thinks they started a capture and
did not is worse off than one who sees an error.
"""

from dataclasses import asdict

from fastapi import HTTPException

from hsc.rig.lease import LeaseError


def register(app, services):

    @app.post("/api/lease/claim")
    async def claim(body: dict):
        client_id = body["client_id"]
        if not services.lease.claim(client_id):
            raise LeaseError(
                f"rig control is held by {services.lease.holder}")
        services.bus.publish("lease", holder=services.lease.holder)
        return {"holder": services.lease.holder}

    @app.post("/api/lease/release")
    async def release(body: dict):
        services.lease.release(body["client_id"])
        services.bus.publish("lease", holder=services.lease.holder)
        return {"holder": services.lease.holder}

    @app.post("/api/lease/heartbeat")
    async def heartbeat(body: dict):
        if not services.lease.heartbeat(body["client_id"]):
            raise LeaseError("rig control is held by another client")
        return {"holder": services.lease.holder}

    @app.post("/api/jobs")
    async def submit(body: dict):
        services.lease.require(body.get("client_id"))
        try:
            job_id = services.jobs.submit(body["kind"], body.get("params", {}))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"id": job_id}

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: str):
        job = services.jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown job")
        return asdict(job)

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel(job_id: str):
        return {"cancelled": services.jobs.cancel(job_id)}
```

Remove the `xfail` marker added in Task 11.

- [ ] **Step 4: Run tests**

Run: `uv run python -m pytest tests/api -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add hsc/api/routes_control.py tests/api
git commit -m "feat: lease and job endpoints, lease-gated commands"
```

---

### Task 14: WebSockets

**Files:**
- Modify: `hsc/api/ws_events.py`, `hsc/api/ws_preview.py`
- Test: `tests/api/test_ws.py`

**Interfaces:**
- Consumes: `EventBus`, `ControlLease`.
- Produces: `/ws/events` (JSON), `/ws/preview` (binary, `PREVIEW_HEADER` struct format `"<IHHQ"` = sequence, width, height, timestamp).

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_ws.py
"""Both sockets. Events must reach observers too; preview must not stall them."""
import json
import struct

from hsc.api.ws_preview import PREVIEW_HEADER, pack_preview


def test_events_socket_greets_with_role_and_lease(client):
    with client.websocket_connect("/ws/events?client_id=me") as ws:
        hello = ws.receive_json()
    assert hello["kind"] == "hello"
    assert hello["payload"]["client_id"] == "me"
    assert hello["payload"]["lease_holder"] is None


def test_published_events_reach_a_connected_client(client, services):
    with client.websocket_connect("/ws/events?client_id=me") as ws:
        ws.receive_json()                       # hello
        services.bus.publish("status", text="Capturing")
        message = ws.receive_json()
    assert message["kind"] == "status"
    assert message["payload"]["text"] == "Capturing"


def test_an_observer_receives_events_it_cannot_command(client, services):
    services.lease.claim("controller")
    with client.websocket_connect("/ws/events?client_id=observer") as ws:
        hello = ws.receive_json()
        assert hello["payload"]["role"] == "observer"
        services.bus.publish("log", text="line")
        assert ws.receive_json()["payload"]["text"] == "line"


def test_preview_frame_packs_a_header_then_jpeg():
    payload = pack_preview(seq=7, width=320, height=120, timestamp=99,
                           jpeg=b"\xff\xd8\xff")
    size = struct.calcsize(PREVIEW_HEADER)
    seq, width, height, timestamp = struct.unpack(PREVIEW_HEADER,
                                                  payload[:size])
    assert (seq, width, height, timestamp) == (7, 320, 120, 99)
    assert payload[size:] == b"\xff\xd8\xff"


def test_preview_socket_sends_frames_published_to_the_bus(client, services):
    import numpy as np
    with client.websocket_connect("/ws/preview") as ws:
        services.bus.publish("preview", width=8, height=4, timestamp=1,
                             pixels=np.zeros((4, 8), dtype=np.uint8))
        payload = ws.receive_bytes()
    assert len(payload) > struct.calcsize(PREVIEW_HEADER)


def test_preview_client_can_pause(client, services):
    with client.websocket_connect("/ws/preview") as ws:
        ws.send_json({"paused": True})
        ack = ws.receive_json()
    assert ack["paused"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/api/test_ws.py -v`
Expected: FAIL — no routes.

- [ ] **Step 3: Write minimal implementation**

```python
# hsc/api/ws_events.py
#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""JSON event socket.

EVERY client receives every event, controller or observer -- watching a
capture is not a privilege. Only commands are lease-gated, and those go over
HTTP where a refusal can carry a status code.
"""

import asyncio
from dataclasses import asdict

from fastapi import WebSocket, WebSocketDisconnect


def register(app, services):

    @app.websocket("/ws/events")
    async def events(ws: WebSocket, client_id: str = "anonymous"):
        await ws.accept()
        holder = services.lease.holder
        await ws.send_json({"kind": "hello", "payload": {
            "client_id": client_id, "lease_holder": holder,
            "role": "controller" if holder == client_id else "observer"}})
        queue = services.bus.subscribe()
        try:
            while True:
                event = await asyncio.get_running_loop().run_in_executor(
                    None, queue.get)
                if event.kind == "preview":
                    continue                  # binary, on the other socket
                await ws.send_json({"kind": event.kind,
                                    "payload": _plain(event.payload)})
        except WebSocketDisconnect:
            pass
        finally:
            services.bus.unsubscribe(queue)
            if services.lease.holder == client_id:
                services.lease.release(client_id)


def _plain(payload):
    return {k: v for k, v in payload.items() if _jsonable(v)}


def _jsonable(value):
    return isinstance(value, (str, int, float, bool, list, dict, type(None)))
```

```python
# hsc/api/ws_preview.py
#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Binary preview socket.

Separate from the event socket so a viewer on a slow link drops frames without
ever delaying the progress of a running capture.
"""

import asyncio
import struct

import cv2
from fastapi import WebSocket, WebSocketDisconnect

#: sequence, width, height, timestamp
PREVIEW_HEADER = "<IHHQ"


def pack_preview(seq, width, height, timestamp, jpeg):
    return struct.pack(PREVIEW_HEADER, seq, width, height, timestamp) + jpeg


def encode(pixels, quality=80):
    ok, buffer = cv2.imencode(".jpg", pixels,
                              [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return buffer.tobytes() if ok else b""


def register(app, services):

    @app.websocket("/ws/preview")
    async def preview(ws: WebSocket):
        await ws.accept()
        queue = services.bus.subscribe()
        state = {"paused": False}
        seq = 0
        try:
            while True:
                receive = asyncio.create_task(_maybe_control(ws, state))
                event = await asyncio.get_running_loop().run_in_executor(
                    None, queue.get)
                receive.cancel()
                if event.kind != "preview" or state["paused"]:
                    continue
                seq += 1
                await ws.send_bytes(pack_preview(
                    seq, event.payload["width"], event.payload["height"],
                    event.payload["timestamp"],
                    encode(event.payload["pixels"])))
        except WebSocketDisconnect:
            pass
        finally:
            services.bus.unsubscribe(queue)


async def _maybe_control(ws, state):
    message = await ws.receive_json()
    state["paused"] = bool(message.get("paused", state["paused"]))
    await ws.send_json({"paused": state["paused"]})
```

**Implementer note:** `test_preview_client_can_pause` may need the control
message handled before any frame arrives. If the task interleaving above proves
flaky under `TestClient`, restructure as two tasks joined with
`asyncio.wait(..., return_when=FIRST_COMPLETED)` — do not weaken the test to a
sleep.

- [ ] **Step 4: Run tests**

Run: `uv run python -m pytest tests/api -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add hsc/api/ws_events.py hsc/api/ws_preview.py tests/api/test_ws.py
git commit -m "feat: JSON event and binary preview WebSockets"
```

---

### Task 15: Layering guard, coverage gate, entry point

**Files:**
- Create: `hsc/api/__main__.py`
- Create: `tests/test_layering.py`
- Modify: `pyproject.toml`, `CLAUDE.md`

**Interfaces:**
- Consumes: everything.
- Produces: `uv run python -m hsc.api --host --port --data-root --spa --cors`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_layering.py
"""The rig layer must stay testable without a server, and the excluded file
must stay trivial. Both are load-bearing for the coverage claim."""
import ast
from pathlib import Path

import pytest

RIG = Path("hsc/rig")
FORBIDDEN = {"fastapi", "starlette", "uvicorn", "hsc.api"}


@pytest.mark.parametrize("path", sorted(RIG.glob("*.py")), ids=lambda p: p.name)
def test_rig_layer_imports_no_web_framework(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
            imported.add(node.module)
    assert not (imported & FORBIDDEN), (
        f"{path} imports a web framework; hsc/rig must run without a server")


def test_hsc_analysis_modules_do_not_import_the_rig_layer():
    """Dependencies point one way: rig -> analysis, never back."""
    for path in Path("hsc").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "from hsc.rig" not in text and "import hsc.rig" not in text
        assert "from hsc.api" not in text and "import hsc.api" not in text
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `uv run python -m pytest tests/test_layering.py -v`
Expected: pass if the earlier tasks respected the constraint. If it fails, fix
the import — do not relax the test.

- [ ] **Step 3: Write the entry point**

```python
# hsc/api/__main__.py
#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Run the rig service.

    uv run python -m hsc.api --host 100.x.y.z --port 8000

Binds to the Tailscale address in production. There is no application-level
authentication: the tailnet is the security boundary, so anyone on it can fire
the injector.
"""

import argparse
from pathlib import Path

import uvicorn

from hsc.api.app import RigServices, create_app
from hsc.app_paths import data_root
from hsc.hardware.imv import ImvCamera
from hsc.rig.events import EventBus
from hsc.rig.importer import import_measure_root
from hsc.rig.jobs import JobManager, RigPaths
from hsc.rig.lease import ControlLease
from hsc.rig.store import RunStore
from hsc.rig.worker import CameraWorker


def build(data=None, spa=None, cors=()):
    root = Path(data or data_root())
    paths = RigPaths(captures=root / "captures",
                     injections=root / "injection images",
                     measures=root / "measure")
    store = RunStore(root / "rig.db")
    import_measure_root(paths.measures, store)
    bus = EventBus()
    worker = CameraWorker(ImvCamera(), bus, paths.captures)
    return create_app(RigServices(
        store=store, jobs=JobManager(worker, store, bus, paths),
        lease=ControlLease(), bus=bus, paths=paths,
        spa_dir=Path(spa) if spa else None, cors_origins=tuple(cors)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data-root", default=None)
    parser.add_argument("--spa", default=None, help="built frontend directory")
    parser.add_argument("--cors", action="append", default=[],
                        help="allowed browser origin; repeatable")
    args = parser.parse_args()
    uvicorn.run(build(args.data_root, args.spa, args.cors),
                host=args.host, port=args.port)


if __name__ == "__main__":
    main()
```

`build()` is separated from `main()` so it can be covered; `main()` itself is
argument parsing plus a `uvicorn.run` call.

- [ ] **Step 4: Run the full suite with coverage**

Run:
```powershell
uv run python -m pytest --cov=hsc.hardware --cov=hsc.rig --cov=hsc.api --cov-report=term-missing --cov-fail-under=100
```
Expected: 100%. Any uncovered line is either a missing test or code that should
not exist — fix by adding the test, not by widening the omit list.

- [ ] **Step 5: Document and commit**

Add to `CLAUDE.md` under the module map:

```markdown
- **`hsc/hardware/`** — the seam between rig code and the vendor SDK.
  `device.py` is the protocol; `imv.py` is the real adapter and the ONLY file
  excluded from coverage — a test parses it and fails if it grows any logic;
  `fake.py` replays a saved burst and is what every test above the seam runs
  against, including faults (dropped frames, wrong ROI) that used to be
  reproducible only on the rig.
- **`hsc/rig/`** — the service: one camera worker, piston pipeline jobs with
  phases and cancellation, the single-controller lease, the event bus and the
  SQLite store. Imports no web framework (asserted by `tests/test_layering.py`)
  so the whole pipeline is testable without a server.
- **`hsc/api/`** — FastAPI over `hsc/rig/`: REST, `/ws/events` (JSON) and
  `/ws/preview` (binary JPEG), and the `RuntimeError` -> error-code mapping
  that lets the UI show the lighting numbers next to a failed capture.
  Run with `uv run python -m hsc.api --host <tailscale-ip>`.
```

```bash
git add hsc/api/__main__.py tests/test_layering.py CLAUDE.md pyproject.toml
git commit -m "feat: rig service entry point, layering guard, coverage gate"
```

---

### Task 16: Retire the Tkinter app

Operator decision, 2026-08-15: Tk is deleted at the end of slice 2, as the spec
says. Do this **last**, after Task 15 is green.

**Know what this costs before starting.** Deleting the GUI removes the only
driver for two capabilities the API does not yet have, because slices 0–2
implement the piston pipeline only:

- **Monitor mode loses its driver.** `hsc/monitor.py` and `hsc/frame_writer.py`
  are used *only* by `gui/camera_worker.py`. **Keep both modules** — they are
  camera-free, have their own tests and a CLI (`python -m hsc.monitor <run>
  --compare`) — but nothing can start a monitoring session until a later slice.
- **Interactive calibration and reference-line drawing go.** `calibrate_ui.py`
  and `reference_ui.py` are Tk dialogs, rebuilt in React in slice 5. The
  non-interactive paths survive: `python -m hsc.calibrate_scale <still>
  --ref-mm 5 --roi1 ... --roi2 ...`, Auto Calibrate via `auto_calibrate_image`,
  and `set_reference_from_image`. Git history holds the dialogs for the port.
- **Spray-angle capture** must go via `python -m hsc.capture_image --burst`,
  then the analysis CLIs.

**Files:**
- Delete: `hsc/gui/` (12 files), `hsc/capture_gui.py`, `hsc/calibrate_ui.py`,
  `hsc/reference_ui.py`, `run_gui.py`
- Delete: `tests/test_gui_structure.py`, `tests/test_piston_gui_wiring.py`,
  `tests/test_monitor_wiring.py`, `tests/test_smart_dispatch.py`
- **Trim, do not delete:** `tests/test_auto_pick.py`, `tests/test_jet_in_rect.py`,
  `tests/test_ref_lines_toggle.py`, `tests/test_v2_toggle.py`
- Modify: `CLAUDE.md`, `packaging/HighSpeedCamera.spec`, `pyproject.toml`

- [ ] **Step 1: Separate the analysis assertions from the GUI ones**

Those four test files assert analysis behaviour but reach it through GUI
symbols. For each, run it and read it:

```powershell
uv run python -m pytest tests/test_auto_pick.py tests/test_jet_in_rect.py tests/test_ref_lines_toggle.py tests/test_v2_toggle.py -v
```

Keep every assertion about `measure_angle` / `measure_folder` output. Replace
GUI plumbing (`CaptureGui`, Tk variables, `inspect.getsource(layout)`) with
direct calls — e.g. a test that drove `auto_pick_var` becomes a direct
`measure_folder(..., auto_pick=True)` call. If a test asserts *only* GUI
wiring, delete that test function alone.

- [ ] **Step 2: Verify the analysis suite is intact before deleting anything**

```powershell
uv run python -m pytest -q
```
Record the count. It must drop by exactly the number of GUI-only tests removed
— any other drop means analysis coverage was lost in Step 1.

- [ ] **Step 3: Delete the Tk code**

```powershell
git rm -r hsc/gui
git rm hsc/capture_gui.py hsc/calibrate_ui.py hsc/reference_ui.py run_gui.py
git rm tests/test_gui_structure.py tests/test_piston_gui_wiring.py tests/test_monitor_wiring.py tests/test_smart_dispatch.py
```

- [ ] **Step 4: Follow the references**

`hsc/gui/config.py` held constants other modules may import (`INJECTION_DIR`,
`MEASURE_DIR`, `PAD_BEFORE`, `PAD_AFTER`, `CAPTURE_ROIS`, `ROI_FPS`,
`PISTON_ASPECT`). Find every user and move the survivors into `hsc/rig/paths.py`:

```powershell
Select-String -Path "hsc\*.py","hsc\rig\*.py","hsc\api\*.py","tests\**\*.py" -Pattern "gui\.config|gui import config"
```

Update `packaging/HighSpeedCamera.spec` (its entry point is `run_gui.py`) — the
frozen build now targets `hsc.api`, or is dropped from this slice if the web
build is not yet packaged. Remove the `--selftest` reference from `CLAUDE.md`.

- [ ] **Step 5: Confirm nothing imports Tk**

```powershell
Select-String -Path "hsc\**\*.py","tests\**\*.py" -Pattern "import tkinter|from hsc.gui"
```
Expected: no matches.

- [ ] **Step 6: Full suite and coverage**

```powershell
uv run python -m pytest -q
uv run python -m pytest --cov=hsc.hardware --cov=hsc.rig --cov=hsc.api --cov-fail-under=100 -q
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: retire the Tkinter app, the rig is driven by the API"
```

---

## Self-Review

**Spec coverage:**

| spec requirement | task |
|---|---|
| `CameraDevice` protocol, `Frame` with block_id/timestamp | 1 |
| `FakeCamera` replaying a burst, drop and ROI faults | 2 |
| Thin adapter, single documented exclusion, structural guard | 3 |
| SQLite summary-metrics schema, settings | 4 |
| Importer over existing folders, idempotent | 5 |
| Single-controller lease with TTL | 6 |
| Event fan-out that never blocks the grab thread | 7 |
| Camera worker with the three rig-earned guards | 8 |
| Pipeline with phases + standalone steps, cancellation | 9, 10 |
| FastAPI app, CORS, SPA mount, typed errors | 11 |
| Runs, CSV, media endpoints | 12 |
| Job and lease endpoints, lease-gated commands | 13 |
| `/ws/events` JSON, `/ws/preview` binary | 14 |
| `hsc/rig` imports no web framework | 15 |
| 100% coverage enforced | 15 |

**Not covered by any task, deliberately:** live preview *production* (the
worker publishes `preview` events but nothing yet grabs continuously — that
arrives with slice 4, when a UI exists to watch it), spray-angle and monitor
pipelines, and the calibration and reference dialogs.

**Tk deletion — resolved 2026-08-15.** I argued for deferring it to slice 4,
because deleting Tk at slice 2 removes the only working preview while the
worker's continuous-preview loop is still unwritten. The operator decided in
favour of the spec: **delete at slice 2**, now Task 16. The cost is stated at
the head of that task so it is deliberate rather than discovered — between this
slice and slice 4 there is no preview, no monitor mode, and no interactive
calibration; the rig is driven by the API and the CLIs.

**Type consistency:** `RunRecord` field names match between `store.py`,
`importer.py` and `jobs.py`; `RigPaths(captures, injections, measures)` is used
identically in Tasks 9–15; `BurstResult.output_dir` is the name used by
`jobs._capture`; `PREVIEW_HEADER` is defined once and imported by the test.

**Placeholders:** none. The two implementer notes (summary key availability in
Task 5, preview pause interleaving in Task 14) describe how to verify and what
not to do, rather than deferring a decision.
