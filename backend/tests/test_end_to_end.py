"""
Test de Integración End-to-End — Flujo completo 3 roles (Admin, Alumno, Coach).
Cubre los 8 pasos del ciclo de vida real de un alumno en el Box CrossFit.
Cada paso verifica con evidencia (SQL o HTTP), no solo que "no tire error".
Usa un alumno DEDICADO (id=8888) creado ad-hoc, que se limpia al final.
"""
import pytest
import requests
import psycopg2
from datetime import date, timedelta, datetime, timezone

from tests.conftest import BASE, TENANT_ID

# ── Datos del alumno dedicado para este test ──
E2E_ALUMNO_ID = 8888
E2E_CORREO = "e2e.test@example.com"
E2E_PASSWORD = "TestPass123!"
E2E_RUT = "88.888.888-8"
E2E_NOMBRE = "Alumno E2E Test"

# Admin y coach de prueba (existentes en test DB)
ADMIN_ID = 1001
COACH_ID = 1000

# Estado compartido entre pasos


class SharedE2E:
    alumno_id = None
    password_generada = None
    token_alumno = None
    solicitud_id = None
    voucher_url = None
    suscripcion_id = None
    creditos_iniciales = None
    clase_id = None
    disciplina_id = None
    wod_id = None
    rm_id = None
    movimiento_id = None
    plan_id = 1   # CrossFit básico


def get_db_conn():
    """Retorna conexión SQL directa a la DB test (muddy-term)."""
    DB = 'postgresql://neondb_owner:npg_dgH4Goce5DkB@ep-muddy-term-aclwd3w7-pooler.sa-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require'
    return psycopg2.connect(DB)


def limpiar_alumno_e2e():
    """Elimina todos los datos creados por el test E2E."""
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        # Orden inverso de creación
        cur.execute("DELETE FROM historial_rm WHERE alumno_id = %s",
                    (E2E_ALUMNO_ID,))
        cur.execute("""
            DELETE FROM reservas WHERE alumno_id = %s
        """, (E2E_ALUMNO_ID,))
        cur.execute("""
            DELETE FROM suscripciones WHERE usuario_id = %s
        """, (E2E_ALUMNO_ID,))
        cur.execute("""
            DELETE FROM solicitudes_planes WHERE alumno_id = %s
        """, (E2E_ALUMNO_ID,))
        cur.execute("""
            DELETE FROM notificaciones WHERE alumno_id = %s
        """, (E2E_ALUMNO_ID,))
        cur.execute("""
            DELETE FROM usuarios WHERE id = %s
        """, (E2E_ALUMNO_ID,))
        conn.commit()
        print(f"  🧹 Limpieza E2E completada para alumno {E2E_ALUMNO_ID}")
    except Exception as e:
        conn.rollback()
        print(f"  ⚠️ Error en limpieza (no crítico): {e}")
    finally:
        cur.close()
        conn.close()


# ===================================================================
# PASO 1 — Admin crea un alumno nuevo
# ===================================================================

def test_e2e_01_admin_crea_alumno():
    """[Paso 1] Admin crea un alumno nuevo → verifica que se genera contraseña."""
    # Primero limpiar por si quedó de una ejecución anterior
    limpiar_alumno_e2e()

    # Crear alumno con contraseña explícita (como haría el admin)
    r = requests.post(f"{BASE}/usuarios/", json={
        "tenant_id": TENANT_ID,
        "rut": E2E_RUT,
        "nombre": E2E_NOMBRE,
        "telefono": "+56988888888",
        "correo": E2E_CORREO,
        "password": E2E_PASSWORD,
        "rol": "alumno"
    })
    assert r.status_code == 201, f"Crear alumno falló: {r.status_code} - {r.text[:200]}"
    data = r.json()
    assert data.get("id") is not None, "No se devolvió id del alumno"
    assert data.get("activo") == True, "El alumno debe estar activo"
    SharedE2E.alumno_id = data["id"]
    print(f"  ✅ Alumno creado: id={SharedE2E.alumno_id}, correo={E2E_CORREO}")

    # Verificar en SQL que el password_hash NO está vacío
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT password_hash FROM usuarios WHERE id = %s", (SharedE2E.alumno_id,))
        row = cur.fetchone()
        assert row is not None, "Alumno no encontrado en DB"
        assert row[0] is not None and len(row[0]) > 20, \
            f"password_hash inválido: {row[0] if row else None}"
        print(f"  ✅ Password hash verificado en DB (longitud={len(row[0])})")
    finally:
        cur.close()
        conn.close()


