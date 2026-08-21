"""Limpieza manual SOLO de datos TEST_VALIDACION leftover (FK-safe).
Elimina por ids de tenant/usuario en orden correcto de FKs."""
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from sqlalchemy import text  # noqa: E402
from app.db.database import engine  # noqa: E402

TIDS = [8081971, 8081972, 8435276, 8435277]
UIDS = [8082071, 8082072, 8082073, 8082074, 8082075,
        8435376, 8435377, 8435378, 8435379, 8435380]

tlist = ", ".join(str(t) for t in TIDS)
ulist = ", ".join(str(u) for u in UIDS)

# En el MISMO orden que el cleanup del harness, pero con pasos por tabla
# (cada uno en su propia transacción para que un fallo no deje todo a medias).
PASOS = [
    ("notificaciones", f"DELETE FROM notificaciones WHERE alumno_id IN ({ulist})"),
    ("notificaciones_enviadas", f"DELETE FROM notificaciones_enviadas WHERE alumno_id IN ({ulist})"),
    ("solicitudes_planes", f"DELETE FROM solicitudes_planes WHERE tenant_id IN ({tlist}) OR alumno_id IN ({ulist})"),
    ("transacciones_financieras", f"DELETE FROM transacciones_financieras WHERE tenant_id IN ({tlist})"),
    ("cobertura_emergencia", f"DELETE FROM cobertura_emergencia WHERE tenant_id IN ({tlist})"),
    ("auditoria", f"DELETE FROM auditoria WHERE tenant_id IN ({tlist})"),
    ("clases", f"DELETE FROM clases WHERE tenant_id IN ({tlist})"),
    ("horarios", f"DELETE FROM horarios WHERE tenant_id IN ({tlist})"),
    ("coach_disciplinas", f"DELETE FROM coach_disciplinas WHERE tenant_id IN ({tlist})"),
    ("retencion_alumnos", f"DELETE FROM retencion_alumnos WHERE tenant_id IN ({tlist})"),
    ("historial_rm", f"DELETE FROM historial_rm WHERE tenant_id IN ({tlist})"),
    ("suscripciones", f"DELETE FROM suscripciones WHERE tenant_id IN ({tlist})"),
    ("wods", f"DELETE FROM wods WHERE tenant_id IN ({tlist})"),
    ("asistencias", f"DELETE FROM asistencias WHERE tenant_id IN ({tlist})"),
    ("pedidos", f"DELETE FROM pedidos WHERE tenant_id IN ({tlist}) OR alumno_id IN ({ulist})"),
    ("productos", f"DELETE FROM productos WHERE tenant_id IN ({tlist})"),
    ("usuarios", f"DELETE FROM usuarios WHERE tenant_id IN ({tlist}) OR rut LIKE 'TV%' OR correo LIKE 'test_validacion_%'"),
    ("movimientos", f"DELETE FROM movimientos WHERE tenant_id IN ({tlist})"),
    ("planes", f"DELETE FROM planes WHERE tenant_id IN ({tlist})"),
    ("tenants", f"DELETE FROM tenants WHERE id IN ({tlist}) OR subdomain LIKE 'test-validacion-%'"),
]

with engine.connect() as conn:
    # inspeccion previa: notificaciones que referencian a los usuarios
    notif = conn.execute(text(
        f"SELECT id, alumno_id, tipo, mensaje FROM notificaciones WHERE alumno_id IN ({ulist})")).fetchall()
    print(f"notificaciones leftover que referencian a usuarios test: {len(notif)}")
    for n in notif:
        print(f"   notif id={n.id} alumno_id={n.alumno_id} tipo={n.tipo} msg={n.mensaje[:60]!r}")

for tabla, sql in PASOS:
    try:
        with engine.begin() as c:
            r = c.execute(text(sql))
            if r.rowcount:
                print(f"  {tabla}: {r.rowcount} fila(s) eliminada(s)")
    except Exception as e:
        print(f"  {tabla}: ERROR -> {type(e).__name__}: {str(e)[:150]}")

print("Limpieza manual completada.")
