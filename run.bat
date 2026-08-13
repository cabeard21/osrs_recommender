@echo off
rem OSRS PvP progression tracker -- Windows launcher.
rem
rem The Makefile's targets hardcode the POSIX venv layout (.venv/bin/python), so they
rem cannot run here; this is the Windows equivalent of `make migrate && make run`.
rem
rem One process, one port (SDD section 5): UI at /, sync API at /api/sync, health at
rem /healthz. The bind address comes from config.yaml and has no default (section 11.1).

setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"

rem Run from the repo root: the package is not pip-installed into the venv, so
rem `python -m tracker.app` resolves `tracker` via the working directory.
pushd "%ROOT%"

if not exist "%PY%" (
    echo [run] No virtualenv at .venv\Scripts\python.exe
    echo [run] Create one with:  python -m venv .venv
    goto :fail
)

rem config.yaml is gitignored -- it holds the bearer token shared with the RuneLite
rem plugin (section 11.2), so a fresh clone has to grow its own.
if not exist "config.yaml" (
    echo [run] config.yaml not found -- creating it from config.example.yaml
    copy /Y "config.example.yaml" "config.yaml" >nul
    if errorlevel 1 goto :fail
    "%PY%" -c "import pathlib,secrets; p=pathlib.Path('config.yaml'); p.write_text(p.read_text(encoding='utf-8').replace('CHANGE_ME', secrets.token_urlsafe(32)), encoding='utf-8')"
    if errorlevel 1 goto :fail
    echo [run] Generated a fresh api_token. Copy it into the RuneLite plugin's settings.
    echo [run] Review bind_address before exposing this beyond loopback -- see docs\DEPLOYMENT.md
)

rem A placeholder token is not a token. The app would start and serve /api anyway, which
rem is the exact failure section 11.2 exists to prevent.
findstr /C:"CHANGE_ME" "config.yaml" >nul
if not errorlevel 1 (
    echo [run] config.yaml still contains CHANGE_ME. Set a real api_token first:
    echo [run]     .venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
    goto :fail
)

echo [run] alembic upgrade head
"%PY%" -m alembic upgrade head
if errorlevel 1 goto :fail

echo [run] starting tracker
"%PY%" -m tracker.app
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%

:fail
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" set "RC=1"
popd
exit /b %RC%