def test_e2e_02_alumno_login_y_elige_plan():
    """[Paso 2] Alumno hace login con esa contraseña y elige un plan (crea solicitud)."""
    assert SharedE2E.alumno_id is not None

    # 2a. Login
    r = requests.post(f"{BASE}/auth/login", json={
        "correo": E2E_CORREO,
        "password": E2E_PASSWORD
    })
    assert r.status_code == 200, f"Login falló: {r.status_code} - {r.text[:200]}"
    data = r.json()
    assert data.get("access_token") is not None, "No se generó token JWT"
    assert data.get("usuario_id") == SharedE2E.alumno_id, \
        f"usuario_id no coincide: {data.get('usuario_id')} != {SharedE2E.alumno_id}"
    SharedE2E.token_alumno = data["access_token"]
    print(f"  ✅ Login exitoso, token JWT generado")

    # 2b. Obtener lista de planes (verificar que existe plan_id=1)
    r = requests.get(f"{BASE}/planes", params={"tenant_id": TENANT_ID})
    assert r.status_code == 200, f"Listar planes falló: {r.status_code}"
    planes = r.json()
    plan_crossfit = None
    for p in planes:
        if p.get("id") == SharedE2E.plan_id:
            plan_crossfit = p
            break
    assert plan_crossfit is not None, f"Plan id={SharedE2E.plan_id} no encontrado"
    assert plan_crossfit.get("activo", True), "El plan debe estar activo"
    print(
        f"  ✅ Plan encontrado: {plan_crossfit.get('nombre')} (id={SharedE2E.plan_id})")

    # 2c. Crear solicitud de plan
    r = requests.post(f"{BASE}/solicitudes/solicitar", json={
        "tenant_id": TENANT_ID,
        "alumno_id": SharedE2E.alumno_id,
        "plan_id": SharedE2E.plan_id,
        "voucher_url": None,
        "certificado_estudiante_url": None
    })
    assert r.status_code == 201, f"Crear solicitud falló: {r.status_code} - {r.text[:200]}"
    solicitud_data = r.json()
    assert solicitud_data.get(
        "id") is not None, "No se devolvió id de solicitud"
    assert solicitud_data.get("status") == "pending", \
        f"Estado debe ser 'pending', obtenido: {solicitud_data.get('status')}"
    SharedE2E.solicitud_id = solicitud_data["id"]
    print(f"  ✅ Solicitud creada: id={SharedE2E.solicitud_id}, estado=pending")

    # Verificar en SQL que la solicitud existe y está pendiente
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT estado FROM solicitudes_planes WHERE id = %s", (SharedE2E.solicitud_id,))
        row = cur.fetchone()
        assert row is not None, "Solicitud no encontrada en DB"
        assert row[0] == "pending", f"Estado en DB debe ser 'pending', obtenido: {row[0]}"
        print(f"  ✅ Estado 'pending' verificado en DB")
    finally:
        cur.close()
        conn.close()


