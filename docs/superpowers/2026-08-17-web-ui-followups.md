# Web UI backend — carried follow-ups

Recorded 2026-08-17, at the end of slices 0–2. Everything here was found by
review, judged non-blocking for merge, and deliberately not fixed. It is written
down because the reasons are the expensive part.

## Would produce a wrong number on the rig

**A split capture/measure loses the truncation warning.** `truncated` and
`dropped` reach the run row through `job.result`, which is per-job. The chained
`piston_run` pipeline carries them; but the API also accepts `capture`, `find`
and `measure` as separate kinds, and a standalone `measure` job's
`_record_from` sees an empty result, so both columns land `NULL` —
indistinguishable from a genuine re-analysis. The evidence survives in
`piston_capture.json` (`truncated` plus `grab_status`), but nothing reads it
back, and a standalone measure job does not even know its `source_dir`.
An operator who captures and measures as two jobs therefore gets a shortened
stroke and a plausible, quietly low peak speed — the exact failure the flag
exists to prevent. Fix when the UI can drive split jobs: have `measure` read
the capture meta, or refuse to record a run whose capture provenance is unknown.

**A timeout and a genuine SDK fault are still indistinguishable.** Every non-OK
grab status ends the burst as `truncated`. Since the fix wave the status itself
is recorded (`BurstResult.grab_status`, `piston_capture.json`, the
`capture_done` event) rather than flattened to `None`, so the evidence survives
— but separating "the camera timed out" from "the camera failed" needs vendor
error constants, and reading those means touching the analysis layer.

**Nothing validates `exposure_us`.** The Tk selector constrained the choice to
950 µs at 320×240 and 550 µs at 320×120; the API accepts any number a browser
field can type. Exceeding the cap halves the frame rate — which is precisely the
class of bug (2026-08-13, two lost rig runs) that motivated this whole branch.
A `CaptureConfig.__post_init__` check is the natural home.

## Capability regressions from retiring Tk

**There is no persistent log.** The Tk build mirrored every message to
`data_root()/app.log`, which this repo's own notes call "the only persistent
record". The three new packages contain no logging at all: job failure reasons,
the dropped-frame warning, and `measure_piston`'s calibration-size-mismatch
warning exist only for whoever was connected, and the event bus drops events by
design under load. `EventBus.history()` exists but no route exposes it. After
the first overnight failure the operator has nothing to read. This is the
largest single regression in the branch.

Related: `JobManager.close()` correctly refuses to close the camera while a job
still holds it, but reports that refusal only to the event bus — whose
subscribers are the very sockets being torn down at shutdown. The behaviour is
right; the reporting will not reach anyone.

**Also gone, deliberately:** the spray-angle workflow has no route (CLI only),
Monitor mode has no driver, interactive calibration and reference drawing are
gone until the React dialogs land, and packaging was dropped rather than
repointed — `packaging/` and `pyinstaller` are removed, `dist/` left untouched
in case it is the deployed copy. `CLAUDE.md`'s Retired section records what a
future packaging spec must redo, including the load-bearing `vendor/`
relative-path requirement.

## Contracts that are true today and fragile tomorrow

**`Grab.build` promises more than the real adapter delivers.** `device.py`'s
docstring says `build` "is `None` unless the grab succeeded", and `FakeCamera`
honours that. `ImvCamera` cannot: it may not branch, so it always passes a
`partial`. Nothing reads `build` without checking `.ok` first, so there is no
live defect — but an author who trusts the docstring and writes
`if grab.build is not None: grab.build()` will call `string_at` on an invalid
buffer on the real camera. `.ok` is the only safe gate; the sentence should say
so.

**The no-logic guard is still blind to the technique that defeated it.**
`test_imv_has_no_logic.py` forbids `If`/`For`/`While`/comprehensions/`BinOp`/
`BoolOp`/`Compare`/`IfExp`/`Try` — but not `ast.Dict` or `ast.Lambda`. A status
branch was once laundered through `{...}.get(x, default)` and passed. That
instance was removed by moving the decision into the worker, but the same trick
would pass again.

**`measure_dir` normalisation lives in the two callers, not the table.** Both
writers now `.resolve()`, but `RunStore.run_by_measure_dir` looks up with a bare
string, so it does not share the rule — the inverse of the reasoning used for
the `COALESCE` fix, where the rule was deliberately put in the table because it
is a property of the table. No production caller today.

**`COALESCE` cannot un-learn a value.** A writer can raise or replace any value
it holds, never clear one. That is what protects pipeline-only columns from the
importer's rescan. The one reachable consequence: if a `*_speed.csv` is
regenerated in place with a metric absent, the next rescan updates the stroke
numbers while the row keeps the older jet speed and pressure, computed from
different inputs — a mixed-provenance row rather than a crash.

## Smaller carried items

- Three error-body shapes on one API: `{"code","message"}` from the middleware,
  `{"detail": str}` from `HTTPException`, `{"detail": [...]}` from pydantic.
  Roughly half the 4xx surface bypasses the typed codes. Unify with the frontend.
- `JobManager` never prunes `_jobs`/`_cancels`/`_threads`; `_camera_job()` scans
  all jobs per submit and each entry holds a dead `Thread`.
- `job.progress` is mutated without publishing and never reset between phases,
  so each phase's first event carries the previous phase's 1.0.
- `JobBody.params` is unvalidated: `{"kind": "capture", "params": {}}` returns
  200 then fails asynchronously with `KeyError('width')`. `duration_s` is
  likewise unbounded, which is what makes the shutdown join timeout reachable.
- Coverage is statement-only; `branch = true` is not set.
- `pydantic` is imported directly but not declared in `pyproject.toml`.
- `hsc/frame_writer.py` has no importer and no CLI — reachable only from its
  tests. `hsc/monitor.py` at least keeps its `--compare` CLI.
- `hsc/calibrate_scale.py:24` still points at the deleted `calibrate_ui.py`.
  Left alone because editing it would be the first modification to an analysis
  module in the whole branch; fix it in a commit that touches nothing else.
- `close(timeout=30)` joins threads sequentially, so shutdown is worst-case
  n × 30 s.

## Not a defect, but know it

`resolve_timebase` discards `FakeCamera`'s synthesised ticks, because the worker
measures wall-clock fps (really BMP read speed) which cannot agree with the
fake's rate. So no test above the hardware seam can validate a *time* — the
end-to-end test asserts geometry only, deliberately. Likewise `stroke_mm`
depends on a gitignored, machine-local `settings/calibration.json`, so it can
never be asserted on a clean checkout.

`data\rig.db` has no migration, per this repo's explicit no-backward-
compatibility rule. A database from an earlier build of this branch must be
deleted; the failure if it is not is a loud `OperationalError`, not silent.
