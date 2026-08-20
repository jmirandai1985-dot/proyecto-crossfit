"""
VERIFICACIÃ“N END-TO-END (TEST / small-butterfly)
Flujo: Admin â†’ Coach (jesus id=7) â†’ Alumno Demo (id=5)

Ejecutar SOLO con ENVIRONMENT=test (lo setea este script antes de importar app).
Reporta evidencia literal (JSON + valores BD) para cada paso.
"""
import requests
import psycopg2
import os
import sys
import json
import importlib
from datetime import date, timedelta

# â”€â”€ SEGURIDAD: forzar ENVIRONMENT=test ANTES de importar app â”€â”€
os.environ["ENVIRONMENT"] = "test"

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)

# Verificar que la URL apunta a small-butterfly (nunca prod)
settings = importlib.import_module("app.core.config").settings
DB_URL = settings.DATABASE_URL
if "small-butterfly" not in DB_URL:
    sys.exit("FATAL: La URL NO es small-butterfly (test). Abortando para proteger datos.")


BASE = "http://localhost:8000/api/v1"
TENANT_ID = 1
COACH_ID = 7
ALUMNO_ID = 5
DISCIPLINA_ID = 1  # CrossFit
HOY = date.today()
MANANA = HOY + timedelta(days=1)

# Credenciales de BD test para consultas directas
TEST_DB_URL = DB_URL


def get_db_conn():
    return psycopg2.connect(TEST_DB_URL)


def q(label, sql, params=None):
    """Ejecuta query SQL y muestra evidencia literal."""
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute(sql, params or ())
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        print(f"  {label}:")
        if not rows:
            print("    (sin filas)")
        for r in rows:
            print(
                f"    {json.dumps(dict(zip(cols, r)), default=str, ensure_ascii=False)}")
        return rows
    finally:
        cur.close()
        conn.close()


def request(method, url, **kwargs):
    r = requests.request(method, url, **kwargs)
    try:
        body = r.json()
    except Exception:
        body = r.text[:500]
    print(f"  {method} {url}")
    print(f"    Status: {r.status_code}")
    print(
        f"    Respuesta: {json.dumps(body, default=str, ensure_ascii=False, indent=4) if not isinstance(body, str) else body}")
    return r, body


def generar_token(usuario_id, rol, nombre):
    """Genera JWT igual que los tests (app.core.security.create_access_token)."""
    from app.core.security import create_access_token
    return create_access_token({
        "usuario_id": usuario_id,
        "tenant_id": TENANT_ID,
        "rol": rol,
        "correo": f"token-{usuario_id}@test.com",
        "nombre": nombre
    })


print("=" * 70)
print("  VERIFICACIÃ“N END-TO-END: ADMIN â†’ COACH (jesus=7) â†’ ALUMNO (id=5)")
print(f"  BD: {DB_URL.split('@')[1][:30]}...")
print(f"  Fecha hoy: {HOY} | MaÃ±ana: {MANANA}")
print("=" * 70)

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# PASO 1 â€” ADMIN
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
print("\n" + "=" * 70)
print("  PASO 1 â€” ADMIN: coach jesus + clase crossfit")
print("=" * 70)

# 1a. Coach jesus
q("Coach usuario id=7",
  """SELECT id, nombre, rol, activo, correo FROM usuarios WHERE id=%s""",
  (COACH_ID,))

q("Coach-disciplina (7â†’1 crossfit)",
  """SELECT id, tenant_id, coach_id, disciplina_id, activo FROM coach_disciplinas
     WHERE coach_id=%s AND disciplina_id=%s AND tenant_id=%s""",
  (COACH_ID, DISCIPLINA_ID, TENANT_ID))

# 1b. Disciplina crossfit
q("Disciplina id=1",
  """SELECT id, nombre, activo, requiere_coach FROM disciplinas WHERE id=%s AND tenant_id=%s""",
  (DISCIPLINA_ID, TENANT_ID))

