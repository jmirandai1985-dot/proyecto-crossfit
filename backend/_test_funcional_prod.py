"""Prueba funcional de produccion (solo lectura): genera un JWT con el mismo
mecanismo de la app (JWT_SECRET_KEY de .env) para un usuario real activo y
consulta un endpoint autenticado que lee de la BD (GET /api/v1/planes).
Confirma: validación de token + consulta a BD a través de la conexión nueva.
NO imprime credenciales ni el token completo.
"""
import sys

import requests

from app.core.security import create_access_token
from app.db.database import SessionLocal
from app.models.usuario import Usuario

BASE = "http://localhost:8000"

db = SessionLocal()
user = db.query(Usuario).filter(Usuario.activo.is_(True)).order_by(Usuario.id).first()
if not user:
    print("FAIL: no hay usuarios activos en produccion")
    sys.exit(1)
uid = user.id
tenant = user.tenant_id
rol = user.rol.value if hasattr(user.rol, "value") else str(user.rol)
nombre = user.nombre
correo = user.correo
db.close()

print(f"usuario para la prueba: id={uid} rol={rol} (nombre no se imprime)")

token = create_access_token({
    "usuario_id": uid, "tenant_id": tenant, "rol": rol,
    "correo": correo, "nombre": nombre,
})

try:
    r = requests.get(f"{BASE}/api/v1/planes",
                     headers={"Authorization": f"Bearer {token}"}, timeout=20)
    if r.status_code == 200:
        items = r.json()
        print(f"GET /api/v1/planes -> 200 | items={len(items)} | autenticacion+BD OK")
        print("RESULTADO: PASS")
        sys.exit(0)
    else:
        print(f"GET /api/v1/planes -> {r.status_code} | body={r.text[:150]}")
        print("RESULTADO: FAIL")
        sys.exit(1)
except Exception as e:
    print(f"ERROR de red: {str(e)[:150]}")
    sys.exit(1)
