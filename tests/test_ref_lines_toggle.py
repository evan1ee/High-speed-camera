"""The "Ref. lines on output" checkbox: measure output images can omit the
yellow tip line + blue centerline while keeping the red rectangle."""

import inspect

import numpy as np

from hsc import reference_lines


def _ref_with_rect():
    """A synthetic reference: vertical tip line at x=200, horizontal
    centerline, and a rectangle."""
    ref = reference_lines.build_reference((200, 80), (200, 160), (320, 240))
    reference_lines.attach_rectangle(ref, mm_per_px=0.1)
    return ref


def _color_present(img, bgr):
    """True if any pixel is near ``bgr`` (LINE_AA blends edge pixels)."""
    diff = np.abs(img.astype(int) - np.array(bgr, dtype=int))
    return bool(np.any(np.all(diff < 60, axis=-1)))


def test_draw_reference_lines_off_keeps_rect_only():
    ref = _ref_with_rect()
    img = np.zeros((240, 320, 3), dtype=np.uint8)
    reference_lines.draw_reference(img, ref, lines=False)
    assert not _color_present(img, reference_lines.YELLOW)
    assert not _color_present(img, reference_lines.BLUE)
    assert _color_present(img, reference_lines.RED)


def test_draw_reference_default_draws_everything():
    ref = _ref_with_rect()
    img = np.zeros((240, 320, 3), dtype=np.uint8)
    reference_lines.draw_reference(img, ref)
    assert _color_present(img, reference_lines.YELLOW)
    assert _color_present(img, reference_lines.BLUE)
    assert _color_present(img, reference_lines.RED)


def test_measure_folder_accepts_ref_lines():
    from hsc import measure_angle

    sig = inspect.signature(measure_angle.measure_folder)
    assert "ref_lines" in sig.parameters
    assert sig.parameters["ref_lines"].default is True
    src = inspect.getsource(measure_angle.measure_folder)
    assert "lines=ref_lines" in src


def test_gui_checkbox_wired():
    """Layout has the checkbox, measurement owns the var (default OFF) and
    passes it through the worker into measure_folder."""
    import hsc.gui.layout as layout
    import hsc.gui.measurement as measurement

    layout_src = inspect.getsource(layout)
    assert "Ref. lines on output" in layout_src
    assert "self.ref_lines_var" in layout_src

    meas_src = inspect.getsource(measurement)
    assert "self.ref_lines_var = tk.BooleanVar(value=False)" in meas_src
    assert "ref_lines=" in inspect.getsource(measurement.MeasurementMixin._measure_worker)