# 1c. Clases crossfit prÃ³ximos 7 dÃ­as (visibles por filtro disciplina)
FECHA_MAX = HOY + timedelta(days=7)
filas_clases = q("Clases crossfit (prÃ³ximos 7 dÃ­as) â€” visibilidad por disciplina",
                 """SELECT c.id, c.fecha, c.hora_inicio, c.hora_fin, c.coach_id, c.wod_id,
            c.cupo_maximo, c.asistentes_confirmados,
            d.nombre AS disciplina_nombre, u.nombre AS coach_nombre
     FROM clases c
     LEFT JOIN disciplinas d ON c.disciplina_id = d.id
     LEFT JOIN usuarios u ON c.coach_id = u.id
     WHERE c.tenant_id=%s AND c.disciplina_id=%s
       AND c.fecha >= %s AND c.fecha <= %s
       AND c.cancelada = false
     ORDER BY c.fecha, c.hora_inicio""",
                 (TENANT_ID, DISCIPLINA_ID, HOY, FECHA_MAX))

# Elegir la primera clase crossfit disponible (hoy o prÃ³ximos dÃ­as)
clase_elegida = None
if filas_clases:
    clase_elegida = filas_clases[0]

if clase_elegida is None:
    print("\n[ERROR] No hay clase crossfit en los prÃ³ximos 7 dÃ­as â†’ no se puede continuar.")
    sys.exit(1)

CLASE_ID = clase_elegida[0]
print(f"\n  â†’ Clase elegida: id={CLASE_ID}, fecha={clase_elegida[1]}, hora={clase_elegida[2]}-{clase_elegida[3]}, "
      f"coach_id={clase_elegida[4]}, coach_nombre={clase_elegida[9]}")

# Verificar rol del coach jesus (para saber si usa validaciÃ³n de disciplina o bypass admin)
q("Rol/estado actual de jesus (id=7)",
  """SELECT id, nombre, rol, activo FROM usuarios WHERE id=%s""", (COACH_ID,))
row_rol = q("Rol para decisiÃ³n",
            "SELECT rol FROM usuarios WHERE id=%s", (COACH_ID,))
ROL_COACH = row_rol[0][0] if row_rol else None
print(f"  â†’ Rol de jesus: {ROL_COACH}")

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# PASO 2 â€” COACH publica WOD
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
print("\n" + "=" * 70)
print("  PASO 2 â€” COACH publica WOD vÃ­a API (POST /wods/ + POST /wods/batch)")
print("=" * 70)

# Token del coach jesus
COACH_TOKEN = generar_token(COACH_ID, ROL_COACH, "jesus")
HEADERS = {"Authorization": f"Bearer {COACH_TOKEN}"}
print(f"  Token coach jesus (id=7) generado OK")

# 2a. Obtener un movimiento disponible (vÃ­a BD para evitar output enorme)
movs_bd = q("Movimiento disponible para WOD",
            "SELECT id, nombre FROM movimientos WHERE tenant_id=%s AND activo=true ORDER BY id LIMIT 1",
            (TENANT_ID,))
if not movs_bd:
    print("\n[ERROR] No hay movimientos en BD â†’ no se puede crear WOD.")
    sys.exit(1)
mov_id = movs_bd[0][0]
nombre_mov = movs_bd[0][1]
print(f"  Movimiento elegido: id={mov_id}, nombre='{nombre_mov}'")

# 2b. Si la clase ya tiene WOD asignado (de una corrida anterior), reutilizarlo
fecha_wod = str(clase_elegida[1])
WOD_ID = clase_elegida[5]  # c.wod_id de la query de clases

