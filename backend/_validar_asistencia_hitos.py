"""
Validación dirigida de las Fases 1 y 2: Sistema de Asistencia + Hitos (n8n).

Corre contra la BD de TEST (small-butterfly, ENVIRONMENT=test). Crea un tenant
aislado con prefijo TEST_ASISTENCIA, ejecuta los casos y limpia al final.

Casos cubiertos:
  1) Coach marca asistencia de una clase completa (1 click / batch confirmar)
  2) Coach destilda a 1 alumno -> se guarda correctamente
  3) Intento de corrección fuera de la ventana (día siguiente / otra fecha) -> 403
  4) Cálculo de % con escenarios 100%, parcial y sin reservas
  5) Racha: mes 100% sube; mes sin reservas se congela; mes <100% corta a 0
  6) Hito NO se duplica si se evalúa el mismo mes 2 veces
  7) Endpoint n8n rechaza sin la API key correcta (y funciona con la correcta)
  8) Backfill genera hitos retroactivos correctos SIN duplicar
"""
import os
import sys
import random
import datetime
from datetime import date, time as dtime

os.environ["ENVIRONMENT"] = "test"
os.environ["SENTRY_DSN"] = ""
# API key de n8n para el endpoint evaluar-mes (solo esta validación)
os.environ["N8N_API_KEY"] = "test-n8n-key-asistencia-2026"
# Evitar intentos SMTP reales: credenciales vacías -> login falla al instante
os.environ["GMAIL_SMTP_USER"] = ""
os.environ["GMAIL_SMTP_APP_PASSWORD"] = ""

# Bloqueo SMTP a nivel de librería: cualquier _enviar falla al instante y
# queda registrado como 'fallido' con mes_referencia (el dedupe funciona igual).
import smtplib  # noqa: E402


class _FakeSMTP:
    def __init__(self, *args, **kwargs):
        raise ConnectionError("SMTP bloqueado durante la validación")


smtplib.SMTP = _FakeSMTP

from sqlalchemy import text as sa_text  # noqa: E402

from app.main import app  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.db.database import engine, SessionLocal  # noqa: E402
from app.utils.santiago import hoy_santiago  # noqa: E402
from app.services import asistencia_service as svc  # noqa: E402

PREFIX = "TEST_ASISTENCIA"  # marcador inconfundible para limpieza
BASE = random.randint(6_000_000, 6_999_000)

TENANT = BASE          # tenant de pruebas (eval/batch/racha)
TENANT2 = BASE + 1     # tenant de backfill

DISC = BASE + 2
DISC2 = BASE + 3       # disciplina NO asignada al coach (filtro)
DISC_T2 = BASE + 4

COACH = BASE + 10
ADMIN = BASE + 11

AFULL = BASE + 20      # batch 1
AFULL2 = BASE + 21     # batch 2
ARACHA = BASE + 22     # 100% M1,M2,M3 -> racha 3
ACONGELA = BASE + 23   # 100% M2, sin reservas M1 -> congela en 1
ACORTA = BASE + 24     # 100% M2, parcial M1 -> corta a 0
AINACT = BASE + 25     # sin reservas nunca
ABACKFILL = BASE + 26  # (TENANT2) 100% M1..M6 -> hitos 1,3,6
ABACKFILL_CORTE = BASE + 27  # (TENANT2) 100% M4..M2, parcial M1 -> hitos 1,3
AOTRO = BASE + 28      # (TENANT2) alumno sin datos

HORARIO = BASE + 30    # TENANT/DISC
HORARIO2 = BASE + 31   # TENANT/DISC2
HORARIO_T2 = BASE + 32

# Clases de HOY (fecha = hoy Santiago)
CHOY_PASADA = BASE + 40   # hoy 00:00:00 (ya pasó)
CHOY_FUTURA = BASE + 41   # hoy 23:59:59 (futura, disciplinas del coach)
CHOY_DISC2 = BASE + 42    # hoy 23:59:59 pero disciplina NO asignada al coach

TID_LIST = (TENANT, TENANT2)
UID_LIST = (COACH, ADMIN, AFULL, AFULL2, ARACHA, ACONGELA, ACORTA, AINACT,
            ABACKFILL, ABACKFILL_CORTE, AOTRO)

# Contadores para clases/reservas de meses pasados
_CID = {"v": BASE + 100}
_RID = {"v": BASE + 1000}
CLASE_BY_NAME = {}
RESERVA_BY_NAME = {}


def _nid(counter):
    counter["v"] += 1
    return counter["v"]


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def now_utc_str():
    return fmt(datetime.datetime.now(datetime.timezone.utc))


def mes_atras(offset: int):
    """(anio, mes) con `offset` meses hacia atrás desde el mes actual (Santiago)."""
    hoy = hoy_santiago()
    anio, mes = hoy.year, hoy.month
    for _ in range(offset):
        if mes == 1:
            anio, mes = anio - 1, 12
        else:
            mes -= 1
    return anio, mes


M1 = mes_atras(1)
M2 = mes_atras(2)
M3 = mes_atras(3)
M4 = mes_atras(4)
M5 = mes_atras(5)
M6 = mes_atras(6)


def _fecha_mes(ym, dia):
    return date(ym[0], ym[1], dia)


