#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Clinical Trial Data Downloader — Entry point

Supports --ui flag to choose between PySide6 (default) and legacy tkinter.
"""

import sys
import os
import subprocess
from pathlib import Path


def detect_r_home() -> str | None:
    """Auto-detect R installation path."""
    if "R_HOME" in os.environ:
        path = os.environ["R_HOME"]
        r_exe = os.path.join(path, "bin", "R.exe" if sys.platform == "win32" else "R")
        if os.path.exists(r_exe):
            return path

    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\R-core\R")
            path, _ = winreg.QueryValueEx(key, "InstallPath")
            if path and os.path.exists(path):
                return path
        except OSError:
            pass

        for base in [r"C:\Program Files\R", r"C:\Program Files (x86)\R"]:
            if os.path.exists(base):
                versions = sorted(Path(base).glob("R-*"), reverse=True)
                if versions:
                    return str(versions[0])

    try:
        result = subprocess.run(["R", "RHOME"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return None


def setup_r_environment():
    """Set R environment variables."""
    r_home = detect_r_home()
    if r_home:
        os.environ["R_HOME"] = r_home
        print(f"R_HOME: {r_home}")
    else:
        print("Warning: R installation not found")

    os.environ["LANG"] = "en_US.UTF-8"


def run_pyside6_ui():
    """Launch PySide6 modern UI."""
    from ui.app import create_app
    from ui.main_window import MainWindow

    app, theme = create_app()
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


def run_legacy_ui():
    """Launch legacy tkinter UI."""
    from ctrdata_gui import CtrdataGUI
    gui = CtrdataGUI()
    gui.run()


def main():
    from core.constants import APP_NAME, APP_VERSION

    # Parse --ui flag
    ui_mode = "pyside6"
    if "--ui" in sys.argv:
        idx = sys.argv.index("--ui")
        if idx + 1 < len(sys.argv):
            ui_mode = sys.argv[idx + 1]

    print(f"{APP_NAME} v{APP_VERSION} 启动中... (UI: {ui_mode})")
    setup_r_environment()

    if ui_mode == "legacy":
        run_legacy_ui()
    else:
        try:
            run_pyside6_ui()
        except ImportError as e:
            print(f"PySide6 not available ({e}), falling back to legacy UI...")
            run_legacy_ui()


if __name__ == "__main__":
    main()
