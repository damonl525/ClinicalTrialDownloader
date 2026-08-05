@echo off
chcp 65001 >nul 2>&1
REM ============================================================
REM  Clinical Trial Data Downloader launcher
REM  Uses .venv python (PySide6/pandas installed there)
REM ============================================================

cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo [Error] Virtual environment not found: %VENV_PY%
    echo.
    echo Create and install dependencies first:
    echo   python -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

"%VENV_PY%" "%~dp0main.py" %*

if errorlevel 1 (
    echo.
    pause
)
