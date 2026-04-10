#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ctrdata package — R ctrdata package bridge for Python.

Provides CtrdataBridge class for interacting with clinical trial
registries via the R ctrdata package.

Submodules:
    bridge       — CtrdataBridge facade class
    process      — R subprocess management and execution
    connection   — database connection and query history
    search       — query generation, trial download, URL parsing
    extract      — field discovery and data extraction
    documents    — document download with resume support
"""

from ctrdata.bridge import CtrdataBridge

# Backward compatibility alias
CtrdataCore = CtrdataBridge

__all__ = ["CtrdataBridge", "CtrdataCore"]