def test_e2e_03_alumno_carga_voucher():
    """[Paso 3] Alumno carga un voucher de pago."""
    # Simular subida de voucher: crear un archivo temporal en memoria
    # El endpoint espera multipart/form-data con el archivo
    # Creamos un pequeño JPEG simulado (1x1 pixel)
    fake_jpeg = b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.\' ", # \x1c\x1c(7),014\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c\x1c\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x11\x04\x12!1A\x06\x13Qa\x07"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82\t\n\x16\x17\x18\x19\x1a%&\'()*456789:CDEFGHIJSTUVWXYZcdefghijstuvwxyz\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xc4\x00\x1f\x01\x01\x01\x01\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x11\x00\x02\x01\x02\x04\x04\x03\x04\x07\x05\x04\x04\x00\x01\x02\x77\x00\x01\x02\x03\x11\x04\x05!1\x06\x12AQ\x07aq\x13"2\x81\x08\x14B\x91\xa1\xb1\xc1\t#3R\x15\xf0\x16$br\x82\n\x17\x18\x19\x1a%&\'()*456789:CDEFGHIJSTUVWXYZcdefghijstuvwxyz\x82\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xda\x00\x08\x01\x01\x00\x00?\x00~\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xd9'
    r = requests.post(f"{BASE}/upload/voucher",
                      files={"file": ("voucher_test.jpg", fake_jpeg, "image/jpeg")})
    assert r.status_code == 201, f"Subir voucher falló: {r.status_code} - {r.text[:200]}"
    data = r.json()
    assert data.get("url") is not None, "No se devolvió URL del voucher"
    SharedE2E.voucher_url = data["url"]
    print(f"  ✅ Voucher subido: url={SharedE2E.voucher_url}")

    # Actualizar la solicitud con el voucher_url
    # (Como no hay endpoint PUT para solicitud, lo hacemos directo en SQL)
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE solicitudes_planes SET voucher_url = %s WHERE id = %s",
            (SharedE2E.voucher_url, SharedE2E.solicitud_id)
        )
        conn.commit()
        # Verificar
        cur.execute(
            "SELECT voucher_url FROM solicitudes_planes WHERE id = %s", (SharedE2E.solicitud_id,))
        row = cur.fetchone()
        assert row is not None, "Solicitud no encontrada"
        assert row[0] == SharedE2E.voucher_url, f"voucher_url no actualizado en DB: {row[0]}"
        print(f"  ✅ Voucher URL guardado en solicitud (DB verificada)")
    finally:
        cur.close()
        conn.close()


