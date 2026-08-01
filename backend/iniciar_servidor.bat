@echo off
cd /d C:\Users\Asus\Desktop\Proyectos\proyecto-crossfit\backend
echo ============================================================
echo   INICIANDO SERVIDOR FASTAPI - BOX CROSSFIT (MODO DESARROLLO)
echo ============================================================
echo   Matando procesos anteriores en puerto 8000...
taskkill /F /IM python.exe 2>nul
echo   Servidor levantandose...
echo.
C:\Users\Asus\AppData\Local\Microsoft\WindowsApps\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\python.exe iniciar_servidor.py
pause
