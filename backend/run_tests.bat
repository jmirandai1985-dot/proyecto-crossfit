@echo off
cd /d "%~dp0"
SETLOCAL ENABLEDELAYEDEXPANSION

echo ===============================================================================
echo  RUN TESTS - Box CrossFit Platform
echo ===============================================================================

:: -- 0. CONFIRMACION (este script es DESTRUCTIVO) --
:: Antes del primer test, run_setup_test_db.py hace:
::   * DROP SCHEMA public CASCADE sobre la branch TEST de Neon (linea 89) y
::     reconstruye el schema con create_all()
::   * DELETE de TODO el seed de esa branch (usuarios, tenants, clases,
::     reservas, planes, notificaciones...) y lo vuelve a sembrar
:: El guard de Python (ENVIRONMENT=test + TEST_BRANCH_IDS) protege de tocar PROD,
:: pero no de "me equivoque de ventana": esta confirmacion es la ultima red.
:: No interactivo / automatizado: run_tests.bat /y   (o --yes)
if /i "%~1"=="/y" goto :run_tests_confirmado
if /i "%~1"=="--yes" goto :run_tests_confirmado

echo.
echo ===============================================================================
echo  ATENCION: OPERACION DESTRUCTIVA SOBRE LA BD DE TEST
echo    - DROP SCHEMA public CASCADE + re-seed desde cero (borra los datos de prueba)
echo    - mata cualquier uvicorn que este escuchando en el puerto 8000
echo  PROD NO se toca: la branch la valida TEST_BRANCH_IDS (app/core/config.py).
echo ===============================================================================
set "CONFIRMA="
set /p "CONFIRMA=Escribe SI para continuar (cualquier otra cosa aborta): "
if /i not "!CONFIRMA!"=="SI" (
    echo.
    echo [ABORTADO] No se corrio ningun test ni se toco la BD.
    ENDLOCAL
    exit /b 1
)

:run_tests_confirmado
echo.
echo [OK] Confirmado: se corre la suite COMPLETA contra la BD de TEST.


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