def test_e2e_04_admin_activa_plan():
    """[Paso 4] Admin revisa solicitud pendiente y activa el plan."""
    assert SharedE2E.solicitud_id is not None

    # 4a. Admin lista solicitudes pendientes
    r = requests.get(f"{BASE}/solicitudes/pendientes",
                     params={"tenant_id": TENANT_ID})
    assert r.status_code == 200, f"Listar pendientes falló: {r.status_code}"
    pendientes = r.json()
    ids_pendientes = [s["id"] for s in pendientes]
    assert SharedE2E.solicitud_id in ids_pendientes, \
        f"Solicitud {SharedE2E.solicitud_id} no está en pendientes: {ids_pendientes}"
    print(f"  ✅ Solicitud visible en pendientes ({len(pendientes)} total)")

    # 4b. Admin aprueba la solicitud
    r = requests.put(
        f"{BASE}/solicitudes/{SharedE2E.solicitud_id}/aprobar",
        params={"admin_id": ADMIN_ID}
    )
    assert r.status_code == 200, f"Aprobar solicitud falló: {r.status_code} - {r.text[:200]}"
    data = r.json()
    assert data.get("status") == "approved", \
        f"Estado debe ser 'approved', obtenido: {data.get('status')}"
    print(f"  ✅ Solicitud aprobada por admin {ADMIN_ID}")

    # 4c. Verificar en SQL que la suscripción se creó con estado 'activo'
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, estado, creditos_totales, creditos_disponibles 
            FROM suscripciones 
            WHERE usuario_id = %s AND estado = 'activo'
            ORDER BY created_at DESC LIMIT 1
        """, (SharedE2E.alumno_id,))
        row = cur.fetchone()
        assert row is not None, "No se encontró suscripción activa en DB"
        SharedE2E.suscripcion_id = row[0]
        SharedE2E.creditos_iniciales = row[3]
        assert row[1] == "activo", f"Estado debe ser 'activo', obtenido: {row[1]}"
        assert SharedE2E.creditos_iniciales > 0, \
            f"Créditos disponibles debe ser > 0, obtenido: {SharedE2E.creditos_iniciales}"
        print(f"  ✅ Suscripción activa verificada en DB: id={row[0]}, "
              f"créditos={SharedE2E.creditos_iniciales}")
    finally:
        cur.close()
        conn.close()

    # 4d. Verificar que la solicitud ya no aparece como pendiente
    r = requests.get(f"{BASE}/solicitudes/pendientes",
                     params={"tenant_id": TENANT_ID})
    assert r.status_code == 200
    pendientes = r.json()
    assert SharedE2E.solicitud_id not in [s["id"] for s in pendientes], \
        "La solicitud aprobada aún aparece como pendiente"
    print(f"  ✅ Solicitud ya no aparece en pendientes")


def test_e2e_05_alumno_agenda_clase():
    """[Paso 5] Alumno agenda una clase de CrossFit."""
    assert SharedE2E.alumno_id is not None
    assert SharedE2E.creditos_iniciales is not None

    # 5a. Buscar una clase disponible para HOY o mañana (CrossFit = disciplina_id=3 o similar)
    # Primero obtener disciplinas para saber id de CrossFit
    r = requests.get(f"{BASE}/disciplinas", params={"tenant_id": TENANT_ID})
    assert r.status_code == 200, f"Listar disciplinas falló: {r.status_code}"
    disciplinas = r.json()
    # Buscar CrossFit
    disciplina_cf = None
    for d in disciplinas:
        if "crossfit" in d.get("nombre", "").lower() or "crossfit" in d.get("slug", "").lower():
            disciplina_cf = d
            break
    if not disciplina_cf and len(disciplinas) > 0:
        disciplina_cf = disciplinas[0]  # fallback: primera disciplina
    assert disciplina_cf is not None, "No se encontró disciplina CrossFit"
    SharedE2E.disciplina_id = disciplina_cf["id"]
    print(
        f"  ✅ Disciplina encontrada: {disciplina_cf.get('nombre')} (id={SharedE2E.disciplina_id})")

    # 5b. Buscar clases disponibles HOY de CrossFit
    hoy = date.today()
    r = requests.get(f"{BASE}/clases/", params={
        "tenant_id": TENANT_ID,
        "disciplina_id": SharedE2E.disciplina_id,
        "fecha": str(hoy),
        "solo_con_cupo": True,
        "limit": 5
    })
    assert r.status_code == 200, f"Buscar clases falló: {r.status_code}"
    clases = r.json()
    # Si no hay clases hoy, buscar mañana
    if not clases:
        manana = hoy + timedelta(days=1)
        r = requests.get(f"{BASE}/clases/", params={
            "tenant_id": TENANT_ID,
            "disciplina_id": SharedE2E.disciplina_id,
            "fecha": str(manana),
            "solo_con_cupo": True,
            "limit": 5
        })
        assert r.status_code == 200
        clases = r.json()
        if clases:
            print(f"  ℹ️  Usando clase de mañana ({manana})")
    assert len(clases) > 0, f"No hay clases disponibles de CrossFit"
    clase = clases[0]
    SharedE2E.clase_id = clase["id"]
    print(f"  ✅ Clase encontrada: id={clase['id']}, fecha={clase['fecha']}, "
          f"hora={clase['hora_inicio']}-{clase['hora_fin']}")

    # 5c. Crear reserva
    r = requests.post(f"{BASE}/reservas", json={
        "tenant_id": TENANT_ID,
        "clase_id": SharedE2E.clase_id,
        "alumno_id": SharedE2E.alumno_id,
        "estado": "confirmada"
    })
    assert r.status_code == 201, f"Crear reserva falló: {r.status_code} - {r.text[:200]}"
    reserva = r.json()
    assert reserva.get("id") is not None, "No se devolvió id de reserva"
    assert reserva.get("estado") == "confirmada", \
        f"Estado debe ser 'confirmada', obtenido: {reserva.get('estado')}"
    print(f"  ✅ Reserva creada: id={reserva['id']}")

    # 5d. Verificar en SQL el cupo descontado
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT asistentes_confirmados, cupo_maximo 
            FROM clases WHERE id = %s
        """, (SharedE2E.clase_id,))
        row = cur.fetchone()
        assert row is not None, "Clase no encontrada en DB"
        assert row[0] > 0, f"asistentes_confirmados debe ser > 0, obtenido: {row[0]}"
        assert row[0] <= row[1], \
            f"asistentes_confirmados ({row[0]}) no debe exceder cupo_maximo ({row[1]})"
        print(f"  ✅ Cupo descontado verificado en DB: {row[0]}/{row[1]}")

        # Verificar crédito descontado
        cur.execute("""
            SELECT creditos_disponibles FROM suscripciones 
            WHERE id = %s
        """, (SharedE2E.suscripcion_id,))
        row2 = cur.fetchone()
        assert row2 is not None, "Suscripción no encontrada en DB"
        creditos_restantes = row2[0]
        assert creditos_restantes == SharedE2E.creditos_iniciales - 1, \
            f"Créditos deberían ser {SharedE2E.creditos_iniciales - 1}, obtenido: {creditos_restantes}"
        print(
            f"  ✅ Crédito descontado: {SharedE2E.creditos_iniciales} → {creditos_restantes}")
    finally:
        cur.close()
        conn.close()


