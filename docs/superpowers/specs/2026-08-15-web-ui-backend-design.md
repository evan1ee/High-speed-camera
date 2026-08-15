# Web UI — backend design (slices 0–2)

Status: approved 2026-08-15. Covers the hardware seam, the rig service layer,
and the HTTP/WebSocket API. The React frontend, interactive setup dialogs and
deployment hardening are separate specs.

## Why

The rig is driven by a Tkinter app (`hsc/gui/`). It works, but it can only run
on the machine physically attached to the camera, its state lives in widgets,
and its hardware paths cannot be tested — the frame-rate bug that cost two rig
runs on 2026-08-13 was invisible to the suite because no test could execute
`_do_piston_capture`.

The goal is a browser UI over a Python service, reachable across a tailnet,
with results in a database and a test suite that covers everything above the
SDK boundary.

## Scope

Full replacement of the Tk app, decomposed into six slices. **This spec covers
slices 0–2**; each later slice gets its own.

**Pipelines built first.** The job model is generic, but slices 0–2 implement
only the **piston** pipeline end to end. Spray angle (`capture → find
injection → measure angle → video`) and monitor mode are the same shape and
follow once the pattern is proven against the rig; building all three before
any of them is validated would triple the surface under test for no earlier
feedback. Calibration and Set Reference are inherently interactive — ROI
dragging, line drawing — so they belong with the frontend in slice 5.

| # | slice | delivers |
|---|-------|----------|
| 0 | Hardware seam | everything below becomes testable without the rig |
| 1 | Rig service + SQLite | headless pipeline, jobs, persisted results |
| 2 | FastAPI + WebSocket | remote control, live preview, typed errors |
| 3 | React — results viewing | first browser value |
| 4 | React — rig control | Tk feature parity |
| 5 | React — calibration / reference dialogs | Tk retires |
| 6 | Deployment + E2E hardening | production |

## Decisions

Each was chosen deliberately; the rejected option is recorded because the
reason matters more than the choice.

| decision | chosen | over |
|---|---|---|
| Web scope | full replacement | view-only, or phased |
| Concurrency | single control lease, others observe | last-claim-wins, single client, unrestricted |
| Persistence | summary metrics in SQLite, per-frame CSV on disk | full per-frame in DB, or DB as index |
| Job model | pipeline with phases **and** standalone steps | steps only, or pipeline only |
| Coverage | thin adapter excluded, 100% above it | mock the SDK, or hardware-in-the-loop |
| Preview | two WebSockets (JSON events, binary frames) | one mixed socket, or MJPEG |
| Serving | FastAPI serves the SPA; Vercel optional | either alone |
| Tk | retire once the API works | freeze until parity, or refactor onto the service |

**Concurrency.** The camera is a singleton and a browser invites a second tab.
A stale tab must not be able to fire the injector, so control is a lease and
everyone else observes.

**Persistence.** Per-frame rows would fit comfortably in SQLite, but keeping
them as CSV means the existing ~90 run folders import with no schema
translation — `hsc/summary.read_run()` already parses exactly the summary block
being stored.

**Coverage.** `IMV_GetFrame` cannot be covered without a camera. Mocking the
ctypes layer would report 100% while asserting against a mock of the vendor
DLL — passing tests, failing rig. Instead the adapter holds no logic and is
excluded by an explicit list.

**Tk.** Retiring it early means no GUI between slices 2 and 4; the rig stays
drivable via `capture_image --burst`, the analysis CLIs, and the API itself.
Accepted by the operator.

## Architecture

