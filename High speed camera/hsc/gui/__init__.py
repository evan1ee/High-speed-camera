"""Tkinter GUI package for the high-speed-camera rig.

The main window class is assembled from one mixin per feature area:

- :mod:`hsc.gui.app`           -- window shell, queue dispatch, entry point
- :mod:`hsc.gui.layout`        -- widget construction, logging plumbing
- :mod:`hsc.gui.capture`       -- preview + Capture/Stop (UI side)
- :mod:`hsc.gui.camera_worker` -- the persistent camera thread (SDK side)
- :mod:`hsc.gui.extraction`    -- Find Injection
- :mod:`hsc.gui.measurement`   -- Measure / Measure Angle Block
- :mod:`hsc.gui.video`         -- Make Video (+ auto-measure chaining)
- :mod:`hsc.gui.calibration`   -- Calibrate Scale / Auto Calibrate / Measure Block
- :mod:`hsc.gui.reference`     -- Set Reference
- :mod:`hsc.gui.config`        -- shared folders/constants + app.log writer
- :mod:`hsc.gui.selftest`      -- headless --selftest (no camera, no Tk)

See :mod:`hsc.gui.app` for the recipe to add a new feature module.
"""

from hsc.gui.app import CaptureGui, main

__all__ = ["CaptureGui", "main"]
