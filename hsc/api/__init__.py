#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""HTTP over the rig service.

Thin on purpose: everything this layer exposes is implemented and tested in
:mod:`hsc.rig`, which runs with no server. Imports go one way only -- the rig
layer never imports this package.
"""
