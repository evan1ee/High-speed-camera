#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""A burst long enough to contain a measurable stroke, generated rather than
committed -- thousands of BMPs do not belong in git."""
import sys
from pathlib import Path

import cv2
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
