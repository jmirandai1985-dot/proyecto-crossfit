@echo off
cd /d "%~dp0"
SETLOCAL ENABLEDELAYEDEXPANSION

echo ===============================================================================
echo  RUN TESTS - Box CrossFit Platform
echo ===============================================================================

:: ── 1. Kill any existing uvicorn on port 8000 ──
echo.
echo [STOP] Killing any existing uvicorn on port 8000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000"') do (
    if not "%%a"=="" (
        taskkill /F /PID %%a >nul 2>&1
    )
)
timeout /t 2 /nobreak >nul

:: ── 2. Run the Python orchestrator (seed + uvicorn + pytest) ──
:: This Python script runs EVERYTHING in the same process tree,
:: guaranteeing ENVIRONMENT=test is inherited by all subprocesses.
echo.
echo [RUN] Python orchestrator (seed + uvicorn + pytest)...
py -3.12 _run_tests_orchestrator.py

set PYTEST_EXIT=%ERRORLEVEL%

echo.
echo ===============================================================================
if %PYTEST_EXIT% EQU 0 (
    echo  ALL TESTS PASSED
) else (
    echo  TESTS COMPLETED WITH FAILURES (exit code: %PYTEST_EXIT%)
)
echo ===============================================================================

ENDLOCAL
exit /b %PYTEST_EXIT%