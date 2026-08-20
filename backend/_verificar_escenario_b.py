"""
Verifica los invariantes del Escenario B DESPUÉS de correr k6:
  1. Cupo nunca excedido: reservas válidas == cupo == asistentes_confirmados.
  2. Descuento exacto: con reserva → 29 créditos; sin reserva → 30; nunca < 0.
  3. No hay reserva sin descuento ni descuento sin reserva (1:1).
Lee la config del seed (k6-tests/load_config.json). Solo lectura.
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
CLASE = cfg["clase_id"]
N = cfg["n_alumnos"]


def main():
    ok = True
    with engine.connect() as conn:
        cupo = conn.execute(sa_text(
            "SELECT cupo_maximo, asistentes_confirmados FROM clases WHERE id=:c"),
            {"c": CLASE}).fetchone()
        n_reservas = conn.execute(sa_text(
            "SELECT COUNT(*) FROM reservas WHERE clase_id=:c AND estado != 'cancelled'"),
            {"c": CLASE}).scalar()
        filas = conn.execute(sa_text(
            "SELECT u.id, s.creditos_disponibles FROM usuarios u "
            "JOIN suscripciones s ON s.usuario_id = u.id "
            "WHERE u.tenant_id=:t AND u.rol='alumno' AND s.estado='activo'"),
            {"t": TENANT}).fetchall()
        alumnos_reservados = set(r[0] for r in conn.execute(sa_text(
            "SELECT alumno_id FROM reservas WHERE clase_id=:c AND estado != 'cancelled'"),
            {"c": CLASE}).fetchall())

    print(f"clase {CLASE}: cupo={cupo[0]}, asistentes_confirmados={cupo[1]}")
    print(f"reservas válidas en clase: {n_reservas}")
    print(f"alumnos con suscripción consultados: {len(filas)}")

    # 1) cupo no excedido
    r1 = cupo[1] <= cupo[0] and n_reservas == cupo[1] and n_reservas == cupo[0]
    ok &= r1
    print(f"[1] cupo respetado (reservas==asist==cupo): {'PASS' if r1 else 'FAIL'}")

    # 2/3) descuento exacto 1:1
    mal_sin_reserva = []
    mal_con_reserva = []
    negativos = []
    for uid, cred in filas:
        if cred is None:
            continue
        if cred < 0:
            negativos.append(uid)
        tiene = uid in alumnos_reservados
        if tiene and cred != 29:
            mal_con_reserva.append((uid, cred))
        if not tiene and cred != 30:
            mal_sin_reserva.append((uid, cred))
    r2 = len(mal_sin_reserva) == 0 and len(mal_con_reserva) == 0
    r3 = len(negativos) == 0
    ok &= r2 and r3
    print(f"[2] sin reserva → 30 créditos: {'PASS' if not mal_sin_reserva else 'FAIL ' + str(mal_sin_reserva[:5])}")
    print(f"[3] con reserva → 29 créditos: {'PASS' if not mal_con_reserva else 'FAIL ' + str(mal_con_reserva[:5])}")
    print(f"[4] ningún crédito negativo: {'PASS' if r3 else 'FAIL ' + str(negativos[:5])}")

    print(f"\nRESULTADO: {'OK - invariantes verificados' if ok else 'FALLÓ'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
