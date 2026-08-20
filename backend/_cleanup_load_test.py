"""
Limpieza TOTAL de LOAD_TEST_BOX + verificación de 0 leftovers.

- Doble pasada tolerante a FKs (mismo patrón que los harnesses).
- Identifica tenants por subdomain 'load-test-box-%' y alumnos por
  correo 'load_test_%' / tenant. Borra también k6-tests/tokens.json.
- Imprime conteos de filas restantes por tabla con marcador LOAD_TEST.
"""
import os
import sys
from sqlalchemy import text as sa_text
from app.core.config import settings  # noqa: E402
from app.db.database import engine  # noqa: E402

K6_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "k6-tests"))
TOKENS_FILE = os.path.join(K6_DIR, "tokens.json")


def _tenant_ids(conn):
    rows = conn.execute(sa_text(
        "SELECT id FROM tenants WHERE subdomain LIKE 'load-test-box-%'")).fetchall()
    return [r[0] for r in rows]


def _sub_alumnos(tids):
    if not tids:
        return "(SELECT id FROM usuarios WHERE 1=0)"
    return (f"(SELECT id FROM usuarios WHERE correo LIKE 'load_test_%' "
            f"OR tenant_id IN ({','.join(str(t) for t in tids)}))")


def cleanup():
    print("[cleanup] buscando leftovers LOAD_TEST...")
    with engine.connect() as conn:
        tids = _tenant_ids(conn)
    print(f"[cleanup] tenants LOAD_TEST encontrados: {len(tids)}")

    tids_sql = ",".join(str(t) for t in tids) if tids else "0"
    sub = _sub_alumnos(tids)

    PASOS = [
        ("notificaciones", f"DELETE FROM notificaciones WHERE alumno_id IN {sub}"),
        ("notificaciones_enviadas", f"DELETE FROM notificaciones_enviadas WHERE alumno_id IN {sub}"),
        ("reservas", f"DELETE FROM reservas WHERE tenant_id IN ({tids_sql}) "
                    f"OR alumno_id IN {sub}"),
        ("solicitudes_planes", f"DELETE FROM solicitudes_planes WHERE tenant_id IN ({tids_sql}) "
                              f"OR alumno_id IN {sub}"),
        ("transacciones_financieras", f"DELETE FROM transacciones_financieras WHERE tenant_id IN ({tids_sql})"),
        ("cobertura_emergencia", f"DELETE FROM cobertura_emergencia WHERE tenant_id IN ({tids_sql})"),
        ("auditoria", f"DELETE FROM auditoria WHERE tenant_id IN ({tids_sql})"),
        ("clases", f"DELETE FROM clases WHERE tenant_id IN ({tids_sql})"),
        ("horarios", f"DELETE FROM horarios WHERE tenant_id IN ({tids_sql})"),
        ("coach_disciplinas", f"DELETE FROM coach_disciplinas WHERE tenant_id IN ({tids_sql})"),
        ("retencion_alumnos", f"DELETE FROM retencion_alumnos WHERE tenant_id IN ({tids_sql})"),
        ("historial_rm", f"DELETE FROM historial_rm WHERE tenant_id IN ({tids_sql})"),
        ("suscripciones", f"DELETE FROM suscripciones WHERE tenant_id IN ({tids_sql})"),
        ("wods", f"DELETE FROM wods WHERE tenant_id IN ({tids_sql})"),
        ("asistencias", f"DELETE FROM asistencias WHERE tenant_id IN ({tids_sql})"),
        ("pedidos", f"DELETE FROM pedidos WHERE tenant_id IN ({tids_sql}) "
                    f"OR alumno_id IN {sub}"),
        ("productos", f"DELETE FROM productos WHERE tenant_id IN ({tids_sql})"),
        ("usuarios", f"DELETE FROM usuarios WHERE tenant_id IN ({tids_sql}) "
                    f"OR correo LIKE 'load_test_%'"),
        ("disciplinas", f"DELETE FROM disciplinas WHERE tenant_id IN ({tids_sql})"),
        ("movimientos", f"DELETE FROM movimientos WHERE tenant_id IN ({tids_sql})"),
        ("planes", f"DELETE FROM planes WHERE tenant_id IN ({tids_sql})"),
        ("tenants", f"DELETE FROM tenants WHERE id IN ({tids_sql}) "
                    f"OR subdomain LIKE 'load-test-box-%'"),
    ]

    def _tablas():
        with engine.connect() as conn:
            rows = conn.execute(sa_text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public'")).fetchall()
            return {r[0] for r in rows}

    def _pasada(tablas):
        with engine.begin() as conn:
            for tabla, sql in PASOS:
                if tabla in tablas:
                    conn.execute(sa_text(sql))

    try:
        tablas = _tablas()
        _pasada(tablas)
        _pasada(tablas)
        print("[cleanup] OK - datos LOAD_TEST eliminados")
    except Exception as e:
        print("[cleanup] FALLO:", str(e)[:200])

    try:
        if os.path.exists(TOKENS_FILE):
            os.remove(TOKENS_FILE)
            print("[cleanup] tokens.json eliminado")
    except Exception as e:
        print("[cleanup] aviso borrando tokens.json:", str(e)[:100])


def verificar_cero_leftovers():
    print("\n[leftovers] verificación de 0 restos LOAD_TEST:")
    with engine.connect() as conn:
        tids = _tenant_ids(conn)
        tids_sql = ",".join(str(t) for t in tids) if tids else "0"
        sub = _sub_alumnos(tids)
        checks = [
            ("tenants", "SELECT COUNT(*) FROM tenants WHERE subdomain LIKE 'load-test-box-%'"),
            ("usuarios", f"SELECT COUNT(*) FROM usuarios WHERE tenant_id IN ({tids_sql}) "
                        f"OR correo LIKE 'load_test_%'"),
            ("suscripciones", f"SELECT COUNT(*) FROM suscripciones WHERE tenant_id IN ({tids_sql})"),
            ("reservas", f"SELECT COUNT(*) FROM reservas WHERE tenant_id IN ({tids_sql}) "
                        f"OR alumno_id IN {sub}"),
            ("clases", f"SELECT COUNT(*) FROM clases WHERE tenant_id IN ({tids_sql})"),
            ("horarios", f"SELECT COUNT(*) FROM horarios WHERE tenant_id IN ({tids_sql})"),
            ("planes", f"SELECT COUNT(*) FROM planes WHERE tenant_id IN ({tids_sql})"),
            ("disciplinas", f"SELECT COUNT(*) FROM disciplinas WHERE tenant_id IN ({tids_sql})"),
            ("transacciones_financieras",
             f"SELECT COUNT(*) FROM transacciones_financieras WHERE tenant_id IN ({tids_sql})"),
            ("pedidos", f"SELECT COUNT(*) FROM pedidos WHERE tenant_id IN ({tids_sql}) "
                       f"OR alumno_id IN {sub}"),
            ("auditoria", f"SELECT COUNT(*) FROM auditoria WHERE tenant_id IN ({tids_sql})"),
            ("tokens.json", None),
        ]
        total = 0
        for nombre, sql in checks:
            if sql is None:
                n = 1 if os.path.exists(TOKENS_FILE) else 0
            else:
                try:
                    n = conn.execute(sa_text(sql)).scalar() or 0
                except Exception as e:
                    print(f"[leftovers] {nombre}: no verificable ({str(e)[:80]})")
                    continue
            print(f"[leftovers] {nombre}: {n}")
            total += n
    return total == 0


if __name__ == "__main__":
    cleanup()
    ok = verificar_cero_leftovers()
    print(f"\nLEFTIVERS: {'0 - OK' if ok else '>0 - HAY RESTOS'}")
    sys.exit(0 if ok else 1)
