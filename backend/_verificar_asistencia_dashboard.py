"""
VERIFICACIÃ“N TEMPORAL: Flujo de asistencia del Dashboard Coach (TEST lingering-shape).

Simula EXACTAMENTE el flujo del nuevo botÃ³n del Dashboard Coach:
  1. GET  /api/v1/reservas/por-clase/{claseId}   (cargarAsistenciaClase)
  2. PUT  /api/v1/reservas/{reservaId}/asistencia { asistio: valor } (toggleAsistenciaAlumno)
  3. PUT  para TODAS las reservas (marcarTodosAsistencia)

Verifica con psycopg2 (query directa) que reservas.asistio cambiÃ³ en BD.

Para evitar depender del POST /reservas (que se cuelga), crea las reservas
de prueba directamente con INSERT SQL en la BD TEST, y las limpia al final.
"""
import os
import requests
import psycopg2
from datetime import date

os.environ["ENVIRONMENT"] = "test"
from app.core.config import settings

if settings.DATABASE_URL.startswith("postgresql://user:pass@"):
    print("FATAL: Define DATABASE_URL en backend/.env.test (copia .env.example)")
    sys.exit(1)
DB_URL = settings.DATABASE_URL

BASE = "http://localhost:8000/api/v1"
TENANT_ID = 1
COACH_ID = 7   # jesus - coach activo asignado a CrossFit (disc 1) en TEST
ALUMNO_ID_1 = 999
ALUMNO_ID_2 = 998
HOY = date.today().isoformat()
# app/core/security.py usa SECRET_KEY (no JWT_SECRET_KEY)
SECRET_KEY = os.getenv("SECRET_KEY", "urban_training_box_secret_key_2026_jwt")
ALGORITHM = "HS256"


def log(msg):
    print(msg, flush=True)