def test_e2e_06_coach_genera_wod():
    """[Paso 6] Coach genera un WOD para esa clase."""
    assert SharedE2E.clase_id is not None

    from tests.conftest import get_coach_token

    # 6a. Obtener movimientos disponibles
    r = requests.get(f"{BASE}/movimientos", params={"tenant_id": TENANT_ID})
    assert r.status_code == 200, f"Listar movimientos falló: {r.status_code}"
    movimientos = r.json()
    assert len(movimientos) > 0, "No hay movimientos en la BD"
    # Guardar un movimiento_id para el test de RM posterior
    SharedE2E.movimiento_id = movimientos[0]["id"]
    print(f"  ✅ Movimientos disponibles: {len(movimientos)}")

    # 6b. Obtener la clase para saber fecha, hora
    r = requests.get(f"{BASE}/clases/{SharedE2E.clase_id}",
                     params={"tenant_id": TENANT_ID})
    assert r.status_code == 200, f"Obtener clase falló: {r.status_code}"
    clase = r.json()
    print(f"  ✅ Datos de clase: fecha={clase['fecha']}, "
          f"hora={clase['hora_inicio']}-{clase['hora_fin']}")

    # 6c. Crear WOD con token de coach
    coach_token = get_coach_token()
    headers = {"Authorization": f"Bearer {coach_token}"}

    descripcion_wod = """CALENTAMIENTO
    Movilidad articular 5min
    FUERZA
    Clean 5x3 @ 75%
    WOD
    AMRAP 12 minutos
    10 Burpees
    15 Air Bike"""

    r = requests.post(
        f"{BASE}/wods/?tenant_id={TENANT_ID}&disciplina_id={SharedE2E.disciplina_id}",
        headers=headers,
        json={
            "tenant_id": TENANT_ID,
            "fecha": clase["fecha"],
            "hora_inicio": clase["hora_inicio"],
            "hora_fin": clase["hora_fin"],
            "titulo": "WOD E2E Test",
            "descripcion": descripcion_wod,
            "coach_id": COACH_ID,
            "estado": "publicado",
            "movimientos": []
        }
    )
    assert r.status_code in (200, 201), \
        f"Crear WOD falló: {r.status_code} - {r.text[:300]}"
    wod_data = r.json()
    assert wod_data.get("id") is not None, "No se devolvió id de WOD"
    SharedE2E.wod_id = wod_data["id"]
    print(
        f"  ✅ WOD creado: id={SharedE2E.wod_id}, titulo='{wod_data.get('titulo', '')}'")

    # 6d. Asignar WOD a la clase
    r = requests.post(
        f"{BASE}/wods/clases/{SharedE2E.clase_id}/asignar-wod/{SharedE2E.wod_id}",
        params={"tenant_id": TENANT_ID},
        headers=headers
    )
    assert r.status_code == 200, \
        f"Asignar WOD a clase falló: {r.status_code} - {r.text[:200]}"
    print(f"  ✅ WOD asignado a clase {SharedE2E.clase_id}")

    # 6e. Verificar en SQL que el WOD quedó asociado
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT wod_id FROM clases WHERE id = %s", (SharedE2E.clase_id,))
        row = cur.fetchone()
        assert row is not None, "Clase no encontrada en DB"
        assert row[0] == SharedE2E.wod_id, \
            f"wod_id en clase debe ser {SharedE2E.wod_id}, obtenido: {row[0]}"
        print(f"  ✅ WOD asociado a clase verificado en DB")
    finally:
        cur.close()
        conn.close()