def _agregar_clase(clases_rows, tenant, disc_id, coach_id, fecha, hi, hf):
    cid = _nid(_CID)
    clases_rows.append({
        "id": cid, "tenant_id": tenant, "horario_base_id": HORARIO,
        "coach_id": coach_id, "disciplina_id": disc_id,
        "fecha": fecha, "hora_inicio": hi, "hora_fin": hf,
        "cupo_maximo": 20, "asistentes_confirmados": 1, "cancelada": False,
    })
    return cid


def _agregar_reserva(reservas_rows, tenant, clase_id, alumno_id, asistio):
    rid = _nid(_RID)
    reservas_rows.append({
        "id": rid, "tenant_id": tenant, "clase_id": clase_id,
        "alumno_id": alumno_id, "asistio": asistio,
        "tokens_gastados": 1, "estado": "confirmada",
    })
    return rid


def _map_clase(r):
    """Traduce una fila de clase a los bind params del INSERT."""
    return {
        "id": r["id"], "tid": r["tenant_id"],
        "hb": HORARIO if r["tenant_id"] == TENANT else HORARIO_T2,
        "cid": r["coach_id"], "did": r["disciplina_id"],
        "fecha": r["fecha"], "hi": r["hora_inicio"], "hf": r["hora_fin"],
        "cupo": r["cupo_maximo"], "asist": r["asistentes_confirmados"],
        "ca": now_utc_str(), "ua": now_utc_str(),
    }


def _map_reserva(r):
    """Traduce una fila de reserva a los bind params del INSERT."""
    return {
        "id": r["id"], "tid": r["tenant_id"], "clase": r["clase_id"],
        "alumno": r["alumno_id"], "asistio": r["asistio"],
        "tokens": r["tokens_gastados"], "ca": now_utc_str(), "ua": now_utc_str(),
    }

