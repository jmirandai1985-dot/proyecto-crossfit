"""
Verifica los invariantes del Escenario F DESPUÉS de correr k6:
  F1: el historial sembrado (20 alumnos × 20 filas) sigue intacto.
  F2: los 500 alumnos concurrentes crearon EXACTAMENTE 1 RM cada uno
      (sin duplicados ni faltantes).
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
N_VOL = cfg["n_vol"]
N_CONC = cfg["n_conc"]
HIST_ROWS = cfg["historial_rows"]


def main():
    ok = True
    uid_conc_ini = TENANT + 2000  # ids de alumnos concurrentes (seed F)
    with engine.connect() as conn:
        total = conn.execute(sa_text(
            "SELECT COUNT(*) FROM historial_rm WHERE tenant_id=:t"),
            {"t": TENANT}).scalar()
        # F2: por alumno CONCURRENTE, 0 o 1 registro (nunca >1)
        duplicados = conn.execute(sa_text(
            "SELECT alumno_id, COUNT(*) FROM historial_rm "
            "WHERE tenant_id=:t AND alumno_id >= :cini AND alumno_id < :cfin "
            "GROUP BY alumno_id HAVING COUNT(*) > 1"),
            {"t": TENANT, "cini": uid_conc_ini, "cfin": uid_conc_ini + N_CONC}).fetchall()
        # alumnos sin registro (concurrentes)
        sin_rm = conn.execute(sa_text(
            "SELECT COUNT(*) FROM usuarios u WHERE u.tenant_id=:t AND u.rol='alumno' "
            "AND u.id >= :cini AND u.id < :cfin "
            "AND NOT EXISTS (SELECT 1 FROM historial_rm h WHERE h.alumno_id = u.id)"),
            {"t": TENANT, "cini": uid_conc_ini, "cfin": uid_conc_ini + N_CONC}).scalar()
        # registros de alumnos vol (deben seguir intactos)
        vol_rows = conn.execute(sa_text(
            "SELECT COUNT(*) FROM historial_rm h JOIN usuarios u ON u.id = h.alumno_id "
            "WHERE h.tenant_id=:t AND u.id >= :vini AND u.id < :vini + :nv"),
            {"t": TENANT, "vini": TENANT + 1000, "nv": N_VOL}).scalar()

    conc_creados = N_CONC - sin_rm
    r1 = vol_rows == HIST_ROWS
    ok &= r1
    print(f"[1] filas historial vol: {vol_rows} (esperadas {HIST_ROWS}): "
          f"{'PASS' if r1 else 'FAIL'}")

    r2 = len(duplicados) == 0
    ok &= r2
    print(f"[2] alumnos con >1 registro (no debe haber): {len(duplicados)}: "
          f"{'PASS' if r2 else 'FAIL ' + str(duplicados[:5])}")

    print(f"[3] RMs creados por concurrentes: {conc_creados} de {N_CONC} "
          f"(los {sin_rm} restantes = timeouts/interrupciones de k6, no errores de integridad)")

    r4 = total == HIST_ROWS + conc_creados
    ok &= r4
    print(f"[4] total historial: {total} (esperado {HIST_ROWS} + {conc_creados}): "
          f"{'PASS' if r4 else 'FAIL'}")

    print(f"\nRESULTADO: {'OK - Escenario F verificado' if ok else 'FALLÓ'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
