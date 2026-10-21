@echo off
rem Double-click to upgrade the pinned RuneLite client and validate the plugin.
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"
set "RC=1"
if not exist "%PY%" (
    echo Python environment missing: %PY%
    echo Create the app's .venv first. See README.md.
    goto :done
)
"%PY%" "%ROOT%scripts\upgrade_runelite.py" %*
set "RC=%ERRORLEVEL%"
:done
echo.
pause
exit /b %RC%
