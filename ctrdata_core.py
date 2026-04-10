#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backward compatibility shim — re-exports everything from ctrdata package.

This file exists solely for backward compatibility with code that imports
from ctrdata_core. New code should import from ctrdata directly:

    from ctrdata import CtrdataBridge

All functionality has moved to the ctrdata/ package:
    ctrdata/bridge.py      — CtrdataBridge facade
    ctrdata/process.py     — R subprocess management
    ctrdata/connection.py   — database connection
    ctrdata/search.py      — query generation & trial download
    ctrdata/extract.py     — field discovery & data extraction
    ctrdata/documents.py   — document downloads
"""

# Re-export everything for backward compatibility
from ctrdata import CtrdataBridge

# Alias for code that imports CtrdataCore
CtrdataCore = CtrdataBridge

# Also re-export check_r_environment for legacy tkinter GUI
from ctrdata.process import check_r_environment

__all__ = [
    "CtrdataBridge",
    "CtrdataCore",
    "check_r_environment",
]