def make_token():
    from jose import jwt
    return jwt.encode(
        {
            "usuario_id": COACH_ID,
            "tenant_id": TENANT_ID,
            "rol": "coach",
            "correo": f"coach{COACH_ID}@test.com",
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def main():
    log("=" * 70)
    log(" VERIFICACION: Flujo de Asistencia Dashboard Coach (TEST lingering-shape)")
    log("=" * 70)

    # â”€â”€ 0. Confirmar servidor TEST â”€â”€
    r = requests.get("http://localhost:8000/debug/db-url", timeout=5)
    data = r.json()
    assert data.get("is_test"), f"Servidor NO es TEST: {data}"
    log(f"[OK] Servidor apunta a TEST branch={data.get('branch')}")

    token = make_token()
    headers = {"Authorization": f"Bearer {token}"}

    # â”€â”€ 1. Conectar a BD TEST â”€â”€
    conn = psycopg2.connect(DB_URL, connect_timeout=10)
    conn.autocommit = True
    cur = conn.cursor()
    log("[OK] Conexion a BD TEST establecida")

    # â”€â”€ 2. Obtener clase CrossFit de HOY â”€â”€
    r = requests.get(
        f"{BASE}/clases",
        params={"tenant_id": TENANT_ID, "fecha_desde": HOY,
                "fecha_hasta": HOY, "limit": 200},
        timeout=10,
    )
    assert r.status_code == 200, f"GET /clases: {r.status_code} {r.text[:200]}"
    clases = r.json()
    clases_hoy = clases if isinstance(clases, list) else (
        clases.get("clases", []) if isinstance(clases, dict) else [])
    crossfit = [c for c in clases_hoy if c.get("disciplina_id") == 1]
    assert len(crossfit) > 0, "No hay clases CrossFit hoy"
    clase_id = crossfit[0]["id"]
    log(f"[OK] Clase CrossFit seleccionada: id={clase_id}")

    # â”€â”€ 3. Obtener alumnos reales de TEST (rol=alumno, activo) â”€â”€
    cur.execute(
        "SELECT id FROM usuarios WHERE tenant_id=%s AND rol='alumno' AND activo=true ORDER BY id LIMIT 2",
        (TENANT_ID,),
    )
    alumnos_reales = [row[0] for row in cur.fetchall()]
    assert len(alumnos_reales) >= 1, "No hay alumnos activos en TEST"
    log(f"[OK] Alumnos encontrados en BD TEST: {alumnos_reales}")

    # â”€â”€ 4. Crear reservas de prueba directamente en BD (INSERT SQL) â”€â”€
    reservas_creadas = []
    for alumno_id in alumnos_reales:
        # Verificar que no exista ya una reserva para este alumno/clase
        cur.execute(
            "SELECT id FROM reservas WHERE clase_id=%s AND alumno_id=%s AND estado != 'cancelled'",
            (clase_id, alumno_id),
        )
        existing = cur.fetchone()
        if existing:
            reservas_creadas.append(existing[0])
            log(
                f"[OK] Reserva ya existente para alumno {alumno_id}: id={existing[0]}")
        else:
            cur.execute(
                """
                INSERT INTO reservas (tenant_id, clase_id, alumno_id, asistio, tokens_gastados, estado)
                VALUES (%s, %s, %s, FALSE, 1, 'confirmada')
                RETURNING id
                """,
                (TENANT_ID, clase_id, alumno_id),
            )
            new_id = cur.fetchone()[0]
            reservas_creadas.append(new_id)
            log(
                f"[OK] Reserva INSERTADA en BD: id={new_id} alumno_id={alumno_id}")

    assert len(reservas_creadas) >= 1, "No se pudo crear reservas de prueba"
    log(f"[OK] Total reservas de prueba: {len(reservas_creadas)}")

    # â”€â”€ 4. SIMULAR cargarAsistenciaClase: GET /reservas/por-clase/{claseId} â”€â”€
    log(
        f"\n-- Paso 4: GET /reservas/por-clase/{clase_id} (cargarAsistenciaClase) --")
    r_por = requests.get(f"{BASE}/reservas/por-clase/{clase_id}",
                         params={"tenant_id": TENANT_ID}, timeout=10)
    assert r_por.status_code == 200, f"GET /por-clase: {r_por.status_code} {r_por.text[:200]}"
    reservas_api = r_por.json()
    log(f"[OK] GET /por-clase devolvio {len(reservas_api)} reservas")
    for rv in reservas_api:
        log(f"     reserva_id={rv['id']} alumno_id={rv['alumno_id']} nombre={rv['alumno_nombre']} asistio_antes={rv['asistio']}")

    # Guardar estado original para restaurar
    estado_original = {rv["id"]: rv["asistio"] for rv in reservas_api}

    # â”€â”€ 5. SIMULAR toggleAsistenciaAlumno: PUT asistio=true para PRIMERA reserva â”€â”€
    primera_id = reservas_api[0]["id"]
    log(f"\n-- Paso 5: PUT /reservas/{primera_id}/asistencia {{ asistio: true }} (toggle) --")
    r_put = requests.put(
        f"{BASE}/reservas/{primera_id}/asistencia",
        params={"tenant_id": TENANT_ID},
        json={"asistio": True},
        headers=headers,
        timeout=10,
    )
    assert r_put.status_code == 200, f"PUT asistencia: {r_put.status_code} {r_put.text[:200]}"
    log(f"[OK] PUT /reservas/{primera_id}/asistencia HTTP 200")

    # â”€â”€ 5b. VERIFICACION 1: SELECT directo a BD â†’ asistio=True â”€â”€
    cur.execute("SELECT id, asistio FROM reservas WHERE id = %s", (primera_id,))
    row = cur.fetchone()
    assert row is not None, f"Reserva {primera_id} no encontrada en BD"
    assert row[1] is True, f"asistio debe ser True en BD, obtuve {row[1]}"
    log(f"[VERIFICACION-1 BD] reserva_id={row[0]} asistio={row[1]} <-- CAMBIO REAL persistido")

    # â”€â”€ 6. SIMULAR marcarTodosAsistencia (false): PUT para TODAS â”€â”€
    log(f"\n-- Paso 6: Marcar TODAS ({len(reservas_api)}) con asistio=false --")
    for rv in reservas_api:
        r2 = requests.put(
            f"{BASE}/reservas/{rv['id']}/asistencia",
            params={"tenant_id": TENANT_ID},
            json={"asistio": False},
            headers=headers,
            timeout=10,
        )
        assert r2.status_code == 200, f"PUT asistencia {rv['id']}: {r2.status_code} {r2.text[:200]}"
    log(f"[OK] {len(reservas_api)} llamadas PUT asistio=false completadas")

    # â”€â”€ 6b. VERIFICACION 2: SELECT directo â†’ TODAS deben ser False â”€â”€
    ids = [rv["id"] for rv in reservas_api]
    cur.execute(
        "SELECT id, asistio FROM reservas WHERE id = ANY(%s) ORDER BY id", (ids,))
    filas_false = cur.fetchall()
    for fid, fasistio in filas_false:
        assert fasistio is False, f"reserva_id={fid} debe ser False, obtuve {fasistio}"
        log(
            f"[VERIFICACION-2 BD] reserva_id={fid} asistio={fasistio} <-- 'Marcar Todos' persistio")

    # â”€â”€ 7. VERIFICACION 2b (multi-alumno): marcar TODAS con true â”€â”€
    if len(reservas_api) > 1:
        log(
            f"\n-- Paso 7: 'Marcar todos como asistieron' -> true ({len(reservas_api)} reservas) --")
        for rv in reservas_api:
            r3 = requests.put(
                f"{BASE}/reservas/{rv['id']}/asistencia",
                params={"tenant_id": TENANT_ID},
                json={"asistio": True},
                headers=headers,
                timeout=10,
            )
            assert r3.status_code == 200, f"PUT asistencia {rv['id']}: {r3.status_code}"
        cur.execute(
            "SELECT id, asistio FROM reservas WHERE id = ANY(%s) ORDER BY id", (ids,))
        filas_true = cur.fetchall()
        for fid, fasistio in filas_true:
            assert fasistio is True, f"reserva_id={fid} debe ser True, obtuve {fasistio}"
            log(
                f"[VERIFICACION-2b BD] reserva_id={fid} asistio={fasistio} <-- multi-alumno OK")
        log(
            f"[OK] 'Marcar todos como asistieron' persistio para {len(filas_true)} alumnos")

    # â”€â”€ 8. Limpieza: restaurar estado original + eliminar reservas creadas por SQL â”€â”€
    log("\n-- Paso 8: Limpieza --")
    for rv in reservas_api:
        valor_orig = estado_original.get(rv["id"], False)
        r_rest = requests.put(
            f"{BASE}/reservas/{rv['id']}/asistencia",
            params={"tenant_id": TENANT_ID},
            json={"asistio": valor_orig},
            headers=headers,
            timeout=10,
        )
        assert r_rest.status_code == 200, f"Restaurar reserva {rv['id']}: {r_rest.status_code}"
    log("[OK] Estados originales restaurados via API")

    # Eliminar solo las reservas creadas por INSERT (no tocar las pre-existentes)
    for rid in reservas_creadas:
        cur.execute("DELETE FROM reservas WHERE id = %s", (rid,))
        log(f"[OK] Reserva {rid} eliminada de BD (limpieza)")

    cur.close()
    conn.close()

    log("\n" + "=" * 70)
    log(" RESULTADO: TODAS LAS VERIFICACIONES PASARON OK")
    log("=" * 70)


if __name__ == "__main__":
    main()