def seed():
    """Crea los datos de prueba en UNA transacción (all-or-nothing)."""
    clases_rows = []
    reservas_rows = []

    # ── Clases de HOY (fecha de hoy en Chile) ──
    hoy = hoy_santiago()
    clases_rows.append({
        "id": CHOY_PASADA, "tenant_id": TENANT, "horario_base_id": HORARIO,
        "coach_id": COACH, "disciplina_id": DISC,
        "fecha": hoy, "hora_inicio": dtime(0, 0), "hora_fin": dtime(1, 0),
        "cupo_maximo": 20, "asistentes_confirmados": 0, "cancelada": False,
    })
    clases_rows.append({
        "id": CHOY_FUTURA, "tenant_id": TENANT, "horario_base_id": HORARIO,
        "coach_id": COACH, "disciplina_id": DISC,
        "fecha": hoy, "hora_inicio": dtime(23, 59, 59), "hora_fin": dtime(23, 59, 59),
        "cupo_maximo": 20, "asistentes_confirmados": 2, "cancelada": False,
    })
    clases_rows.append({
        "id": CHOY_DISC2, "tenant_id": TENANT, "horario_base_id": HORARIO2,
        "coach_id": COACH, "disciplina_id": DISC2,
        "fecha": hoy, "hora_inicio": dtime(23, 59, 59), "hora_fin": dtime(23, 59, 59),
        "cupo_maximo": 20, "asistentes_confirmados": 0, "cancelada": False,
    })

    # ── ARACHA: 100% en M1, M2 y M3 (2 clases por mes) ──
    for offset, name in ((1, "m1"), (2, "m2"), (3, "m3")):
        ym = mes_atras(offset)
        for dia, suf in ((5, "d5"), (17, "d17")):
            cid = _agregar_clase(clases_rows, TENANT, DISC, COACH,
                                 _fecha_mes(ym, dia), dtime(10, 0), dtime(11, 0))
            CLASE_BY_NAME[f"racha_{name}_{suf}"] = cid
            rid = _agregar_reserva(reservas_rows, TENANT, cid, ARACHA, True)
            RESERVA_BY_NAME[f"racha_{name}_{suf}"] = rid

    # ── ACONGELA: 100% en M2; M1 sin reservas ──
    for dia in (5, 17):
        cid = _agregar_clase(clases_rows, TENANT, DISC, COACH,
                             _fecha_mes(M2, dia), dtime(10, 0), dtime(11, 0))
        CLASE_BY_NAME[f"congela_m2_d{dia}"] = cid
        _agregar_reserva(reservas_rows, TENANT, cid, ACONGELA, True)

    # ── ACORTA: 100% en M2; parcial en M1 (1 de 2) ──
    for dia in (5, 17):
        cid = _agregar_clase(clases_rows, TENANT, DISC, COACH,
                             _fecha_mes(M2, dia), dtime(10, 0), dtime(11, 0))
        _agregar_reserva(reservas_rows, TENANT, cid, ACORTA, True)
    for dia, asistio in ((5, True), (17, False)):
        cid = _agregar_clase(clases_rows, TENANT, DISC, COACH,
                             _fecha_mes(M1, dia), dtime(10, 0), dtime(11, 0))
        CLASE_BY_NAME[f"corta_m1_d{dia}"] = cid
        _agregar_reserva(reservas_rows, TENANT, cid, ACORTA, asistio)

    # ── AFULL / AFULL2: reservan la clase FUTURA de hoy (para batch) ──
    _agregar_reserva(reservas_rows, TENANT, CHOY_FUTURA, AFULL, False)
    _agregar_reserva(reservas_rows, TENANT, CHOY_FUTURA, AFULL2, False)

    # ── TENANT2: ABACKFILL 100% M1..M6 (12 clases) ──
    for offset in range(1, 7):
        ym = mes_atras(offset)
        for dia in (5, 17):
            cid = _agregar_clase(clases_rows, TENANT2, DISC_T2, None,
                                 _fecha_mes(ym, dia), dtime(10, 0), dtime(11, 0))
            _agregar_reserva(reservas_rows, TENANT2, cid, ABACKFILL, True)

    # ── TENANT2: ABACKFILL_CORTE 100% M4..M2; parcial M1 ──
    for offset in (4, 3, 2):
        ym = mes_atras(offset)
        for dia in (5, 17):
            cid = _agregar_clase(clases_rows, TENANT2, DISC_T2, None,
                                 _fecha_mes(ym, dia), dtime(10, 0), dtime(11, 0))
            _agregar_reserva(reservas_rows, TENANT2, cid, ABACKFILL_CORTE, True)
    for dia, asistio in ((5, True), (17, False)):
        cid = _agregar_clase(clases_rows, TENANT2, DISC_T2, None,
                             _fecha_mes(M1, dia), dtime(10, 0), dtime(11, 0))
        _agregar_reserva(reservas_rows, TENANT2, cid, ABACKFILL_CORTE, asistio)


    with engine.begin() as conn:
        conn.execute(sa_text(
            "INSERT INTO tenants (id, nombre, subdomain, activo, created_at) "
            "VALUES (:id, :nom, :sub, TRUE, :ca)"),
            [{"id": TENANT, "nom": f"{PREFIX} Tenant A",
              "sub": f"test-asistencia-{BASE}", "ca": now_utc_str()},
             {"id": TENANT2, "nom": f"{PREFIX} Tenant B",
              "sub": f"test-asistencia-{BASE}b", "ca": now_utc_str()}])
        conn.execute(sa_text(
            "INSERT INTO usuarios (id, tenant_id, rut, nombre, correo, password_hash, rol, activo, estado) "
            "VALUES (:id, :tid, :rut, :nom, :mail, 'x', :rol, TRUE, 'activo')"),
            [
                {"id": COACH, "tid": TENANT, "rut": "TA000010", "nom": f"{PREFIX} Coach",
                 "mail": f"test_asistencia_coach_{BASE}@test.com", "rol": "coach"},
                {"id": ADMIN, "tid": TENANT, "rut": "TA000011", "nom": f"{PREFIX} Admin",
                 "mail": f"test_asistencia_admin_{BASE}@test.com", "rol": "administrador"},
                {"id": AFULL, "tid": TENANT, "rut": "TA000020", "nom": f"{PREFIX} Full1",
                 "mail": f"test_asistencia_full1_{BASE}@test.com", "rol": "alumno"},
                {"id": AFULL2, "tid": TENANT, "rut": "TA000021", "nom": f"{PREFIX} Full2",
                 "mail": f"test_asistencia_full2_{BASE}@test.com", "rol": "alumno"},
                {"id": ARACHA, "tid": TENANT, "rut": "TA000022", "nom": f"{PREFIX} Racha",
                 "mail": f"test_asistencia_racha_{BASE}@test.com", "rol": "alumno"},
                {"id": ACONGELA, "tid": TENANT, "rut": "TA000023", "nom": f"{PREFIX} Congela",
                 "mail": f"test_asistencia_congela_{BASE}@test.com", "rol": "alumno"},
                {"id": ACORTA, "tid": TENANT, "rut": "TA000024", "nom": f"{PREFIX} Corta",
                 "mail": f"test_asistencia_corta_{BASE}@test.com", "rol": "alumno"},
                {"id": AINACT, "tid": TENANT, "rut": "TA000025", "nom": f"{PREFIX} Inactivo",
                 "mail": f"test_asistencia_inactivo_{BASE}@test.com", "rol": "alumno"},
                {"id": ABACKFILL, "tid": TENANT2, "rut": "TA000026", "nom": f"{PREFIX} Backfill",
                 "mail": f"test_asistencia_backfill_{BASE}@test.com", "rol": "alumno"},
                {"id": ABACKFILL_CORTE, "tid": TENANT2, "rut": "TA000027",
                 "nom": f"{PREFIX} BackfillCorte",
                 "mail": f"test_asistencia_backfill_corte_{BASE}@test.com", "rol": "alumno"},
                {"id": AOTRO, "tid": TENANT2, "rut": "TA000028", "nom": f"{PREFIX} OtroBox",
                 "mail": f"test_asistencia_otro_{BASE}@test.com", "rol": "alumno"},
            ])
        conn.execute(sa_text(
            "INSERT INTO disciplinas (id, tenant_id, nombre, descripcion, es_open_box, requiere_coach, activo) "
            "VALUES (:id, :tid, :nom, NULL, FALSE, TRUE, TRUE)"),
            [{"id": DISC, "tid": TENANT, "nom": f"{PREFIX} CrossFit"},
             {"id": DISC2, "tid": TENANT, "nom": f"{PREFIX} Musculacion"},
             {"id": DISC_T2, "tid": TENANT2, "nom": f"{PREFIX} CrossFit T2"}])
        conn.execute(sa_text(
            "INSERT INTO coach_disciplinas (tenant_id, coach_id, disciplina_id, activo, created_at) "
            "VALUES (:tid, :cid, :did, TRUE, :ca)"),
            {"tid": TENANT, "cid": COACH, "did": DISC, "ca": now_utc_str()})
        conn.execute(sa_text(
            "INSERT INTO horarios (id, tenant_id, disciplina_id, dia_semana, hora_inicio, hora_fin, cupo_maximo, activo, created_at) "
            "VALUES (:id, :tid, :did, 0, '10:00:00', '11:00:00', 20, TRUE, :ca)"),
            [{"id": HORARIO, "tid": TENANT, "did": DISC, "ca": now_utc_str()},
             {"id": HORARIO2, "tid": TENANT, "did": DISC2, "ca": now_utc_str()},
             {"id": HORARIO_T2, "tid": TENANT2, "did": DISC_T2, "ca": now_utc_str()}])

        conn.execute(sa_text(
            "INSERT INTO clases (id, tenant_id, horario_base_id, coach_id, disciplina_id, fecha, hora_inicio, hora_fin, cupo_maximo, asistentes_confirmados, cancelada, created_at, updated_at) "
            "VALUES (:id, :tid, :hb, :cid, :did, :fecha, :hi, :hf, :cupo, :asist, FALSE, :ca, :ua)"),
            [_map_clase(r) for r in clases_rows])
        conn.execute(sa_text(
            "INSERT INTO reservas (id, tenant_id, clase_id, alumno_id, asistio, tokens_gastados, estado, created_at, updated_at) "
            "VALUES (:id, :tid, :clase, :alumno, :asistio, :tokens, 'confirmada', :ca, :ua)"),
            [_map_reserva(r) for r in reservas_rows])
    print(f"[seed] creados: {len(clases_rows)} clases, {len(reservas_rows)} reservas")


