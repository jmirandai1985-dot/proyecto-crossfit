"""Verificación SOLO LECTURA de: (1) existencia de las tablas que usa el cleanup del
harness y (2) filas leftovers TEST_VALIDACION en la BD activa. No modifica nada."""
import sys

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from sqlalchemy import create_engine, text  # noqa: E402
from app.core.config import settings  # noqa: E402

engine = create_engine(settings.DATABASE_URL)

TABLAS_CLEANUP = [
    "notificaciones", "notificaciones_enviadas", "solicitudes_planes",
    "transacciones_financieras", "cobertura_emergencia", "auditoria", "clases",
    "horarios", "coach_disciplinas", "retencion_alumnos", "historial_rm",
    "suscripciones", "wods", "asistencias", "pedidos", "productos", "usuarios",
    "movimientos", "planes", "tenants", "horarios_base", "configuracion_negocio",
    "disciplinas", "reservas",
]

with engine.connect() as c:
    print("=" * 60)
    print("1) EXISTENCIA DE TABLAS USADAS POR EL CLEANUP DEL HARNESS")
    print("=" * 60)
    rows = c.execute(text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public'")).fetchall()
    existentes = {r[0] for r in rows}
    faltan = [t for t in TABLAS_CLEANUP if t not in existentes]
    if faltan:
        print(" ⚠️  FALTAN:", ", ".join(faltan))
    else:
        print(" ✅ Todas las tablas del cleanup existen.")
    print(" (total tablas public:", len(existentes), ")")

    print("\n" + "=" * 60)
    print("2) LEFTOVERS TEST_VALIDACION")
    print("=" * 60)

    tenants = c.execute(text(
        "SELECT id, nombre, subdomain FROM tenants "
        "WHERE subdomain LIKE 'test-validacion-fase1-%' "
        "   OR nombre LIKE 'TEST_VALIDACION%' ORDER BY id")).fetchall()
    usuarios = c.execute(text(
        "SELECT id, tenant_id, rut, nombre, correo FROM usuarios "
        "WHERE rut LIKE 'TV%' OR correo LIKE 'test_validacion_%' "
        "   OR nombre LIKE 'TEST_VALIDACION%' ORDER BY id")).fetchall()

    tids = [t[0] for t in tenants]
    uids = [u[0] for u in usuarios]
    print(f" tenants TEST_VALIDACION : {len(tenants)}")
    for t in tenants:
        print("   ", t)
    print(f" usuarios TEST_VALIDACION: {len(usuarios)}")
    for u in usuarios:
        print("   ", u)

    hallazgos = 0
    if tids:
        tlist = ", ".join(str(t) for t in tids)
        for tabla in TABLAS_CLEANUP:
            if tabla in ("tenants", "usuarios"):
                continue
            if tabla not in existentes:
                continue
            if tabla in ("notificaciones", "notificaciones_enviadas",
                         "pedidos", "reservas"):
                continue  # se cubren por alumno_id abajo
            n = c.execute(text(
                f"SELECT COUNT(*) FROM {tabla} WHERE tenant_id IN ({tlist})"
            )).scalar()
            if n:
                hallazgos += 1
                ids = [r[0] for r in c.execute(text(
                    f"SELECT id FROM {tabla} WHERE tenant_id IN ({tlist})"))]
                print(f"  ❌ LEFTOVER {tabla}: {n} fila(s) ids={ids}")
    if uids:
        ulist = ", ".join(str(u) for u in uids)
        for tabla, col in [("notificaciones", "alumno_id"),
                           ("notificaciones_enviadas", "alumno_id"),
                           ("solicitudes_planes", "alumno_id"),
                           ("pedidos", "alumno_id"),
                           ("reservas", "alumno_id"),
                           ("historial_rm", "alumno_id")]:
            if tabla not in existentes:
                continue
            n = c.execute(text(
                f"SELECT COUNT(*) FROM {tabla} WHERE {col} IN ({ulist})"
            )).scalar()
            if n:
                hallazgos += 1
                ids = [r[0] for r in c.execute(text(
                    f"SELECT id FROM {tabla} WHERE {col} IN ({ulist})"))]
                print(f"  ❌ LEFTOVER {tabla} (por alumno): {n} fila(s) ids={ids}")

    if not tids and not uids:
        print(" ✅ SIN leftovers: no hay tenants ni usuarios TEST_VALIDACION.")
    elif hallazgos == 0:
        print(" ✅ Tenants/usuarios marcados encontrados pero sin filas "
              "huérfanas relacionadas.")
    else:
        print(f" ⚠️  {hallazgos} grupo(s) de tablas con filas pendientes de borrado.")

print("\nVerificación completada (solo lectura).")