if WOD_ID is None:
    hora_inicio = str(clase_elegida[2]) if clase_elegida[2] else None
    hora_fin = str(clase_elegida[3]) if clase_elegida[3] else None

    payload_wod = {
        "tenant_id": TENANT_ID,
        "fecha": fecha_wod,
        "hora_inicio": hora_inicio,
        "hora_fin": hora_fin,
        "titulo": "WOD VerificaciÃ³n E2E jesus",
        "descripcion": "15 min AMRAP",
        "calentamiento": "Movilidad articular 5min",
        "fuerza_habilidad": f"{nombre_mov} 5x3 @ 70%",
        "wod_principal": "AMRAP 12: 10 Burpees + 15 Air Bike",
        "tipo_metcon": "AMRAP",
        "coach_id": COACH_ID,
        "estado": "publicado",
        "movimientos": []
    }

    params_wod = {"tenant_id": TENANT_ID, "disciplina_id": DISCIPLINA_ID}
    r_wod, wod_resp = request("POST", f"{BASE}/wods/", params=params_wod,
                              headers=HEADERS, json=payload_wod)

    if r_wod.status_code not in (200, 201) or not isinstance(wod_resp, dict) or "id" not in wod_resp:
        print(f"\n[ERROR] Crear WOD fallÃ³ â†’ reportar sin aplicar fix.")
        sys.exit(1)

    WOD_ID = wod_resp["id"]
    print(f"  â†’ WOD creado: id={WOD_ID}")

    # 2c. POST /wods/batch â€” asignar WOD a la clase elegida
    r_batch, batch_resp = request("POST", f"{BASE}/wods/batch",
                                  params={"tenant_id": TENANT_ID},
                                  headers=HEADERS,
                                  json={"wod_id": WOD_ID, "clase_ids": [CLASE_ID]})
    if r_batch.status_code != 200:
        print(f"\n[ERROR] Batch fallÃ³ â†’ reportar sin aplicar fix.")
        sys.exit(1)
    print(f"  â†’ Batch OK: {batch_resp.get('mensaje')}")
else:
    print(f"  â†’ Clase ya tenÃ­a WOD id={WOD_ID}; reutilizando (sin POST).")
    # Verificar que el WOD existente pertenece al coach jesus
    q("WOD existente (coach_id)",
      "SELECT id, fecha, titulo, coach_id, estado FROM wods WHERE id=%s", (WOD_ID,))

# 2d. Verificar en BD que clase.wod_id y clase.coach_id quedaron seteados
q("VerificaciÃ³n BD: clase tras batch (wod_id, coach_id)",
  """SELECT id, fecha, disciplina_id, coach_id, wod_id FROM clases WHERE id=%s""",
  (CLASE_ID,))

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# PASO 3 â€” ALUMNO
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
print("\n" + "=" * 70)
print("  PASO 3 â€” ALUMNO (id=5 Alumno Demo)")
print("=" * 70)

# 3a. Datos del alumno
q("Alumno id=5",
  """SELECT id, nombre, rol, activo, correo FROM usuarios WHERE id=%s""",
  (ALUMNO_ID,))

# 3b. SuscripciÃ³n activa (crÃ©ditos antes) â€” mismo orden que el endpoint:
#    creditos_disponibles DESC NULLS LAST (asÃ­ la elegida tendrÃ¡ crÃ©ditos)
antes_rows = q("SuscripciÃ³n activa del alumno (ANTES reserva)",
               """SELECT id, plan_id, estado, creditos_disponibles, creditos_totales, fecha_expiracion
     FROM suscripciones
     WHERE usuario_id=%s AND tenant_id=%s AND estado='activo'
       AND fecha_expiracion > NOW()
     ORDER BY creditos_disponibles DESC NULLS LAST, fecha_expiracion DESC""",
               (ALUMNO_ID, TENANT_ID))
if not antes_rows:
    print("\n[ERROR] Alumno 5 NO tiene suscripciÃ³n activa â†’ la reserva fallarÃ¡.")
    SUSC_ID = None
    CREDITOS_ANTES = None
else:
    SUSC_ID = antes_rows[0][0]
    CREDITOS_ANTES = antes_rows[0][3]
    print(f"  â†’ SuscripciÃ³n activa id={SUSC_ID}, crÃ©ditos={CREDITOS_ANTES}")

# 3c. GET /clases (como lo harÃ­a el frontend del alumno) â€” la clase debe aparecer
r_clases, clases_resp = request("GET", f"{BASE}/clases",
                                params={"tenant_id": TENANT_ID,
                                        "disciplina_id": DISCIPLINA_ID,
                                        "fecha": fecha_wod})
clase_encontrada = None
if isinstance(clases_resp, list):
    for c in clases_resp:
        if c.get("id") == CLASE_ID:
            clase_encontrada = c
            break
