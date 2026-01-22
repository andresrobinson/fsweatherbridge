@echo off
REM FSX Weather Bridge - Run Script (Admin)
REM This script uses the Python installation selected during install
REM Designed to run as administrator

setlocal enabledelayedexpansion

REM Get script directory (important when running as admin)
set "SCRIPT_DIR=%~dp0"
set "CONFIG_FILE=%SCRIPT_DIR%python_config.txt"

if not exist "%CONFIG_FILE%" (
    echo ERROR: Configuration file not found!
    echo Please run install.bat first.
    pause
    exit /b 1
)

REM Read Python path from config (first line only, trim whitespace)
set "PYTHON_PATH="
for /f "usebackq delims=" %%A in ("%CONFIG_FILE%") do (
    set "PYTHON_PATH=%%A"
    goto :found_path
)
:found_path

REM Remove leading/trailing whitespace
set "PYTHON_PATH=!PYTHON_PATH: =!"

if "!PYTHON_PATH!"=="" (
    echo ERROR: Configuration file is empty!
    echo Please run install.bat again to select a Python installation.
    pause
    exit /b 1
)

if not exist "!PYTHON_PATH!\python.exe" (
    echo ERROR: Python installation not found at: !PYTHON_PATH!
    echo.
    echo The path in the config file may be incorrect.
    echo Please run install.bat again to select a different installation.
    pause
    exit /b 1
)

echo Using Python: !PYTHON_PATH!
echo.

REM Change to script directory (critical when running as admin)
cd /d "%SCRIPT_DIR%"

REM Run the application
"!PYTHON_PATH!\python.exe" -m src.main

pause
