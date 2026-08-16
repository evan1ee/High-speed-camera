# Running the rig, and shipping it to another PC

The frozen one-folder Windows app (`dist\HighSpeedCamera\HighSpeedCamera.exe`,
built by `packaging\HighSpeedCamera.spec`) packaged the **Tkinter GUI**, which
was retired on 2026-08-17. Its entry point (`run_gui.py`) no longer exists, so
the spec and `packaging\build_exe.bat` were removed with it. Git history holds
both, and they are the starting point for the next frozen build — which returns
when the React UI exists and there is a web build to bundle beside the service.

Until then the rig runs **from the source checkout**.

## Run the rig service

One time, on the rig PC (installs Python 3.13 + all dependencies into `.venv\`,
pinned by `uv.lock`):

```
uv sync
```

Then:

```
uv run python -m hsc.api --host 100.x.y.z --port 8000
```

Bind to the **Tailscale address** in production. There is no application-level
authentication: the tailnet is the security boundary, so anyone on it can fire
the injector. `--data-root` overrides where `captures\`, `injection images\`,
`measure\` and `rig.db` live (default: `data\` in the checkout); `--spa` serves
a built frontend directory once one exists; `--cors` whitelists a browser
origin during frontend development.

## Analysis without a camera

Measurement needs no SDK and no camera — pure OpenCV/SciPy/scikit-learn on
saved frames — so any PC with the checkout can re-measure an archived run:

```
uv run python -m hsc.piston_track "data\captures\<run>"
uv run python -m hsc.measure_piston "data\injection images\<run>"
uv run python -m hsc.measure_angle "data\injection images\<run>"
uv run python -m hsc.summary "data\measure\<run>" ...
```

## What the rig PC needs

- **For live capture** — the physical high-speed camera plus its USB3 Vision /
  vendor driver. The checkout carries the SDK **runtime DLLs** under `vendor\`
  (`hsc.app_paths.resource_root()`), but the OS-level camera driver comes from
  the camera vendor's own installer.
- **For measurement / video** — nothing beyond `uv sync`.

The scanner binary's checksum is recorded in
`vendor\bin\injection_scan.exe.sha256` (`<hash> *injection_scan.exe`). After
rebuilding it with `native\build_injection_scan.bat`, recompute with
`certutil -hashfile vendor\bin\injection_scan.exe SHA256` and update that file.
