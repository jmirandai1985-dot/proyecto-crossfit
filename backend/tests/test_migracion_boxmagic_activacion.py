"""Endpoint admin `GET /api/v1/migracion-boxmagic/activacion` — AISLADO.

Cubre, SIN BD y SIN red (app mínima con el router REAL de `migracion_boxmagic.py` y una
`get_db` falsa — mismo patrón que `test_admin_referidos_usados.py`):

  * clasificación de las CINCO etapas del embudo y su orden de prioridad;
  * `activado_hoy` con ventana móvil de 24 h (y que "sin hitos" nunca sea True);
  * el resumen agregado (total / por_etapa / activados_hoy) cuadra con las filas;
  * el plan que se muestra es el de la suscripción MÁS RECIENTE;
  * un alumno normal (sin marca de migración) NO cae en `password_cambiada`;
  * 403 para un usuario que no es admin.

    cd backend && py -3.12 -m pytest tests/test_migracion_boxmagic_activacion.py -q --noconftest
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1 import migracion_boxmagic  # noqa: E402
from app.core.dependencies import (  # noqa: E402
    get_current_admin, get_current_user, get_db,
)
from app.models.plan import Plan  # noqa: E402
from app.models.suscripcion import Suscripcion  # noqa: E402
from app.models.usuario import Usuario  # noqa: E402

TENANT = 1
ADMIN_ID = 7
RUTA = "/api/v1/migracion-boxmagic/activacion"

AHORA = datetime.now(timezone.utc)
RECIEN = AHORA - timedelta(hours=1)      # dentro de la ventana de 24 h
HACE_DIAS = AHORA - timedelta(days=3)    # fuera de la ventana


class _FilaAlumno:
    """Lo mínimo que el endpoint lee de `usuarios` (una fila por alumno)."""

    def __init__(self, id_, nombre, correo, *, correo_migracion_enviado_en=None,
                 cambiar_password_al_login=False, acepta_tyc_en=None,
                 acepta_salud_en=None, tenant_id=TENANT):
        self.id = id_
        self.tenant_id = tenant_id
        self.nombre = nombre
        self.correo = correo
        self.correo_migracion_enviado_en = correo_migracion_enviado_en
        self.cambiar_password_al_login = cambiar_password_al_login
        self.acepta_tyc_en = acepta_tyc_en
        self.acepta_salud_en = acepta_salud_en


class _FilaSuscripcion:
    """La fila de `suscripciones` (cualquier estado: el endpoint no filtra por eso)."""

    def __init__(self, usuario_id, fecha_inicio=RECIEN, id_=1):
        self.id = id_
        self.usuario_id = usuario_id
        self.fecha_inicio = fecha_inicio


class _FilaPlan:
    def __init__(self, nombre="Mensual"):
        self.nombre = nombre


class _Consulta:
    def __init__(self, filas):
        self._filas = filas

    def filter(self, *criterios):
        return self

    def join(self, *args, **kwargs):
        return self

    def order_by(self, *args):
        return self

    def all(self):
        return self._filas


class _SesionFalsa:
    """Session mínima: `query(Usuario)` devuelve los alumnos y `query(Suscripcion,
    Plan)` las tuplas (suscripción, plan) YA ordenadas de la más reciente a la más
    vieja, que es el orden en que las entrega Postgres."""

    def __init__(self, alumnos=None, planes=None):
        self._alumnos = alumnos or []
        self._planes = planes or []

    def query(self, *modelos):
        primero = modelos[0] if modelos else None
        if primero is Usuario:
            return _Consulta(self._alumnos)
        if primero is Suscripcion:
            return _Consulta(self._planes)
        return _Consulta([])

    def add(self, obj):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


async def _admin_falso():
    return {
        "usuario_id": ADMIN_ID,
        "tenant_id": TENANT,
        "rol": "admin",
        "correo": "admin@test.com",
        "nombre": "Admin",
        "activo": True,
        "estado": "activo",
    }


def _usuario_no_admin(rol):
    """Identidad falsa con ese rol: `get_current_admin` la rebota con 403."""

    async def _dependencia():
        return {
            "usuario_id": 123,
            "tenant_id": TENANT,
            "rol": rol,
            "correo": "no-admin@test.com",
            "nombre": "No Admin",
            "activo": True,
            "estado": "activo",
        }

    return _dependencia


def _cliente_con(sesion, rol="admin"):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(migracion_boxmagic.router,
                       prefix="/api/v1/migracion-boxmagic")
    app.dependency_overrides[get_db] = lambda: sesion
    if rol == "admin":
        app.dependency_overrides[get_current_admin] = _admin_falso
    else:
        # `get_current_admin` NO se overridea: se ejercita el guard REAL (403).
        app.dependency_overrides[get_current_user] = _usuario_no_admin(rol)
    return TestClient(app)


def _por_id(body):
    return {alumno["id"]: alumno for alumno in body["alumnos"]}


def _embudo_completo():
    """Un alumno en CADA etapa (ids 1..5) + el plan del que compró.

    El de `sin_invitar` es un alumno normal: mismo `cambiar_password_al_login=False`
    que el de `password_cambiada`, pero SIN marca de migración.
    """
    alumnos = [
        _FilaAlumno(1, "Sin Invitar", "sin@test.com"),
        _FilaAlumno(2, "Correo Enviado", "correo@test.com",
                    correo_migracion_enviado_en=RECIEN,
                    cambiar_password_al_login=True),
        _FilaAlumno(3, "Password Cambiada", "pass@test.com",
                    correo_migracion_enviado_en=HACE_DIAS,
                    cambiar_password_al_login=False),
        _FilaAlumno(4, "Registro Completo", "registro@test.com",
                    correo_migracion_enviado_en=HACE_DIAS,
                    cambiar_password_al_login=False,
                    acepta_tyc_en=HACE_DIAS, acepta_salud_en=RECIEN),
        _FilaAlumno(5, "Plan Comprado", "plan@test.com",
                    correo_migracion_enviado_en=HACE_DIAS,
                    cambiar_password_al_login=False,
                    acepta_tyc_en=HACE_DIAS, acepta_salud_en=HACE_DIAS),
    ]
    planes = [(_FilaSuscripcion(usuario_id=5, fecha_inicio=RECIEN),
               _FilaPlan("Pase Libre"))]
    return _SesionFalsa(alumnos=alumnos, planes=planes)


# ── Clasificación de las 5 etapas ─────────────────────────────────────────────
def test_clasifica_las_cinco_etapas():
    cliente = _cliente_con(_embudo_completo())

    r = cliente.get(RUTA)

    assert r.status_code == 200, r.text
    alumnos = _por_id(r.json())
    assert len(alumnos) == 5
    assert alumnos[1]["etapa"] == "sin_invitar"
    assert alumnos[2]["etapa"] == "correo_enviado"
    assert alumnos[3]["etapa"] == "password_cambiada"
    assert alumnos[4]["etapa"] == "registro_completo"
    assert alumnos[5]["etapa"] == "plan_comprado"


def test_plan_comprado_trae_el_nombre_del_plan():
    cliente = _cliente_con(_embudo_completo())

    alumnos = _por_id(cliente.get(RUTA).json())

    assert alumnos[5]["plan_comprado"] == "Pase Libre"
    # El resto no compró: None explícito, no la cadena "None".
    assert alumnos[1]["plan_comprado"] is None
    assert alumnos[4]["plan_comprado"] is None


def test_cada_fila_trae_id_nombre_y_correo():
    cliente = _cliente_con(_embudo_completo())

    alumnos = _por_id(cliente.get(RUTA).json())

    assert alumnos[2]["nombre"] == "Correo Enviado"
    assert alumnos[2]["correo"] == "correo@test.com"


# ── Resumen agregado ─────────────────────────────────────────────────────────
def test_resumen_cuadra_con_las_filas():
    cliente = _cliente_con(_embudo_completo())

    r = cliente.get(RUTA)

    assert r.status_code == 200, r.text
    resumen = r.json()["resumen"]
    assert resumen["total"] == 5
    assert resumen["por_etapa"] == {
        "sin_invitar": 1,
        "correo_enviado": 1,
        "password_cambiada": 1,
        "registro_completo": 1,
        "plan_comprado": 1,
    }
    # 2 y 4 y 5 alcanzaron su hito hace <=24 h; 1 (sin hito) y 3 no.
    assert resumen["activados_hoy"] == 3


def test_resumen_trae_las_cinco_etapas_aunque_esten_en_cero():
    sesion = _SesionFalsa(alumnos=[_FilaAlumno(1, "Uno", "uno@test.com")])
    cliente = _cliente_con(sesion)

    resumen = cliente.get(RUTA).json()["resumen"]

    assert resumen["por_etapa"] == {etapa: (1 if etapa == "sin_invitar" else 0)
                                    for etapa in migracion_boxmagic.ETAPAS}
    assert resumen["total"] == 1
    assert resumen["activados_hoy"] == 0


def test_sin_alumnos_devuelve_embudo_vacio():
    cliente = _cliente_con(_SesionFalsa(alumnos=[], planes=[]))

    body = cliente.get(RUTA).json()

    assert body["alumnos"] == []
    assert body["resumen"]["total"] == 0
    assert body["resumen"]["activados_hoy"] == 0
    assert all(n == 0 for n in body["resumen"]["por_etapa"].values())



# ── Ventana de 24 h ─────────────────────────────────────────────────────────
def test_activado_hoy_solo_dentro_de_24h():
    alumnos = [
        _FilaAlumno(1, "Recién", "recien@test.com",
                    correo_migracion_enviado_en=RECIEN,
                    cambiar_password_al_login=True),
        _FilaAlumno(2, "Viejo", "viejo@test.com",
                    correo_migracion_enviado_en=HACE_DIAS,
                    cambiar_password_al_login=True),
        _FilaAlumno(3, "Sin Hito", "sinhito@test.com"),
    ]
    cliente = _cliente_con(_SesionFalsa(alumnos=alumnos))

    r = cliente.get(RUTA)

    por_id = _por_id(r.json())
    assert por_id[1]["activado_hoy"] is True
    assert por_id[2]["activado_hoy"] is False
    # sin_invitar no alcanzó ningún hito: nunca cuenta como activado hoy.
    assert por_id[3]["etapa"] == "sin_invitar"
    assert por_id[3]["activado_hoy"] is False
    assert r.json()["resumen"]["activados_hoy"] == 1


def test_registro_completo_usa_la_aceptacion_mas_reciente():
    """tyc viejo + salud reciente = sigue siendo un hito de hoy."""
    alumno = _FilaAlumno(1, "Consentimientos", "c@test.com",
                         acepta_tyc_en=HACE_DIAS, acepta_salud_en=RECIEN)
    cliente = _cliente_con(_SesionFalsa(alumnos=[alumno]))

    fila = _por_id(cliente.get(RUTA).json())[1]

    assert fila["etapa"] == "registro_completo"
    assert fila["activado_hoy"] is True


# ── Prioridad y señales de la migración ─────────────────────────────────────
def test_compra_gana_a_registro_completo():
    """Haber comprado es la etapa más avanzada aunque tenga todo lo demás."""
    alumno = _FilaAlumno(1, "Comprador", "compro@test.com",
                         correo_migracion_enviado_en=HACE_DIAS,
                         acepta_tyc_en=HACE_DIAS, acepta_salud_en=HACE_DIAS)
    planes = [(_FilaSuscripcion(usuario_id=1, fecha_inicio=HACE_DIAS),
               _FilaPlan("Mensual"))]
    cliente = _cliente_con(_SesionFalsa(alumnos=[alumno], planes=planes))

    fila = _por_id(cliente.get(RUTA).json())[1]

    assert fila["etapa"] == "plan_comprado"
    assert fila["plan_comprado"] == "Mensual"
    # La suscripción es de hace 3 días: compró, pero no hoy.
    assert fila["activado_hoy"] is False


def test_alumno_normal_no_cae_en_password_cambiada():
    """El flag en False lo tienen TODOS: sin marca de migración es sin_invitar.

    Es el guard del cambio de contraseña: `cambiar_password_al_login` viene en False
    en cualquier alumno creado por un admin o por el alta pública, así que usarlo solo
    pintaría de "password_cambiada" a medio box.
    """
    alumno = _FilaAlumno(1, "Normal", "normal@test.com",
                         cambiar_password_al_login=False,
                         correo_migracion_enviado_en=None)
    cliente = _cliente_con(_SesionFalsa(alumnos=[alumno]))

    assert _por_id(cliente.get(RUTA).json())[1]["etapa"] == "sin_invitar"


def test_muestra_el_plan_de_la_suscripcion_mas_reciente():
    """Vienen ordenadas desc: gana la primera (la última compra)."""
    alumno = _FilaAlumno(1, "Renovó", "renovo@test.com")
    planes = [
        (_FilaSuscripcion(usuario_id=1, fecha_inicio=RECIEN, id_=2),
         _FilaPlan("Anual")),
        (_FilaSuscripcion(usuario_id=1, fecha_inicio=HACE_DIAS, id_=1),
         _FilaPlan("Mensual")),
    ]
    cliente = _cliente_con(_SesionFalsa(alumnos=[alumno], planes=planes))

    fila = _por_id(cliente.get(RUTA).json())[1]

    assert fila["plan_comprado"] == "Anual"
    assert fila["activado_hoy"] is True


# ── Autorización ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("rol", ["alumno", "coach"])
def test_usuario_no_admin_recibe_403(rol):
    cliente = _cliente_con(_embudo_completo(), rol=rol)

    r = cliente.get(RUTA)

    assert r.status_code == 403, r.text
    assert "administrador" in r.json()["detail"].lower()