```
hsc/                   analysis core — UNCHANGED, already camera-free and Tk-free
  piston_track  measure_piston  measure_angle  summary  calibrate_scale  ...

hsc/hardware/          slice 0
  device.py            CameraDevice protocol, Frame, CaptureConfig
  imv.py               real SDK adapter — pure DLL calls, no logic, coverage-excluded
  fake.py              replays a saved burst; deterministic; used by every test

hsc/rig/               slice 1 — extracted from gui/camera_worker.py
  worker.py            single persistent camera thread + command queue
  jobs.py              pipeline and step jobs, phases, cancellation, events
  store.py             SQLite schema, importer over existing folders
  lease.py             single-controller lease, observers

hsc/api/               slice 2
  app.py               FastAPI; serves built SPA; CORS from config
  routes_*.py          REST
  ws_events.py         JSON: commands, progress, log, status, lease
  ws_preview.py        binary JPEG frames
  errors.py            RuntimeError -> typed code mapping
```

Two invariants:

- **`hsc/` analysis modules are not modified.** They are validated against rig
  data across 4 U–40 U on two injectors; changing them to suit a UI would put
  that at risk for no gain.
- **`hsc/rig/` imports no web framework.** The whole pipeline runs and is
  tested without starting a server.

## Slice 0 — hardware seam

```python
class CameraDevice(Protocol):
    def open(self, index: int) -> None: ...
    def configure(self, cfg: CaptureConfig) -> None: ...   # ROI, exposure, format
    def start(self) -> None: ...
    def grab(self, timeout_ms: int) -> Frame | None: ...
    def clone(self, frame: Frame) -> Frame: ...            # defer_save path
    def release(self, frame: Frame) -> None: ...
    def save(self, frame: Frame, path: Path) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...

@dataclass(frozen=True)
class Frame:
    width: int
    height: int
    block_id: int      # gaps reveal dropped frames
    timestamp: int     # the only honest basis for a speed axis
    pixels: memoryview
```

`block_id` and `timestamp` belong on `Frame` because the entire time base
depends on them — the camera free-runs and `AcquisitionFrameRate` reports a
stale stored value (525 while bursts run at ~1048 fps).

**`FakeCamera`** replays a saved burst folder, so tests run against real rig
pixels — the data that exposed the collar, the illumination falloff and the
4 U drift. It synthesises `block_id`/`timestamp` at a chosen rate, making
timebase inference and dropped-frame handling testable. Committed fixtures are
one short burst; the large folders stay local.

**Honest exclusion.** `hsc/hardware/imv.py` is the only excluded file, listed
in `pyproject.toml`. A structural test parses it and fails if it contains
branching or computation — only attribute access, SDK calls, and raising on
error codes. Logic cannot migrate into the untested file without breaking the
build. The repo already uses this pattern
(`test_piston_capture_does_not_touch_the_spray_capture_path`).

## Slice 1 — rig service

**Worker.** `gui/camera_worker.py` lifted out of Tk: one thread owning the open
handle, driven by a command queue rather than `threading.Event` flags. The
burst loops move across intact, including the pre-burst `configure_camera`
(without which a burst inherits the preview's ROI timing and runs at the wrong
frame rate), the frame-size check, and per-frame `blockId`/`timeStamp`
recording. Preview frames feed a JPEG encoder; everything else emits events.

**Jobs.** A `PistonRun` pipeline runs `capture → find → measure → video` as
phases; each step also exists standalone for re-analysis. Cancellation reuses
the `progress(done, total)` callback every long `hsc/` operation already
accepts — it becomes the cancellation checkpoint, so no analysis module
changes. Jobs survive client disconnect and are persisted.

**Schema.**

- `runs` — one row per measured run: label, kind, timestamps, folder paths,
  ROI/exposure/fps/timebase, `mm_per_px` and scale source, barrel/orifice/
  density, and the summary metrics (stroke px and mm, duration, mean and peak
  speed, peak jet speed and pressure, `unstable_frames`).
- `jobs` — id, type, params, state, phase, timings, error, linked run.
- `settings` — rig config currently held in Tk widgets (ROI, exposure, capture
  time, barrel/orifice diameters, run label).

**Importer.** Scans `data/measure/*`, reads the summary block via
`summary.read_run()` and fps/timebase from `piston_meta.json`. Keyed on the
measure folder, so it is idempotent and can run at startup — picking up runs
captured outside the app.

