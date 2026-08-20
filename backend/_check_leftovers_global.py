"""Chequeo global de leftovers de TODAS las corridas de prueba + limpieza.

Marcadores: LOAD_TEST (load-test-box-*, load_test_*), TEST_VALIDACION
(test-validacion-*, test_validacion_*, TV*), TEST_AUDIT_ADMIN
(test-audit-admin-*, test_audit_admin_*, TAA*). Solo lectura + DELETE de lo
encontrado (doble pasada tolerante a FKs) y conteos finales.
"""
import os
import sys
from sqlalchemy import text as sa_text
from app.core.config import settings  # noqa: E402
from app.db.database import engine  # noqa: E402

K6_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "k6-tests"))


def _tenant_ids(conn):
    rows = conn.execute(sa_text(
        "SELECT id FROM tenants WHERE subdomain LIKE 'load-test-box-%' "
        "OR subdomain LIKE 'test-validacion-%' OR subdomain LIKE 'test-audit-admin-%'")).fetchall()
    return [r[0] for r in rows]


def _sub_alumnos(tids):
    if not tids:
        return "(SELECT id FROM usuarios WHERE 1=0)"
    return (f"(SELECT id FROM usuarios WHERE correo LIKE 'load_test_%' "
            f"OR correo LIKE 'test_validacion_%' OR correo LIKE 'test_audit_admin_%' "
            f"OR rut LIKE 'TV%' OR rut LIKE 'TAA%' OR tenant_id IN ({','.join(str(t) for t in tids)}))")


def main():
    with engine.connect() as conn:
        tids = _tenant_ids(conn)
    print(f"tenants de prueba encontrados: {len(tids)}")
    if not tids:
        print("0 tenants -> chequeo final de filas por correo/rut marcado de todos modos")
    tids_sql = ",".join(str(t) for t in tids) if tids else "0"
    sub = _sub_alumnos(tids)

    PASOS = [
        ("notificaciones", f"DELETE FROM notificaciones WHERE alumno_id IN {sub}"),
        ("notificaciones_enviadas", f"DELETE FROM notificaciones_enviadas WHERE alumno_id IN {sub}"),
        ("reservas", f"DELETE FROM reservas WHERE tenant_id IN ({tids_sql}) OR alumno_id IN {sub}"),
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
        ("pedidos", f"DELETE FROM pedidos WHERE tenant_id IN ({tids_sql}) OR alumno_id IN {sub}"),
        ("productos", f"DELETE FROM productos WHERE tenant_id IN ({tids_sql})"),
        ("usuarios", f"DELETE FROM usuarios WHERE tenant_id IN ({tids_sql}) "
                    f"OR correo LIKE 'load_test_%' OR correo LIKE 'test_validacion_%' "
                    f"OR correo LIKE 'test_audit_admin_%' OR rut LIKE 'TV%' OR rut LIKE 'TAA%'"),
        ("disciplinas", f"DELETE FROM disciplinas WHERE tenant_id IN ({tids_sql})"),
        ("movimientos", f"DELETE FROM movimientos WHERE tenant_id IN ({tids_sql})"),
        ("planes", f"DELETE FROM planes WHERE tenant_id IN ({tids_sql})"),
        ("tenants", f"DELETE FROM tenants WHERE id IN ({tids_sql}) "
                    f"OR subdomain LIKE 'load-test-box-%' OR subdomain LIKE 'test-validacion-%' "
                    f"OR subdomain LIKE 'test-audit-admin-%'"),
    ]

    def _tablas():
        with engine.connect() as conn:
            rows = conn.execute(sa_text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'")).fetchall()
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
        print("[cleanup] doble pasada OK")
    except Exception as e:
        print("[cleanup] FALLO:", str(e)[:200])

    # conteos finales
    total = 0
    with engine.connect() as conn:
        tids2 = _tenant_ids(conn)
        t2 = ",".join(str(t) for t in tids2) if tids2 else "0"
        sub2 = _sub_alumnos(tids2)
        checks = [
            ("tenants", "SELECT COUNT(*) FROM tenants WHERE subdomain LIKE 'load-test-box-%' "
                        "OR subdomain LIKE 'test-validacion-%' OR subdomain LIKE 'test-audit-admin-%'"),
            ("usuarios", f"SELECT COUNT(*) FROM usuarios WHERE tenant_id IN ({t2}) "
                        f"OR correo LIKE 'load_test_%' OR correo LIKE 'test_validacion_%' "
                        f"OR correo LIKE 'test_audit_admin_%' OR rut LIKE 'TV%' OR rut LIKE 'TAA%'"),
            ("suscripciones", f"SELECT COUNT(*) FROM suscripciones WHERE tenant_id IN ({t2})"),
            ("reservas", f"SELECT COUNT(*) FROM reservas WHERE tenant_id IN ({t2}) OR alumno_id IN {sub2}"),
            ("solicitudes_planes", f"SELECT COUNT(*) FROM solicitudes_planes WHERE tenant_id IN ({t2}) "
                                  f"OR alumno_id IN {sub2}"),
            ("historial_rm", f"SELECT COUNT(*) FROM historial_rm WHERE tenant_id IN ({t2})"),
            ("pedidos", f"SELECT COUNT(*) FROM pedidos WHERE tenant_id IN ({t2}) OR alumno_id IN {sub2}"),
            ("transacciones_financieras", f"SELECT COUNT(*) FROM transacciones_financieras WHERE tenant_id IN ({t2})"),
            ("planes", f"SELECT COUNT(*) FROM planes WHERE tenant_id IN ({t2})"),
            ("clases", f"SELECT COUNT(*) FROM clases WHERE tenant_id IN ({t2})"),
            ("auditoria", f"SELECT COUNT(*) FROM auditoria WHERE tenant_id IN ({t2})"),
            ("tokens.json", None),
        ]
        for nombre, sql in checks:
            if sql is None:
                n = 1 if os.path.exists(os.path.join(K6_DIR, "tokens.json")) else 0
            else:
                try:
                    n = conn.execute(sa_text(sql)).scalar() or 0
                except Exception as e:
                    print(f"[leftovers] {nombre}: no verificable ({str(e)[:80]})")
                    continue
            print(f"[leftovers] {nombre}: {n}")
            total += n
    print(f"\nTOTAL leftovers: {total}")
    sys.exit(0 if total == 0 else 1)


if __name__ == "__main__":
    main()
