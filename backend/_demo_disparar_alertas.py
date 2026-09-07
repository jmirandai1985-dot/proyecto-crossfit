"""DEMO: dispara las 3 alertas programadas via los endpoints manuales de admin.

1) Reporta quién coincide con cada alerta en tenant_id=1 (mismas queries del servicio).
2) Login real como admin del demo (demo_alertas_admin@test.cl).
3) POST a los 3 endpoints y verifica notificaciones_enviadas.
"""
import requests
from sqlalchemy import text

from app.core.config import settings
from app.db.database import SessionLocal

if "polished-term" not in settings.DATABASE_URL:
    raise SystemExit("ABORT: no es TEST")

BASE = "http://localhost:8000"
ADMIN_CORREO = "demo_alertas_admin@test.cl"
ADMIN_PASS = "AdminDemo123!"
TENANT_ID = 1

db = SessionLocal()
try:
    print("=== Coincidencias por alerta en tenant 1 (pre-disparo) ===")
    hoy = "hoy"
    # renovación (vencen en 3 días)
    rows = db.execute(text("""
        SELECT u.id, u.nombre, u.correo FROM suscripciones s
        JOIN usuarios u ON u.id=s.usuario_id
        WHERE s.tenant_id=1 AND s.estado='activo' AND u.activo=true
          AND s.fecha_expiracion::date = CURRENT_DATE + 3""")).fetchall()
    print(f"[vencimiento 3d] {len(rows)} candidato(s):", [dict(r._mapping) for r in rows])
    # urgencia (vencen hoy)
    rows = db.execute(text("""
        SELECT u.id, u.nombre, u.correo FROM suscripciones s
        JOIN usuarios u ON u.id=s.usuario_id
        WHERE s.tenant_id=1 AND s.estado='activo' AND u.activo=true
          AND s.fecha_expiracion::date = CURRENT_DATE""")).fetchall()
    print(f"[urgencia hoy] {len(rows)} candidato(s):", [dict(r._mapping) for r in rows])
    # inactividad (7+ días sin asistencia)
    rows = db.execute(text("""
        SELECT u.id, u.nombre, u.correo, (SELECT MAX(a.fecha) FROM asistencias a
               WHERE a.usuario_id=u.id) AS ultima
        FROM usuarios u
        WHERE u.tenant_id=1 AND u.rol='alumno' AND u.activo=true AND u.estado='activo'""")).fetchall()
    cand = [dict(r._mapping) for r in rows
            if r.ultima is not None and r.ultima < (__import__('datetime').date.today() - __import__('datetime').timedelta(days=7))]
    print(f"[inactividad 7+] {len(cand)} candidato(s):", cand)
finally:
    db.close()

# ── Login real ──
r = requests.post(f"{BASE}/api/v1/auth/login",
                  json={"correo": ADMIN_CORREO, "password": ADMIN_PASS}, timeout=10)
print("\nlogin:", r.status_code)
if r.status_code != 200:
    print(r.text)
    raise SystemExit(1)
tok = r.json()["access_token"]
H = {"Authorization": f"Bearer {tok}"}

# ── Disparo ──
for nombre, path in [
    ("vencimiento 3d", "/api/v1/notificaciones/enviar-alertas-vencimiento"),
    ("urgencia hoy",   "/api/v1/notificaciones/enviar-alertas-urgencia"),
    ("inactividad 7+", "/api/v1/notificaciones/enviar-alertas-inactividad"),
]:
    resp = requests.post(f"{BASE}{path}", headers=H, timeout=60)
    print(f"[{nombre}] status={resp.status_code} body={resp.text[:400]}")

# ── Verificación en BD ──
db = SessionLocal()
try:
    casos = [
        (291, "renovacion_plan",        "Test Vence en 3 días"),
        (292, "vencimiento_inminente",  "Test Vence Hoy"),
        (293, "inactividad",            "Test Inactivo 7+"),
    ]
    for uid, tipo, nombre in casos:
        rows = db.execute(text(
            "SELECT id, alumno_id, tipo, estado, detalle_error, fecha_envio "
            "FROM notificaciones_enviadas WHERE alumno_id=:a AND tipo=:t ORDER BY id"),
            {"a": uid, "t": tipo}).fetchall()
        print(f"\nalumno '{nombre}' (id={uid}) tipo={tipo}: {len(rows)} fila(s)")
        for row in rows:
            print("   ", dict(row._mapping))
finally:
    db.close()