**Lease.** Single controller, TTL with heartbeat, released on disconnect,
explicit handover. It lives here rather than in the API layer so it is testable
without a server. Control commands from a non-holder are rejected with a typed
error, never silently ignored.

## Slice 2 — API

```
GET     /api/health
GET     /api/camera/status
GET/PUT /api/settings
GET     /api/runs?kind=&label=&limit=
GET     /api/runs/{id}
GET     /api/runs/{id}/csv                  streamed from disk
GET     /api/runs/{id}/media/{name}         plots, video, annotated frames
POST    /api/runs/import
POST    /api/summary                        cross-run stats over selected ids
POST    /api/jobs                           {type, params} -> job id
GET     /api/jobs/{id}
POST    /api/jobs/{id}/cancel
POST    /api/lease/{claim,release,heartbeat}
```

**`/ws/events`** — JSON. Server→client: `hello` (role, lease holder, camera
status), `lease`, `job` (state/phase/progress), `log`, `status`, `run`, `error`.
Client→server: heartbeat. Every client receives all events; only commands are
lease-gated.

**`/ws/preview`** — binary: fixed header (sequence, width, height, timestamp,
flags) then JPEG bytes. Client→server JSON `{fps, paused}`, so a slow observer
throttles itself without affecting the controller. Separate socket so a backed
-up preview never delays job events.

**Typed errors.** `hsc/` raises rich diagnostics — contrast too low, no
measurable injection, no barrel interior, no frame timing. Each maps to a code
(`CONTRAST_TOO_LOW`, `NO_INJECTION`, `NO_TIMEBASE`, `LEASE_REQUIRED`,
`CAMERA_BUSY`) carrying its measured values, so the UI can show the lighting
numbers beside a failed capture. Message text remains the human fallback.

**Serving.** FastAPI mounts the built SPA at `/` when `dist/` exists; CORS
origins come from config, so a Vercel deployment is a config entry rather than
a code change. The frontend's API base URL is configured, same-origin by
default.

**Process and security.** One `uvicorn` process on the rig PC bound to the
Tailscale interface. No app-level auth — the tailnet is the boundary. Stated
plainly because it is a real decision: anyone on the tailnet can fire the
injector.

## Testing

| layer | approach | coverage |
|---|---|---|
| `hsc/` analysis | existing suite, 202 tests, real rig fixtures | already high |
| `hsc/hardware/imv.py` | structural test only (no logic permitted) | excluded |
| `hsc/hardware/fake.py` | unit | 100% |
| `hsc/rig/` | unit + integration against `FakeCamera` | 100% |
| `hsc/api/` | `httpx.AsyncClient` + `TestClient`, WS via `websockets` | 100% |

The suite must run with no camera attached and no server started. Integration
tests drive a whole pipeline job end to end against `FakeCamera` and assert the
persisted run row — the first time the capture path is covered at all.

Coverage is enforced in CI with `--cov-fail-under=100` scoped to `hsc/hardware`,
`hsc/rig` and `hsc/api`, with the single documented omission.

## Risks

1. **Extraction of `camera_worker` is the risky step.** It holds behaviour
   earned from rig failures — pre-burst reconfiguration, size verification,
   timestamp recording, monitor-mode flushing. Mitigation: extract before
   deleting any Tk code, and cover each behaviour with a `FakeCamera` test
   *before* the move, so the tests fail if the move loses something.
2. **No GUI between slices 2 and 4.** Accepted; CLI and API remain.
3. **JPEG encoding cost on the rig PC.** Preview is 320×240 at ~25 fps, which
   is minor, but it shares a process with capture. Mitigation: encode off the
   grab thread, drop frames under load rather than queueing — the grab loop
   must never block.
4. **100% coverage is a ratchet.** It can be met by writing tests that assert
   nothing. Mitigation: the structural test on the adapter, and review of what
   integration tests actually assert.

## Out of scope

React frontend, calibration and reference-line UI, Vercel deployment,
authentication, multi-rig support, and any change to `hsc/` analysis modules.
