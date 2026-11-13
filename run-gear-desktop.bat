@echo off
rem Gear calculations run here; account facts and prices come from the Pi.
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"
set "TRACKER_CONFIG_FILE=%ROOT%config.gear-desktop.yaml"
pushd "%ROOT%"

if not exist "%PY%" (
    echo [gear] Create a Python 3.12 virtual environment at .venv and install this project.
    goto :fail
)
if not exist "%TRACKER_CONFIG_FILE%" (
    copy /Y "config.gear-desktop.example.yaml" "%TRACKER_CONFIG_FILE%" >nul
    if errorlevel 1 goto :fail
    echo [gear] Created config.gear-desktop.yaml. Set player_id and the Pi read-only token.
    echo [gear] See docs\DEPLOYMENT.md for Pi provisioning.
    goto :fail
)

rem Validate configuration before downloading or building anything. Never print secrets.
"%PY%" -c "from tracker.gear_desktop import load_desktop_settings; load_desktop_settings()"
if errorlevel 1 goto :fail

rem Native builds belong to provisioning, never to routine startup.
"%PY%" -c "from tracker.gear_desktop import load_desktop_settings; from tracker.gear.native.readiness import require_native; s=load_desktop_settings(); require_native() if s.optimization_engine == 'native' and s.optimization_profile == 'combined' else None"
if errorlevel 1 goto :fail

pushd "frontend\gear"
echo [gear] installing locked frontend dependencies
call npm ci
if errorlevel 1 goto :build_fail
echo [gear] building Gear frontend
call npm run build
if errorlevel 1 goto :build_fail
popd

echo [gear] downloading missing gear icons
"%PY%" -u -m tools.capture_gear_icons
if errorlevel 1 goto :fail

echo [gear] starting desktop Gear on the configured private address and port
"%PY%" -m tracker.gear_desktop
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%

:build_fail
popd
:fail
popd
exit /b 1
