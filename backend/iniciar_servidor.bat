@echo off
cd /d C:\Users\Asus\Desktop\proyecto_box_crossfit\backend
echo ============================================================
echo   INICIANDO SERVIDOR FASTAPI - BOX CROSSFIT
echo ============================================================
echo.
echo Servidor corriendo en: http://localhost:8000
echo Documentacion Swagger: http://localhost:8000/docs
echo.
echo Presiona CTRL+C para detener el servidor
echo ============================================================
echo.
python -m uvicorn app.main:app --reload