def test_e2e_07_alumno_consulta_wod_hoy():
    """[Paso 7] Alumno consulta 'WOD de hoy' y verifica descuento de crédito."""
    assert SharedE2E.alumno_id is not None
    assert SharedE2E.token_alumno is not None
    assert SharedE2E.wod_id is not None

    # 7a. Consultar créditos ANTES (para verificar descuento después de la reserva)
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT creditos_disponibles FROM suscripciones 
            WHERE id = %s
        """, (SharedE2E.suscripcion_id,))
        row = cur.fetchone()
        creditos_antes = row[0] if row else 0
        print(f"  ℹ️  Créditos disponibles actualmente: {creditos_antes}")
    finally:
        cur.close()
        conn.close()

    # 7b. Consultar WOD de hoy
    r = requests.get(
        f"{BASE}/wods/hoy",
        params={"tenant_id": TENANT_ID, "alumno_id": SharedE2E.alumno_id}
    )
    assert r.status_code == 200, f"Consultar WOD hoy falló: {r.status_code} - {r.text[:200]}"
    wod_hoy = r.json()

    # El WOD puede devolver None si la clase no es hoy
    if wod_hoy is None:
        # Buscar en la clase reservada
        r = requests.get(f"{BASE}/reservas/por-clase/{SharedE2E.clase_id}",
                         params={"tenant_id": TENANT_ID})
        assert r.status_code == 200
        reservas = r.json()
        reserva_alumno = None
        for res in reservas:
            if res["alumno_id"] == SharedE2E.alumno_id:
                reserva_alumno = res
                break
        assert reserva_alumno is not None, "Reserva del alumno no encontrada"
        print(
            f"  ✅ Alumno tiene reserva confirmada (clase_id={SharedE2E.clase_id})")

        # Consultar WOD directamente
        r = requests.get(
            f"{BASE}/wods/{SharedE2E.wod_id}",
            params={"tenant_id": TENANT_ID}
        )
        assert r.status_code == 200
        wod_hoy = r.json()

    assert wod_hoy is not None, "No se encontró WOD"
    assert wod_hoy.get("id") == SharedE2E.wod_id, \
        f"WOD id no coincide: {wod_hoy.get('id')} != {SharedE2E.wod_id}"
    print(f"  ✅ WOD consultado exitosamente: '{wod_hoy.get('titulo', '')}'")

    # 7c. Verificar que se descontó 1 crédito (ya se verificó en paso 5)
    # Confirmar que creditos_disponibles < creditos_iniciales
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT creditos_disponibles FROM suscripciones 
            WHERE id = %s
        """, (SharedE2E.suscripcion_id,))
        row = cur.fetchone()
        creditos_despues = row[0] if row else 0
        assert creditos_despues < SharedE2E.creditos_iniciales, \
            f"Créditos no se descontaron: inicial={SharedE2E.creditos_iniciales}, actual={creditos_despues}"
        assert creditos_despues == creditos_antes, \
            f"Créditos no deberían haber cambiado entre pasos 5 y 7: antes={creditos_antes}, ahora={creditos_despues}"
        print(
            f"  ✅ Créditos verificados: {SharedE2E.creditos_iniciales} → {creditos_despues}")
    finally:
        cur.close()
        conn.close()


