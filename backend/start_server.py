"""
Script para iniciar el servidor FastAPI
"""
import uvicorn
import os
import sys

if __name__ == "__main__":
    # Cambiar al directorio del backend
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(backend_dir)

    print("=" * 60)
    print("  INICIANDO SERVIDOR FASTAPI - BOX CROSSFIT")
    print("=" * 60)
    print()
    print("Servidor corriendo en: http://localhost:8000")
    print("Documentación Swagger: http://localhost:8000/docs")
    print()
    print("Presiona CTRL+C para detener el servidor")
    print("=" * 60)
    print()

    # Iniciar uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
