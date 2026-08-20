"""
Verifica los invariantes del Escenario A DESPUÉS de correr k6:
  1. Usuarios creados por registro: entre 1 y 5 (techo rate limit 5/hora).
  2. Sin duplicados por correo NI por rut en el tenant.
  3. Cada usuario creado quedó 'pendiente_activacion' (activo=False) con
     suscripción 'Prueba' pendiente (mismo flujo de landing).
Solo lectura. Lee k6-tests/load_config.json.
"""
import json
import os
import sys
from sqlalchemy import text as sa_text
from app.core.config import settings  # noqa: E402
from app.db.database import engine  # noqa: E402

K6_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "k6-tests"))
with open(os.path.join(K6_DIR, "load_config.json"), encoding="utf-8") as f:
    cfg = json.load(f)
TENANT = cfg["tenant_id"]


def main():
    ok = True
    with engine.connect() as conn:
        n_creados = conn.execute(sa_text(
            "SELECT COUNT(*) FROM usuarios WHERE tenant_id=:t AND rol='alumno' "
            "AND correo LIKE 'load_test_a_%' AND rol='alumno'"),
            {"t": TENANT}).scalar()
        dup_correo = conn.execute(sa_text(
            "SELECT correo, COUNT(*) FROM usuarios WHERE tenant_id=:t AND correo LIKE 'load_test_a_%' AND rol='alumno' "
            "GROUP BY correo HAVING COUNT(*) > 1"),
            {"t": TENANT}).fetchall()
        dup_rut = conn.execute(sa_text(
            "SELECT rut, COUNT(*) FROM usuarios WHERE tenant_id=:t AND correo LIKE 'load_test_a_%' AND rol='alumno' "
            "GROUP BY rut HAVING COUNT(*) > 1"),
            {"t": TENANT}).fetchall()
        mal_estado = conn.execute(sa_text(
            "SELECT id, estado, activo FROM usuarios WHERE tenant_id=:t AND correo LIKE 'load_test_a_%' AND rol='alumno' "
            "AND (estado != 'pendiente_activacion' OR activo = TRUE)"),
            {"t": TENANT}).fetchall()
        con_prueba = conn.execute(sa_text(
            "SELECT COUNT(*) FROM suscripciones s JOIN usuarios u ON u.id = s.usuario_id "
            "JOIN planes p ON p.id = s.plan_id "
            "WHERE u.tenant_id=:t AND u.correo LIKE 'load_test_a_%' "
            "AND p.nombre='Prueba' AND s.estado='pendiente'"),
            {"t": TENANT}).scalar()

    r1 = 1 <= n_creados <= 5
    ok &= r1
    print(f"[1] usuarios creados por registro: {n_creados} (esperado 1..5, techo 5/hora): "
          f"{'PASS' if r1 else 'FAIL'}")

    r2 = len(dup_correo) == 0 and len(dup_rut) == 0
    ok &= r2
    print(f"[2] sin duplicados (correo {len(dup_correo)}, rut {len(dup_rut)}): "
          f"{'PASS' if r2 else 'FAIL'}")

    r3 = len(mal_estado) == 0
    ok &= r3
    print(f"[3] todos pendiente_activacion/activo=False: "
          f"{'PASS' if r3 else 'FAIL ' + str(mal_estado[:5])}")

    r4 = con_prueba == n_creados
    ok &= r4
    print(f"[4] suscripciones Prueba pendientes: {con_prueba} (esperadas {n_creados}): "
          f"{'PASS' if r4 else 'FAIL'}")

    print(f"\nRESULTADO: {'OK - Escenario A verificado' if ok else 'FALLÓ'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
