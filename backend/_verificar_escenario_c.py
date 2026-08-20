"""
Verifica los invariantes del Escenario C DESPUÉS de correr k6:
  1. Todas las solicitudes quedan 'approved' (y ninguna 'rejected'/duplicada).
  2. EXACTAMENTE 1 suscripción paga por solicitud aprobada (sin duplicados
     por doble-aprobación: s0 y s1 recibieron 2 aprobaciones concurrentes).
  3. EXACTAMENTE 1 transacción financiera por aprobación (sin duplicados).
  4. La suscripción 'Prueba' de cada alumno quedó 'vencido' (fix P3b).
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
PLAN_PAGO = cfg["plan_pago_id"]
SOLICITUDES = cfg["solicitudes"]


def main():
    ok = True
    with engine.connect() as conn:
        # 1) estados de las solicitudes
        rows = conn.execute(sa_text(
            "SELECT id, estado FROM solicitudes_planes WHERE tenant_id=:t"),
            {"t": TENANT}).fetchall()
        estados = {r[0]: r[1] for r in rows}
        no_approved = [sid for sid, st in estados.items() if st != "approved"]
        r1 = len(rows) == len(SOLICITUDES) and not no_approved
        ok &= r1
        print(f"[1] solicitudes: {len(rows)} ({len(SOLICITUDES)} esperadas) - "
              f"todas approved: {'PASS' if r1 else 'FAIL ' + str(no_approved[:5])}")

        # 2) suscripciones pagas: 1 por alumno, sin duplicados
        sus = conn.execute(sa_text(
            "SELECT usuario_id, COUNT(*) FROM suscripciones "
            "WHERE tenant_id=:t AND plan_id=:p AND estado='activo' "
            "GROUP BY usuario_id"),
            {"t": TENANT, "p": PLAN_PAGO}).fetchall()
        dupes = [u for u, c in sus if c > 1]
        r2 = len(sus) == len(SOLICITUDES) and not dupes
        ok &= r2
        print(f"[2] suscripciones pagas: {len(sus)} (1 por alumno, sin duplicados): "
              f"{'PASS' if r2 else 'FAIL dupes=' + str(dupes[:5])}")

        # 3) transacciones financieras: 1 por aprobación
        n_tx = conn.execute(sa_text(
            "SELECT COUNT(*) FROM transacciones_financieras "
            "WHERE tenant_id=:t AND tipo='ingreso' AND categoria='membresia'"),
            {"t": TENANT}).scalar()
        r3 = n_tx == len(SOLICITUDES)
        ok &= r3
        print(f"[3] transacciones financieras: {n_tx} (esperadas {len(SOLICITUDES)}): "
              f"{'PASS' if r3 else 'FAIL'}")

        # 4) Prueba expirada (P3b) para cada alumno
        sin_vencer = conn.execute(sa_text(
            "SELECT COUNT(*) FROM suscripciones s JOIN planes p ON p.id = s.plan_id "
            "WHERE s.tenant_id=:t AND p.nombre='Prueba' AND s.estado='activo'"),
            {"t": TENANT}).scalar()
        r4 = sin_vencer == 0
        ok &= r4
        print(f"[4] suscripciones Prueba aún activas (deben ser 0): {sin_vencer}: "
              f"{'PASS' if r4 else 'FAIL'}")

    print(f"\nRESULTADO: {'OK - Escenario C verificado' if ok else 'FALLÓ'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