if clase_encontrada:
    print(f"  â†’ Clase {CLASE_ID} aparece en GET /clases âœ“")
    print(f"    coach_nombre={clase_encontrada.get('coach_nombre')} | coach_id={clase_encontrada.get('coach_id')} | wod_id={clase_encontrada.get('wod_id')}")
    if clase_encontrada.get("coach_nombre") == "jesus":
        print("  â†’ coach_nombre='jesus' âœ“ (vÃ­a campo directo o fallback de disciplina)")
    else:
        print(
            f"  âš ï¸  coach_nombre='{clase_encontrada.get('coach_nombre')}' (esperado 'jesus')")
else:
    print("  âš ï¸  Clase no apareciÃ³ en GET /clases")

# 3d. GET /wods/hoy con alumno_id â€” ANTES de reserva (debe ser None o el WOD si ya tiene reserva)
r_wod_hoy_antes, wod_hoy_antes = request("GET", f"{BASE}/wods/hoy",
                                         params={"tenant_id": TENANT_ID, "alumno_id": ALUMNO_ID})
if wod_hoy_antes is None:
    print("  â†’ /wods/hoy antes de reserva: None (esperado si alumno no tiene reserva hoy)")

# 3e. POST /reservas â€” simular reserva del alumno en la clase
if SUSC_ID is not None:
    # Verificar si el alumno ya tiene una reserva activa en esa clase
    r_res_exist, res_exist = request("GET", f"{BASE}/reservas/por-clase/{CLASE_ID}",
                                     params={"tenant_id": TENANT_ID})
    ya_reservada = False
    if isinstance(res_exist, list):
        for rsv in res_exist:
            if rsv.get("alumno_id") == ALUMNO_ID and rsv.get("activa"):
                ya_reservada = True
                print(
                    f"  â„¹ï¸  Alumno ya tiene reserva activa id={rsv.get('id')} en clase {CLASE_ID}")
                # Re-verificar crÃ©dito descontado
                q("CrÃ©ditos tras reserva existente",
                  """SELECT creditos_disponibles FROM suscripciones WHERE id=%s""", (SUSC_ID,))
    if not ya_reservada:
        r_reserva, reserva_resp = request("POST", f"{BASE}/reservas", json={
            "tenant_id": TENANT_ID,
            "clase_id": CLASE_ID,
            "alumno_id": ALUMNO_ID,
            "estado": "confirmada"
        })
        if r_reserva.status_code == 201:
            print(
                f"  â†’ Reserva creada: id={reserva_resp.get('id')}, estado={reserva_resp.get('estado')}")
        else:
            print(f"  âš ï¸  Reserva fallÃ³: {reserva_resp}")

    # 3f. Verificar crÃ©dito descontado
    q("SuscripciÃ³n (DESPUÃ‰S reserva) â€” debe ser 1 menos",
      """SELECT id, creditos_disponibles FROM suscripciones WHERE id=%s""", (SUSC_ID,))

    # 3g. Asistentes confirmados incrementado
    q("Clase asistentes_confirmados (debe ser > 0)",
      """SELECT id, asistentes_confirmados, cupo_maximo FROM clases WHERE id=%s""", (CLASE_ID,))

# 3h. GET /wods/hoy con alumno_id â€” DESPUÃ‰S de reserva
r_wod_hoy, wod_hoy = request("GET", f"{BASE}/wods/hoy",
                             params={"tenant_id": TENANT_ID, "alumno_id": ALUMNO_ID})
if wod_hoy is not None:
    print(
        f"  â†’ WOD de hoy visible para alumno: '{wod_hoy.get('titulo')}' (id={wod_hoy.get('id')}) âœ“")
else:
    # Puede ser que la clase sea de maÃ±ana â†’ /wods/hoy no aplica hoy
    print(
        f"  â†’ /wods/hoy devolviÃ³ None (la clase es de {fecha_wod}; si es maÃ±ana, es esperado)")

print("\n" + "=" * 70)
print("  VERIFICACIÃ“N COMPLETADA")
print("=" * 70)