def test_e2e_08_alumno_registra_rm_y_consulta_evolucion():
    """[Paso 8] Alumno registra un RM y consulta su evolución."""
    assert SharedE2E.alumno_id is not None
    assert SharedE2E.movimiento_id is not None

    # 8a. Registrar un RM
    r = requests.post(f"{BASE}/historial-rm", json={
        "tenant_id": TENANT_ID,
        "alumno_id": SharedE2E.alumno_id,
        "movimiento_id": SharedE2E.movimiento_id,
        "peso_kg": 80.0,
        "tipo_rm": "peso",
        "fecha": str(date.today()),
        "notas": "RM E2E Test"
    })
    assert r.status_code == 201, \
        f"Registrar RM falló: {r.status_code} - {r.text[:200]}"
    rm_data = r.json()
    assert rm_data.get("id") is not None, "No se devolvió id de RM"
    SharedE2E.rm_id = rm_data["id"]
    assert rm_data.get("peso_kg") == 80.0, \
        f"peso_kg debe ser 80.0, obtenido: {rm_data.get('peso_kg')}"
    print(
        f"  ✅ RM registrado: id={SharedE2E.rm_id}, movimiento_id={SharedE2E.movimiento_id}, peso=80kg")

    # 8b. Registrar segundo RM (para ver evolución)
    r2 = requests.post(f"{BASE}/historial-rm", json={
        "tenant_id": TENANT_ID,
        "alumno_id": SharedE2E.alumno_id,
        "movimiento_id": SharedE2E.movimiento_id,
        "peso_kg": 85.0,
        "tipo_rm": "peso",
        "fecha": str(date.today() + timedelta(days=7)),
        "notas": "RM E2E Test v2"
    })
    assert r2.status_code == 201, \
        f"Registrar segundo RM falló: {r2.status_code} - {r2.text[:200]}"
    rm2_data = r2.json()
    print(f"  ✅ Segundo RM registrado: id={rm2_data['id']}, peso=85kg")

    # 8c. Consultar evolución del movimiento
    r = requests.get(
        f"{BASE}/historial-rm/alumnos/{SharedE2E.alumno_id}/movimiento/{SharedE2E.movimiento_id}",
        params={"tenant_id": TENANT_ID}
    )
    assert r.status_code == 200, \
        f"Consultar evolución falló: {r.status_code} - {r.text[:200]}"
    evolucion = r.json()
    assert isinstance(evolucion, list), "Evolución debe ser una lista"
    assert len(evolucion) >= 2, \
        f"Debe haber al menos 2 registros, obtenidos: {len(evolucion)}"

    # Verificar que los RMs aparecen reflejados
    pesos_encontrados = [r.get("peso_kg")
                         for r in evolucion if r.get("peso_kg")]
    assert 80.0 in pesos_encontrados, \
        f"RM de 80kg no aparece en evolución: {pesos_encontrados}"
    assert 85.0 in pesos_encontrados, \
        f"RM de 85kg no aparece en evolución: {pesos_encontrados}"
    print(f"  ✅ Evolución consultada: {len(evolucion)} registros, "
          f"pesos={pesos_encontrados}")

    # 8d. Consultar RMs del alumno
    r = requests.get(
        f"{BASE}/historial-rm/alumnos/{SharedE2E.alumno_id}/rms",
        params={"tenant_id": TENANT_ID}
    )
    assert r.status_code == 200, \
        f"Consultar RMs alumno falló: {r.status_code} - {r.text[:200]}"
    rms_alumno = r.json()
    assert isinstance(rms_alumno, list), "RMs debe ser una lista"
    # Buscar el movimiento específico
    rm_encontrado = None
    for rm in rms_alumno:
        if rm.get("movimiento_id") == SharedE2E.movimiento_id:
            rm_encontrado = rm
            break
    assert rm_encontrado is not None, \
        f"Movimiento {SharedE2E.movimiento_id} no aparece en RMs del alumno"
    assert rm_encontrado.get("peso_kg") == 85.0, \
        f"Mejor RM debe ser 85.0, obtenido: {rm_encontrado.get('peso_kg')}"
    print(
        f"  ✅ RMs del alumno OK: mejor {rm_encontrado['movimiento_nombre']} = {rm_encontrado['peso_kg']}kg")


def test_e2e_99_limpiar_datos():
    """[Limpieza] Elimina TODOS los datos de prueba creados en el E2E."""
    limpiar_alumno_e2e()
    print(f"  ✅ Datos E2E eliminados para alumno {E2E_ALUMNO_ID}")