def cleanup():
    """Elimina TODOS los datos de prueba por PREFIJO (auto-sanea corridas
    interrumpidas cuyo BASE random no coincide con la corrida actual).

    Doble pasada para respetar FKs creadas en el camino. Los patrones son
    inconfundibles: subdomain 'test-asistencia-%' y correos 'test_asistencia_%'.
    """
    SUB = "test-asistencia-%"
    CORREO = "test_asistencia_%@test.com"
    PASOS = [
        ("reservas", "DELETE FROM reservas WHERE tenant_id IN (SELECT id FROM tenants WHERE subdomain LIKE :sub) "
                     "OR alumno_id IN (SELECT id FROM usuarios WHERE correo LIKE :correo)"),
        ("hitos_alumno", "DELETE FROM hitos_alumno WHERE tenant_id IN (SELECT id FROM tenants WHERE subdomain LIKE :sub)"),
        ("clases", "DELETE FROM clases WHERE tenant_id IN (SELECT id FROM tenants WHERE subdomain LIKE :sub)"),
        ("horarios", "DELETE FROM horarios WHERE tenant_id IN (SELECT id FROM tenants WHERE subdomain LIKE :sub)"),
        ("coach_disciplinas", "DELETE FROM coach_disciplinas WHERE tenant_id IN (SELECT id FROM tenants WHERE subdomain LIKE :sub)"),
        ("asistencias", "DELETE FROM asistencias WHERE tenant_id IN (SELECT id FROM tenants WHERE subdomain LIKE :sub) "
                        "OR usuario_id IN (SELECT id FROM usuarios WHERE correo LIKE :correo)"),
        ("notificaciones", "DELETE FROM notificaciones WHERE alumno_id IN (SELECT id FROM usuarios WHERE correo LIKE :correo)"),
        ("notificaciones_enviadas", "DELETE FROM notificaciones_enviadas WHERE alumno_id IN (SELECT id FROM usuarios WHERE correo LIKE :correo)"),
        ("suscripciones", "DELETE FROM suscripciones WHERE tenant_id IN (SELECT id FROM tenants WHERE subdomain LIKE :sub)"),
        ("solicitudes_planes", "DELETE FROM solicitudes_planes WHERE tenant_id IN (SELECT id FROM tenants WHERE subdomain LIKE :sub)"),
        ("transacciones_financieras", "DELETE FROM transacciones_financieras WHERE tenant_id IN (SELECT id FROM tenants WHERE subdomain LIKE :sub)"),
        ("auditoria", "DELETE FROM auditoria WHERE tenant_id IN (SELECT id FROM tenants WHERE subdomain LIKE :sub)"),
        ("cobertura_emergencia", "DELETE FROM cobertura_emergencia WHERE tenant_id IN (SELECT id FROM tenants WHERE subdomain LIKE :sub)"),
        ("historial_rm", "DELETE FROM historial_rm WHERE tenant_id IN (SELECT id FROM tenants WHERE subdomain LIKE :sub)"),
        ("pedidos", "DELETE FROM pedidos WHERE tenant_id IN (SELECT id FROM tenants WHERE subdomain LIKE :sub)"),
        ("movimientos", "DELETE FROM movimientos WHERE tenant_id IN (SELECT id FROM tenants WHERE subdomain LIKE :sub)"),
        ("planes", "DELETE FROM planes WHERE tenant_id IN (SELECT id FROM tenants WHERE subdomain LIKE :sub)"),
        ("disciplinas", "DELETE FROM disciplinas WHERE tenant_id IN (SELECT id FROM tenants WHERE subdomain LIKE :sub)"),
        ("usuarios", "DELETE FROM usuarios WHERE id IN (SELECT id FROM usuarios WHERE correo LIKE :correo)"),
        ("tenants", "DELETE FROM tenants WHERE subdomain LIKE :sub"),
    ]
    params = {"sub": SUB, "correo": CORREO}

    def _tablas():
        with engine.connect() as conn:
            rows = conn.execute(sa_text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public'")).fetchall()
            return {r[0] for r in rows}

    def _pasada(tablas):
        with engine.begin() as conn:
            for tabla, sql in PASOS:
                if tabla in tablas:
                    conn.execute(sa_text(sql), params)

    try:
        tablas = _tablas()
        _pasada(tablas)
        _pasada(tablas)
        print("[cleanup] OK - datos de prueba eliminados (por prefijo)")
    except Exception as e:
        print(f"[cleanup] FALLO (limpiar manualmente con prefijo {PREFIX}): {str(e)[:300]}")


def token(user_id, tenant_id, rol):
    return create_access_token({
        "usuario_id": user_id, "tenant_id": tenant_id, "rol": rol,
        "correo": f"u{user_id}@t.cl", "nombre": f"u{user_id}",
    })


RESULTS = []


def record(caso, esperado, obtenido, ok, detalle=""):
    RESULTS.append(ok)
    estado = "PASS" if ok else "FAIL"
    print(f"[{estado}] {caso}\n      esperado={esperado} obtenido={obtenido} {detalle}")


from httpx import ASGITransport, AsyncClient  # noqa: E402

API_KEY = "test-n8n-key-asistencia-2026"


def q1(sql, **kw):
    with engine.connect() as conn:
        return conn.execute(sa_text(sql), kw).scalar()


def qall(sql, **kw):
    with engine.connect() as conn:
        return conn.execute(sa_text(sql), kw).fetchall()


async def run_tests():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        hCoach = {"Authorization": f"Bearer {token(COACH, TENANT, 'coach')}"}
        hAdmin = {"Authorization": f"Bearer {token(ADMIN, TENANT, 'administrador')}"}
        hA = {"Authorization": f"Bearer {token(ARACHA, TENANT, 'alumno')}"}
        hAOtro = {"Authorization": f"Bearer {token(AOTRO, TENANT2, 'alumno')}"}
        hFull = {"Authorization": f"Bearer {token(AFULL, TENANT, 'alumno')}"}

        rid_f1 = q1("SELECT id FROM reservas WHERE clase_id=:cl AND alumno_id=:a",
                    cl=CHOY_FUTURA, a=AFULL)
        rid_f2 = q1("SELECT id FROM reservas WHERE clase_id=:cl AND alumno_id=:a",
                    cl=CHOY_FUTURA, a=AFULL2)

        # 1) GET /clases-hoy (coach): solo disciplinas asignadas y desde ahora
        r = await c.get("/api/v1/asistencia/clases-hoy", headers=hCoach)
        data = r.json() if r.status_code == 200 else []
        ids = [x["id"] for x in data]
        ok = (r.status_code == 200 and CHOY_FUTURA in ids
              and CHOY_PASADA not in ids and CHOY_DISC2 not in ids)
        record("1. GET /clases-hoy (coach): filtro disciplina + hora >= ahora",
               f"contiene {CHOY_FUTURA}, NO {CHOY_PASADA}/{CHOY_DISC2}",
               f"{r.status_code} ids={ids}", ok)

        # 2) GET /clases-hoy (admin): todas las disciplinas del día
        r = await c.get("/api/v1/asistencia/clases-hoy", headers=hAdmin)
        data = r.json() if r.status_code == 200 else []
        ids = [x["id"] for x in data]
        ok = (r.status_code == 200 and CHOY_FUTURA in ids and CHOY_DISC2 in ids
              and CHOY_PASADA not in ids)
        record("2. GET /clases-hoy (admin): ve todas las disciplinas",
               f"contiene {CHOY_FUTURA} y {CHOY_DISC2}",
               f"{r.status_code} ids={ids}", ok)

        # 3) GET /clases/{id}/alumnos con token de ALUMNO -> 403
        r = await c.get(f"/api/v1/asistencia/clases/{CHOY_FUTURA}/alumnos", headers=hFull)
        record("3. GET alumnos de clase (token alumno) -> 403",
               403, r.status_code, r.status_code == 403)

        # 4) GET /clases/{id}/alumnos (coach): 2 reservas, no marcada
        r = await c.get(f"/api/v1/asistencia/clases/{CHOY_FUTURA}/alumnos", headers=hCoach)
        data = r.json() if r.status_code == 200 else {}
        res = data.get("reservas") or []
        ok = (r.status_code == 200 and len(res) == 2
              and data.get("marcada") is False)
        record("4. GET alumnos de clase (coach): 2 reservas, marcada=False",
               "200 + 2 reservas",
               f"{r.status_code} n={len(res)} marcada={data.get('marcada')}",
               ok)

        # 5) POST /clases/{id}/confirmar BATCH: todos asistieron (1 click)
        payload = {"asistencias": [
            {"reserva_id": rid_f1, "asistio": True},
            {"reserva_id": rid_f2, "asistio": True},
        ]}
        r = await c.post(f"/api/v1/asistencia/clases/{CHOY_FUTURA}/confirmar",
                         json=payload, headers=hCoach)
        ok = r.status_code == 200 and r.json().get("confirmados") == 2
        record("5. POST confirmar BATCH (todos asistieron)", "200 confirmados=2",
               f"{r.status_code} {r.text[:80]}", ok)


        # 6) Batch -> columnas de auditoría (por/at/via='batch')
        n = q1("SELECT COUNT(*) FROM reservas WHERE id IN (:a,:b) AND asistio=TRUE "
               "AND asistencia_marcada_por=:m AND asistencia_via='batch' "
               "AND asistencia_marcada_at IS NOT NULL",
               a=rid_f1, b=rid_f2, m=COACH)
        record("6. Batch -> columnas de auditoría (por/at/via='batch')",
               2, n, n == 2)

        # 7) POST confirmar de nuevo destildando a 1 alumno
        payload = {"asistencias": [
            {"reserva_id": rid_f1, "asistio": True},
            {"reserva_id": rid_f2, "asistio": False},
        ]}
        r = await c.post(f"/api/v1/asistencia/clases/{CHOY_FUTURA}/confirmar",
                         json=payload, headers=hCoach)
        v1 = q1("SELECT asistio FROM reservas WHERE id=:i", i=rid_f1)
        v2 = q1("SELECT asistio FROM reservas WHERE id=:i", i=rid_f2)
        ok = r.status_code == 200 and v1 is True and v2 is False
        record("7. Batch con destildado: se guarda correctamente",
               "200 + asis(True/False)", f"{r.status_code} v1={v1} v2={v2}", ok)

        # 8) Confirmar clase de OTRO día -> 403 (ventana backend)
        cid_pas = CLASE_BY_NAME["racha_m1_d5"]
        rid_pas = RESERVA_BY_NAME["racha_m1_d5"]
        r = await c.post(f"/api/v1/asistencia/clases/{cid_pas}/confirmar",
                         json={"asistencias": [{"reserva_id": rid_pas, "asistio": True}]},
                         headers=hCoach)
        record("8. Confirmar clase de día anterior -> 403 (ventana)",
               403, r.status_code, r.status_code == 403)

        # 9) PUT /reservas/{id}/asistencia de día anterior (coach) -> 403
        r = await c.put(f"/api/v1/reservas/{rid_pas}/asistencia",
                        json={"asistio": True}, headers=hCoach)
        record("9. PUT asistencia día anterior (coach) -> 403",
               403, r.status_code, r.status_code == 403)

        # 10) Admin bypass de la ventana -> 200
        r = await c.put(f"/api/v1/reservas/{rid_pas}/asistencia",
                        json={"asistio": True}, headers=hAdmin)
        record("10. PUT asistencia día anterior (admin bypass) -> 200",
               200, r.status_code, r.status_code == 200)

        # 11) PUT asistencia MISMO día (coach) -> 200 + via='coach'
        r = await c.put(f"/api/v1/reservas/{rid_f1}/asistencia",
                        json={"asistio": True}, headers=hCoach)
        via = q1("SELECT asistencia_via FROM reservas WHERE id=:i", i=rid_f1)
        ok = r.status_code == 200 and via == "coach"
        record("11. PUT asistencia mismo día (coach) -> 200 + via='coach'",
               "200 + via=coach", f"{r.status_code} via={via}", ok)


        # ── Escenarios de % de asistencia (mes cerrado M1) ──
        db = SessionLocal()
        calc = svc.calcular_asistencia_mes(db, ARACHA, TENANT, *M1)
        ok = (calc["estado"] == "completo" and calc["pct"] == 100
              and calc["total_reservadas"] == 2 and calc["asistidas"] == 2)
        record("12. % ARACHA M1: 100% sobre reservado",
               "completo 100% (2/2)",
               f"{calc['estado']} {calc['pct']}% {calc['asistidas']}/{calc['total_reservadas']}",
               ok)

        calc = svc.calcular_asistencia_mes(db, ACORTA, TENANT, *M1)
        ok = calc["estado"] == "parcial" and calc["pct"] == 50
        record("13. % ACORTA M1: parcial 50%",
               "parcial 50% (1/2)",
               f"{calc['estado']} {calc['pct']}% {calc['asistidas']}/{calc['total_reservadas']}",
               ok)

        calc = svc.calcular_asistencia_mes(db, AINACT, TENANT, *M1)
        record("14. % AINACT M1: sin reservas -> sin_actividad",
               "sin_actividad", f"{calc['estado']} pct={calc['pct']}",
               calc["estado"] == "sin_actividad")

        # ── Escenarios de racha ──
        racha = svc.calcular_racha(db, ARACHA, TENANT, *M1)
        record("15. Racha ARACHA M1 (100% M1,M2,M3) -> sube a 3",
               3, racha, racha == 3)

        racha = svc.calcular_racha(db, ACONGELA, TENANT, *M1)
        record("16. Racha ACONGELA M1 (sin reservas M1, 100% M2) -> CONGELA en 1",
               1, racha, racha == 1)

        racha = svc.calcular_racha(db, ACORTA, TENANT, *M1)
        record("17. Racha ACORTA M1 (parcial M1) -> CORTA a 0",
               0, racha, racha == 0)
        db.close()

        # ── Vistas del alumno ──
        r = await c.get("/api/v1/asistencia/mi-resumen", headers=hA)
        data = r.json() if r.status_code == 200 else {}
        ok = (r.status_code == 200 and data.get("racha_actual") == 3
              and data.get("proximo_hito") == 6)
        record("18. GET /mi-resumen ARACHA (racha=3, próximo hito=6)",
               "200 racha=3 prox=6",
               f"{r.status_code} racha={data.get('racha_actual')} prox={data.get('proximo_hito')}",
               ok)

        r = await c.get("/api/v1/asistencia/mis-hitos", headers=hA)
        data = r.json() if r.status_code == 200 else {}
        n_hitos = len(data.get("hitos") or [])
        record("19. GET /mis-hitos ARACHA (antes de evaluar) -> 0",
               "0 hitos", f"{r.status_code} n={n_hitos}",
               r.status_code == 200 and n_hitos == 0)

        r = await c.get("/api/v1/asistencia/mi-resumen", headers=hAOtro)
        data = r.json() if r.status_code == 200 else {}
        record("20. GET /mi-resumen AOTRO (tenant2, sin datos) -> racha 0",
               "racha=0", f"{r.status_code} racha={data.get('racha_actual')}",
               r.status_code == 200 and data.get("racha_actual") == 0)

        # ── n8n: autenticación ──
        r = await c.post("/api/v1/asistencia/n8n/evaluar-mes",
                         params={"tenant_id": TENANT, "anio": M1[0], "mes": M1[1]})
        record("21. n8n evaluar-mes SIN API key -> 401",
               401, r.status_code, r.status_code == 401)

        r = await c.post("/api/v1/asistencia/n8n/evaluar-mes",
                         params={"tenant_id": TENANT, "anio": M1[0], "mes": M1[1]},
                         headers={"X-N8N-API-Key": "clave-incorrecta"})
        record("22. n8n evaluar-mes API key INCORRECTA -> 401",
               401, r.status_code, r.status_code == 401)

        r = await c.post("/api/v1/asistencia/n8n/evaluar-mes",
                         params={"anio": M1[0]},
                         headers={"X-N8N-API-Key": API_KEY})
        data = r.json() if r.status_code == 200 else {}
        record("23. n8n evaluar-mes con anio pero sin mes -> 400",
               400, r.status_code, r.status_code == 400)


        # ── n8n: evaluación del mes M1 con API key correcta ──
        r = await c.post("/api/v1/asistencia/n8n/evaluar-mes",
                         params={"tenant_id": TENANT, "anio": M1[0], "mes": M1[1]},
                         headers={"X-N8N-API-Key": API_KEY})
        data = r.json() if r.status_code == 200 else {}
        ten = (data.get("tenants") or [{}])[0]
        ok = (r.status_code == 200
              and ten.get("cumplimiento") == 1   # ARACHA (100%)
              and ten.get("acompanamiento") == 1  # ACORTA (parcial)
              and ten.get("hitos_generados") == 1)  # ARACHA nivel 3
        record("24. n8n eval M1 (tenant): 1 cumplimiento + 1 acompañamiento + 1 hito",
               "200 cum=1 ac=1 hitos=1",
               f"{r.status_code} cum={ten.get('cumplimiento')} ac={ten.get('acompanamiento')} "
               f"hitos={ten.get('hitos_generados')}",
               ok)

        n = q1("SELECT COUNT(*) FROM hitos_alumno WHERE alumno_id=:a AND nivel=3 "
               "AND notificado=TRUE AND tenant_id=:t", a=ARACHA, t=TENANT)
        record("25. Hito ARACHA nivel 3 creado y notificado",
               1, n, n == 1)

        n = q1("SELECT COUNT(*) FROM notificaciones_enviadas WHERE alumno_id=:a "
               "AND tipo='cumplimiento' AND mes_referencia=:mr",
               a=ARACHA, mr=date(M1[0], M1[1], 1))
        record("26. Correo de cumplimiento ARACHA registrado (mes_referencia M1)",
               1, n, n == 1)

        n = q1("SELECT COUNT(*) FROM notificaciones_enviadas WHERE alumno_id=:a "
               "AND tipo='acompanamiento' AND mes_referencia=:mr",
               a=ACORTA, mr=date(M1[0], M1[1], 1))
        record("27. Correo de acompañamiento ACORTA registrado (mes_referencia M1)",
               1, n, n == 1)

        # ── Idempotencia: segunda llamada al mismo mes ──
        r = await c.post("/api/v1/asistencia/n8n/evaluar-mes",
                         params={"tenant_id": TENANT, "anio": M1[0], "mes": M1[1]},
                         headers={"X-N8N-API-Key": API_KEY})
        data = r.json() if r.status_code == 200 else {}
        ten = (data.get("tenants") or [{}])[0]
        ok = (r.status_code == 200 and ten.get("cumplimiento") == 0
              and ten.get("acompanamiento") == 0 and ten.get("hitos_generados") == 0)
        record("28. n8n misma llamada 2da vez: NO duplica (cum=0 ac=0 hitos=0)",
               "200 + 0/0/0",
               f"{r.status_code} cum={ten.get('cumplimiento')} ac={ten.get('acompanamiento')} "
               f"hitos={ten.get('hitos_generados')}",
               ok)

        n = q1("SELECT COUNT(*) FROM hitos_alumno WHERE alumno_id=:a AND tenant_id=:t",
               a=ARACHA, t=TENANT)
        record("29. Hitos ARACHA totales (sigue en 1, sin duplicado)",
               1, n, n == 1)

        n = q1("SELECT COUNT(*) FROM notificaciones_enviadas WHERE alumno_id=:a "
               "AND tipo='cumplimiento' AND mes_referencia=:mr",
               a=ARACHA, mr=date(M1[0], M1[1], 1))
        record("30. Correo cumplimiento M1 (1 sola fila, sin re-envío)",
               1, n, n == 1)

        # ── Vistas del alumno tras la evaluación ──
        r = await c.get("/api/v1/asistencia/mis-hitos", headers=hA)
        data = r.json() if r.status_code == 200 else {}
        niveles = sorted(h["nivel"] for h in (data.get("hitos") or []))
        record("31. GET /mis-hitos ARACHA (post eval) -> [3]",
               "niveles=[3]", f"{r.status_code} niveles={niveles}",
               r.status_code == 200 and niveles == [3])

        r = await c.get("/api/v1/asistencia/mi-resumen", headers=hA)
        data = r.json() if r.status_code == 200 else {}
        alcanzados = sorted(h["nivel"] for h in (data.get("hitos_alcanzados") or []))
        ok = (r.status_code == 200 and data.get("racha_actual") == 3
              and data.get("proximo_hito") == 6 and alcanzados == [3])
        record("32. GET /mi-resumen ARACHA (racha=3, prox=6, hitos=[3])",
               "200 + 3/6/[3]",
               f"{r.status_code} racha={data.get('racha_actual')} "
               f"prox={data.get('proximo_hito')} hitos={alcanzados}",
               ok)


        # ── Backfill retroactivo (TENANT2) ──
        db = SessionLocal()
        bf1 = svc.backfill_hitos(db, tenant_id=TENANT2)
        db.close()
        n = q1("SELECT COUNT(*) FROM hitos_alumno WHERE tenant_id=:t", t=TENANT2)
        ok = bf1["hitos_creados"] == 5 and n == 5
        record("33. Backfill TENANT2: 5 hitos creados (1,3,6 + 1,3)",
               "creados=5", f"creados={bf1['hitos_creados']} total={n}", ok)

        niv = sorted(x[0] for x in qall(
            "SELECT nivel FROM hitos_alumno WHERE alumno_id=:a", a=ABACKFILL))
        record("34. Backfill ABACKFILL niveles (racha 6) -> [1,3,6]",
               "[1,3,6]", str(niv), niv == [1, 3, 6])

        niv = sorted(x[0] for x in qall(
            "SELECT nivel FROM hitos_alumno WHERE alumno_id=:a", a=ABACKFILL_CORTE))
        record("35. Backfill ABACKFILL_CORTE (corte en M1) -> [1,3]",
               "[1,3]", str(niv), niv == [1, 3])

        n = q1("SELECT COUNT(*) FROM hitos_alumno WHERE tenant_id=:t AND notificado=FALSE",
               t=TENANT2)
        record("36. Backfill: todos los hitos retroactivos con notificado=True",
               0, n, n == 0)

        db = SessionLocal()
        bf2 = svc.backfill_hitos(db, tenant_id=TENANT2)
        db.close()
        n = q1("SELECT COUNT(*) FROM hitos_alumno WHERE tenant_id=:t", t=TENANT2)
        ok = bf2["hitos_creados"] == 0 and n == 5
        record("37. Backfill 2da vez: idempotente (0 nuevos, total 5)",
               "creados=0 total=5",
               f"creados={bf2['hitos_creados']} total={n}", ok)

        # ── Cross-tenant: coach del TENANT no ve clases de TENANT2 ──
        cid_t2 = q1("SELECT id FROM clases WHERE tenant_id=:t LIMIT 1", t=TENANT2)
        r = await c.get(f"/api/v1/asistencia/clases/{cid_t2}/alumnos", headers=hCoach)
        record("38. Cross-tenant: coach TENANT sobre clase TENANT2 -> 404",
               404, r.status_code, r.status_code == 404)

        # ── n8n: todos los tenants (sin tenant_id), mes M1 ya evaluado ──
        r = await c.post("/api/v1/asistencia/n8n/evaluar-mes",
                         headers={"X-N8N-API-Key": API_KEY})
        data = r.json() if r.status_code == 200 else {}
        ok = (r.status_code == 200 and data.get("tenants_evaluados") >= 2
              and data.get("hitos_generados_total") == 0)
        record("39. n8n todos los tenants: 200, sin hitos nuevos (dedupe)",
               "200 tenants>=2 hitos=0",
               f"{r.status_code} tenants={data.get('tenants_evaluados')} "
               f"hitos={data.get('hitos_generados_total')}",
               ok)


def main():
    import asyncio
    print("=" * 72)
    print("VALIDACIÓN Fases 1 y 2 — Asistencia + Hitos (n8n)")
    print("Marcador:", PREFIX, "| base:", BASE, "| BD:", "TEST (small-butterfly)")
    print("=" * 72)
    print("[setup] Limpieza previa de posibles leftovers...")
    cleanup()
    print("[setup] Creando datos de prueba (1 transacción, all-or-nothing)...")
    seed()
    try:
        asyncio.run(run_tests())
    except SystemExit:
        raise
    except Exception as e:
        import traceback
        print("[run] ERROR durante la ejecución:", str(e)[:500])
        traceback.print_exc()
    finally:
        print("[teardown] Limpieza final...")
        cleanup()
    total = len(RESULTS)
    passed = sum(1 for x in RESULTS if x)
    print(f"\nRESULTADO (Postgres test): {passed}/{total} PASS")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()

