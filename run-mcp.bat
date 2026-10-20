@echo off
rem Start the private MCP sidecar and its existing Secure MCP Tunnel profile.
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"
set "TUNNEL_CLIENT=D:\ChatGPT_MCP_Tunnel\tunnel-client.exe"
if defined OSRS_TUNNEL_CLIENT set "TUNNEL_CLIENT=%OSRS_TUNNEL_CLIENT%"

if not exist "%PY%" (
    echo [run-mcp] No virtual environment at .venv\Scripts\python.exe
    echo [run-mcp] Create one with: python -m venv .venv
    exit /b 1
)
if not exist "%TUNNEL_CLIENT%" (
    echo [run-mcp] Tunnel client not found: %TUNNEL_CLIENT%
    echo [run-mcp] Set OSRS_TUNNEL_CLIENT to the full path of tunnel-client.exe.
    exit /b 1
)

pushd "%ROOT%"
if errorlevel 1 exit /b 1

"%PY%" -c "import sys; from tracker.config.settings import load_settings; s = load_settings(); sys.exit(0 if s.mcp.enabled and s.mcp.player_id is not None else 'Set mcp.enabled=true and mcp.player_id in config.yaml')"
if errorlevel 1 goto :fail

"%PY%" -m tracker.mcp.healthcheck >nul 2>&1
if errorlevel 1 (
    echo [run-mcp] Starting private MCP server in a separate window
    start "OSRS MCP Server" /D "%ROOT%" cmd /k call "%PY%" -m tracker.mcp
    for /L %%I in (1,1,20) do (
        "%PY%" -m tracker.mcp.healthcheck >nul 2>&1
        if not errorlevel 1 goto :ready
        timeout /t 1 /nobreak >nul
    )
    echo [run-mcp] MCP server did not expose the current tool contract. Check the server window.
    echo [run-mcp] If an older MCP process owns port 8503, stop it and retry.
    goto :fail
)

:ready
echo [run-mcp] Starting tunnel profile osrs-recommender
"%TUNNEL_CLIENT%" run --profile osrs-recommender
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%

:fail
popd
exit /b 1
