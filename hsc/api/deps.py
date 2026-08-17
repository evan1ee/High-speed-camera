#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Shared helpers for the route modules."""


def services_of(app):
    """The :class:`~hsc.api.app.RigServices` this app was built around."""
    return app.state.services
