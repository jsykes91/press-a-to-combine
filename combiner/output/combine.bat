@echo off
rem ------------------------------------------------------------------
rem  RTF table combiner
rem  First run: makes a private Python environment (.venv) next to this
rem  file and installs pywin32 into it.  After that it just opens the
rem  window.  Extra arguments (e.g. --run ...) are passed to combine.py
rem  and run in this console instead of opening the window.
rem ------------------------------------------------------------------
setlocal
cd /d "%~dp0"
set "VENV=%~dp0.venv"
set "READY=%VENV%\setup_ok.txt"

if exist "%READY%" goto :run

echo Setting up Python for the RTF combiner (first run only)...
set "PYEXE="
where py >nul 2>nul && set "PYEXE=py -3"
if not defined PYEXE (
    python -c "import sys" >nul 2>nul && set "PYEXE=python"
)
if not defined PYEXE (
    echo.
    echo Python 3 was not found. Install it from https://www.python.org/downloads/
    echo ^(tick "Add python.exe to PATH"^), then run combine.bat again.
    pause
    exit /b 1
)

if exist "%VENV%" rmdir /s /q "%VENV%"
%PYEXE% -m venv "%VENV%"
if errorlevel 1 goto :setup_failed
"%VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check --quiet pywin32
if errorlevel 1 goto :setup_failed
"%VENV%\Scripts\python.exe" -c "import tkinter, win32com.client"
if errorlevel 1 goto :setup_failed
echo Set up on %date% %time% > "%READY%"
echo Python is ready.

:run
if "%~1"=="" (
    start "" "%VENV%\Scripts\pythonw.exe" "%~dp0combine.py"
    exit /b 0
)
"%VENV%\Scripts\python.exe" "%~dp0combine.py" %*
exit /b %errorlevel%

:setup_failed
echo.
echo Setting up Python failed - see the messages above.
echo Check the internet connection (pywin32 is downloaded once) and try again.
pause
exit /b 1
