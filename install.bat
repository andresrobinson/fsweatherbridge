@echo off
REM FSX Weather Bridge Installation Script
REM This script detects installed Python versions and allows user selection

setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "CONFIG_FILE=%SCRIPT_DIR%python_config.txt"

echo ========================================
echo FSX Weather Bridge - Installation
echo ========================================
echo.

REM Detect Python installations
echo Detecting Python installations...
echo.

set "PYTHON_COUNT=0"
set "PYTHON_LIST="

REM Check common Python installation locations
for %%P in (
    "C:\Python*"
    "C:\Program Files\Python*"
    "C:\Program Files (x86)\Python*"
    "%LOCALAPPDATA%\Programs\Python\Python*"
    "%APPDATA%\Python\Python*"
) do (
    if exist %%P (
        for /d %%D in (%%P) do (
            if exist "%%D\python.exe" (
                REM Check if it's 32-bit
                "%%D\python.exe" -c "import sys; exit(0 if sys.maxsize <= 2**32 else 1)" 2>nul
                if !errorlevel! equ 0 (
                    set /a PYTHON_COUNT+=1
                    set "PYTHON_!PYTHON_COUNT!=%%D"
                    echo [!PYTHON_COUNT!] %%D ^(32-bit^)
                    set "PYTHON_LIST=!PYTHON_LIST!%%D "
                ) else (
                    echo [SKIP] %%D ^(64-bit - not compatible^)
                )
            )
        )
    )
)

REM Also check PATH
for %%P in (python.exe python3.exe) do (
    where %%P >nul 2>&1
    if !errorlevel! equ 0 (
        for /f "tokens=*" %%W in ('where %%P') do (
            set "PYTHON_PATH=%%W"
            for %%D in ("!PYTHON_PATH!") do set "PYTHON_DIR=%%~dpD"
            set "PYTHON_DIR=!PYTHON_DIR:~0,-1!"
            
            REM Check if already in list
            set "FOUND=0"
            for /l %%I in (1,1,!PYTHON_COUNT!) do (
                if "!PYTHON_%%I!"=="!PYTHON_DIR!" set "FOUND=1"
            )
            
            if !FOUND! equ 0 (
                REM Check if 32-bit
                "!PYTHON_PATH!" -c "import sys; exit(0 if sys.maxsize <= 2**32 else 1)" 2>nul
                if !errorlevel! equ 0 (
                    set /a PYTHON_COUNT+=1
                    set "PYTHON_!PYTHON_COUNT!=!PYTHON_DIR!"
                    echo [!PYTHON_COUNT!] !PYTHON_DIR! ^(32-bit, from PATH^)
                )
            )
        )
    )
)

if !PYTHON_COUNT! equ 0 (
    echo.
    echo ERROR: No 32-bit Python installations found!
    echo.
    echo FSX Weather Bridge requires 32-bit Python.
    echo Please install Python 32-bit from https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo.
echo Please select a Python installation:
set /p "SELECTION=Enter number (1-%PYTHON_COUNT%): "

REM Validate selection
set "SELECTED_PYTHON="
for /l %%I in (1,1,!PYTHON_COUNT!) do (
    if "!SELECTION!"=="%%I" (
        set "SELECTED_PYTHON=!PYTHON_%%I!"
    )
)

if not defined SELECTED_PYTHON (
    echo Invalid selection!
    pause
    exit /b 1
)

echo.
echo Selected: !SELECTED_PYTHON!
echo.

REM Save selection to config file (overwrite, no trailing spaces)
>"%CONFIG_FILE%" echo !SELECTED_PYTHON!

REM Verify the file was written correctly
set "VERIFY_PATH="
for /f "usebackq delims=" %%A in ("%CONFIG_FILE%") do set "VERIFY_PATH=%%A"

if "!VERIFY_PATH!"=="!SELECTED_PYTHON!" (
    echo Configuration saved successfully to: %CONFIG_FILE%
    echo Saved path: !SELECTED_PYTHON!
) else (
    echo WARNING: Configuration file may not have been written correctly.
    echo Attempting alternative method...
    (
        echo !SELECTED_PYTHON!
    ) > "%CONFIG_FILE%"
    echo Configuration saved to: %CONFIG_FILE%
)
echo.

REM Install dependencies
echo Installing dependencies...
echo.

"%SELECTED_PYTHON%\python.exe" -m pip install --upgrade pip

REM Install from requirements.txt if it exists, otherwise install individually
if exist "%SCRIPT_DIR%requirements.txt" (
    echo Installing from requirements.txt...
    "%SELECTED_PYTHON%\python.exe" -m pip install -r "%SCRIPT_DIR%requirements.txt"
) else (
    echo Installing dependencies individually...
    "%SELECTED_PYTHON%\python.exe" -m pip install fastapi "uvicorn[standard]" aiohttp pydantic pystray pillow
)

if !errorlevel! neq 0 (
    echo.
    echo ERROR: Failed to install dependencies!
    pause
    exit /b 1
)

echo.
echo ========================================
echo Installation complete!
echo ========================================
echo.
echo Python path saved to: %CONFIG_FILE%
echo You can now run the application using run.bat
echo.
pause
