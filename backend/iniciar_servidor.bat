@echo off
cd /d C:\Users\Asus\Desktop\Proyectos\proyecto-crossfit\backend
echo ============================================================
echo   INICIANDO SERVIDOR FASTAPI - BOX CROSSFIT (MODO DESARROLLO)
echo ============================================================
echo.
echo   ENVIRONMENT=test (BD purple-cherry)
echo   Servidor: http://localhost:8000
echo   Swagger:  http://localhost:8000/docs
echo.
echo   Para ver los datos del seed, el frontend debe estar
echo   corriendo (npm run dev) apuntando a este backend.
echo.
echo   Presiona CTRL+C para detener.
echo ============================================================
echo.

set ENVIRONMENT=test
python -m uvicorn app.main:app --reload