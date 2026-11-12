"""Panel de RECUPERACIÓN de inactivos (`/api/v1/migracion-boxmagic/recuperacion*`) — AISLADO.

Cubre, SIN BD y SIN red (app mínima con el router REAL de `migracion_boxmagic.py`, una
`get_db` falsa y la última asistencia inyectada — mismo patrón que
`test_migracion_boxmagic_activacion.py`):

  * GET: los CUATRO estados (`sin_contactar`, `promocion_enviada`, `vencida`,
    `recuperado`), la oferta MÁS RECIENTE y el resumen agregado.
  * GET: el criterio de "alumno inactivo" (7+ días sin asistir, con historial REAL:
    quien nunca entrenó no entra, igual que en `fidelizacion.py`).
  * POST: crea la fila, manda el correo (MOCKEADO, no sale nada) y responde
    `correo_enviado` true/false, incluido el caso en que el envío revienta: la oferta
    se guarda igual (best-effort).
  * PUT: marca recuperado y responde 404 cuando no hay promoción vigente.
  * 403 para un usuario que no es admin en los TRES endpoints.

    cd backend && py -3.12 -m pytest tests/test_migracion_boxmagic_recuperacion.py -q --noconftest
"""
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.api.v1 import migracion_boxmagic  # noqa: E402
from app.core.dependencies import (  # noqa: E402
    get_current_admin, get_current_user, get_db,
)
from app.models.promocion_recuperacion import PromocionRecuperacion  # noqa: E402
from app.models.usuario import Usuario  # noqa: E402
from app.services import email_service  # noqa: E402
from app.utils.santiago import fecha_chile  # noqa: E402

TENANT = 1
ADMIN_ID = 7
ALUMNO_ID = 123
RUTA = "/api/v1/migracion-boxmagic/recuperacion"

HOY = date(2026, 12, 11)                 # "hoy" de Chile, fijado para el test
AHORA = datetime.now(timezone.utc)
EN_10_DIAS = AHORA + timedelta(days=10)
AYER = datetime.now(timezone.utc) - timedelta(days=3)


class _FilaAlumno:
    """Lo mínimo que el endpoint lee de `usuarios`."""

    def __init__(self, id_, nombre="Alumno", correo="alumno@test.com", telefono=None,
                 estado="activo", tenant_id=TENANT):
        self.id = id_
        self.tenant_id = tenant_id
        self.nombre = nombre
        self.correo = correo
        self.telefono = telefono
        self.estado = estado
        self.rol = "alumno"


class _FilaPromo:
    """Una fila de `promociones_recuperacion` (atributos, sin ORM)."""

    def __init__(self, id_, usuario_id=ALUMNO_ID, estado="enviada",
                 vence_en=EN_10_DIAS, tipo_beneficio="dias_gratis", cantidad=5,
                 notificacion_id=None, creado_en=AYER):
        self.id = id_
        self.usuario_id = usuario_id
        self.estado = estado
        self.vence_en = vence_en
        self.tipo_beneficio = tipo_beneficio
        self.cantidad = cantidad
        self.notificacion_id = notificacion_id
        self.creado_en = creado_en


class _Consulta:
    def __init__(self, filas):
        self._filas = list(filas)

    def filter(self, *criterios):
        return self

    def order_by(self, *args):
        return self

    def all(self):
        return self._filas

    def first(self):
        return self._filas[0] if self._filas else None


class _SesionFalsa:
    """Session mínima: `query(Usuario)` devuelve alumnos y `query(PromocionRecuperacion)`
    las ofertas tal como se configuraron; `add` les asigna id como haría Postgres."""

    def __init__(self, alumnos=None, promociones=None):
        self._alumnos = alumnos or []
        self._promociones = promociones or []
        self.agregados = []
        self.commits = 0
        self._siguiente_id = 100

    def query(self, *modelos):
        primero = modelos[0] if modelos else None
        if primero is Usuario:
            return _Consulta(self._alumnos)
        if primero is PromocionRecuperacion:
            return _Consulta(self._promociones)
        return _Consulta([])

    def add(self, obj):
        self._siguiente_id += 1
        obj.id = self._siguiente_id
        self.agregados.append(obj)
        self._promociones.append(obj)

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
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


def _parchear(monkeypatch, ultimas: dict):
    """Fija el "hoy" de Chile y la última asistencia REAL de cada alumno.

    `ultimas` = {usuario_id: date} — un id AUSENTE del dict nunca asistió (el
    "sin historial" que NO es un inactivo).
    """
    monkeypatch.setattr(migracion_boxmagic, "hoy_santiago", lambda: HOY)
    monkeypatch.setattr(
        migracion_boxmagic, "ultima_asistencia_por_alumno",
        lambda db, tenant_id, ids: {i: ultimas[i] for i in ids if i in ultimas})


def _mock_envio(monkeypatch, resultado=(True, 555), revienta=False):
    """Reemplaza el envío REAL por uno mudo (no toca SMTP ni la BD) y devuelve la lista
    de llamadas, para poder verificar con qué se llamó."""
    llamadas = []

    def _falso(alumno, tipo_beneficio, cantidad, vence_en):
        llamadas.append((alumno, tipo_beneficio, cantidad, vence_en))
        if revienta:
            raise RuntimeError("SMTP caído (test)")
        return resultado

    monkeypatch.setattr(email_service, "enviar_email_promocion_recuperacion", _falso)
    return llamadas


def _por_id(body):
    return {alumno["id"]: alumno for alumno in body["alumnos"]}



def _escenario_cuatro_estados(ultima=HOY - timedelta(days=20)):
    """Un alumno inactivo por CADA estado del panel (ids 1..4)."""
    alumnos = [
        _FilaAlumno(1, "Sin Contactar", "sin@test.com"),
        _FilaAlumno(2, "Con Oferta Viva", "viva@test.com"),
        _FilaAlumno(3, "Oferta Vencida", "vencida@test.com"),
        _FilaAlumno(4, "Ya Volvió", "volvio@test.com"),
    ]
    promociones = [
        _FilaPromo(11, usuario_id=2, estado="enviada", vence_en=EN_10_DIAS),
        _FilaPromo(12, usuario_id=3, estado="enviada",
                   vence_en=AHORA - timedelta(days=2)),
        _FilaPromo(13, usuario_id=4, estado="recuperado", vence_en=EN_10_DIAS),
    ]
    return (_SesionFalsa(alumnos=alumnos, promociones=promociones),
            {1: ultima, 2: ultima, 3: ultima, 4: ultima})


# ── GET: los cuatro estados ─────────────────────────────────────────────────
def test_get_clasifica_los_cuatro_estados(monkeypatch):
    sesion, ultimas = _escenario_cuatro_estados()
    _parchear(monkeypatch, ultimas)
    cliente = _cliente_con(sesion)

    r = cliente.get(RUTA)

    assert r.status_code == 200, r.text
    alumnos = _por_id(r.json())
    assert alumnos[1]["estado"] == "sin_contactar"
    assert alumnos[1]["promocion"] is None
    assert alumnos[2]["estado"] == "promocion_enviada"
    assert alumnos[2]["promocion"]["id"] == 11
    assert alumnos[3]["estado"] == "vencida"
    assert alumnos[3]["promocion"]["id"] == 12
    assert alumnos[4]["estado"] == "recuperado"
    assert alumnos[4]["promocion"]["id"] == 13


def test_get_resumen_cuadra_con_las_filas(monkeypatch):
    sesion, ultimas = _escenario_cuatro_estados()
    _parchear(monkeypatch, ultimas)
    cliente = _cliente_con(sesion)

    resumen = cliente.get(RUTA).json()["resumen"]

    assert resumen["total"] == 4
    assert resumen["por_estado"] == {
        "sin_contactar": 1,
        "promocion_enviada": 1,
        "vencida": 1,
        "recuperado": 1,
    }


def test_get_lista_las_ofertas_del_alumno_y_sus_dias(monkeypatch):
    sesion, ultimas = _escenario_cuatro_estados()
    _parchear(monkeypatch, ultimas)
    cliente = _cliente_con(sesion)

    fila = _por_id(cliente.get(RUTA).json())[2]

    assert fila["nombre"] == "Con Oferta Viva"
    assert fila["correo"] == "viva@test.com"
    assert fila["ultima_asistencia"] == str(HOY - timedelta(days=20))
    assert fila["dias_ausente"] == 20
    assert fila["promocion"]["tipo_beneficio"] == "dias_gratis"
    assert fila["promocion"]["cantidad"] == 5
    assert fila["promocion"]["vence_en"] == EN_10_DIAS.isoformat()


# ── GET: quién es "inactivo" ────────────────────────────────────────────────
def test_get_excluye_a_quien_asistio_dentro_del_umbral(monkeypatch):
    alumnos = [
        _FilaAlumno(1, "Activo", "activo@test.com"),
        _FilaAlumno(2, "Inactivo", "inactivo@test.com"),
    ]
    _parchear(monkeypatch, {1: HOY - timedelta(days=2),
                            2: HOY - timedelta(days=30)})
    cliente = _cliente_con(_SesionFalsa(alumnos=alumnos))

    alumnos_json = cliente.get(RUTA).json()["alumnos"]

    assert [a["id"] for a in alumnos_json] == [2]
    assert alumnos_json[0]["dias_ausente"] == 30


def test_get_excluye_a_quien_nunca_asistio(monkeypatch):
    """Sin historial NO es un inactivo a recuperar: nunca empezó a entrenar.

    Es el mismo criterio de `fidelizacion.py` (bucket `sin_historial`).
    """
    alumnos = [_FilaAlumno(1, "Recién Inscrito", "nuevo@test.com")]
    _parchear(monkeypatch, {})  # sin última asistencia
    cliente = _cliente_con(_SesionFalsa(alumnos=alumnos))

    body = cliente.get(RUTA).json()

    assert body["alumnos"] == []
    assert body["resumen"]["total"] == 0


def test_get_sin_alumnos_devuelve_panel_vacio(monkeypatch):
    _parchear(monkeypatch, {})
    cliente = _cliente_con(_SesionFalsa(alumnos=[], promociones=[]))

    body = cliente.get(RUTA).json()

    assert body["alumnos"] == []
    assert body["resumen"] == {
        "total": 0,
        "por_estado": {"sin_contactar": 0, "promocion_enviada": 0,
                       "vencida": 0, "recuperado": 0},
    }


def test_get_manda_la_oferta_mas_reciente(monkeypatch):
    """Dos ofertas: la última (viva) define el estado, no la vieja vencida."""
    alumnos = [_FilaAlumno(9, "Renovó Oferta", "r@test.com")]
    promociones = [
        _FilaPromo(30, usuario_id=9, estado="enviada", vence_en=EN_10_DIAS),
        _FilaPromo(20, usuario_id=9, estado="enviada",
                   vence_en=AHORA - timedelta(days=15)),
    ]
    _parchear(monkeypatch, {9: HOY - timedelta(days=40)})
    cliente = _cliente_con(_SesionFalsa(alumnos=alumnos, promociones=promociones))

    fila = _por_id(cliente.get(RUTA).json())[9]

    assert fila["estado"] == "promocion_enviada"
    assert fila["promocion"]["id"] == 30



# ── POST: crear la oferta + mandar el correo ────────────────────────────────
def _cuerpo(tipo_beneficio="dias_gratis", cantidad=5, vence_en=None):
    valor = vence_en or EN_10_DIAS
    return {
        "tipo_beneficio": tipo_beneficio,
        "cantidad": cantidad,
        "vence_en": valor if isinstance(valor, str) else valor.isoformat(),
    }


def _alumno_inactivo():
    return _FilaAlumno(ALUMNO_ID, "Inactivo", "inactivo@test.com",
                       telefono="+56911111111")


def test_post_crea_la_fila_y_manda_el_correo(monkeypatch):
    sesion = _SesionFalsa(alumnos=[_alumno_inactivo()])
    llamadas = _mock_envio(monkeypatch, (True, 555))
    cliente = _cliente_con(sesion)

    r = cliente.post(f"{RUTA}/{ALUMNO_ID}/promocion", json=_cuerpo())

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["usuario_id"] == ALUMNO_ID
    assert body["tipo_beneficio"] == "dias_gratis"
    assert body["cantidad"] == 5
    assert body["estado"] == "enviada"
    assert body["correo_enviado"] is True
    assert body["notificacion_id"] == 555

    # La fila quedó guardada ANTES de mandar el correo, con el admin que la configuró.
    assert len(sesion.agregados) == 1
    guardada = sesion.agregados[0]
    assert guardada.tenant_id == TENANT
    assert guardada.usuario_id == ALUMNO_ID
    assert guardada.creado_por == ADMIN_ID
    assert guardada.estado == "enviada"

    # El correo salió con los datos del alumno y la oferta exacta.
    assert len(llamadas) == 1
    alumno, tipo, cantidad, vence = llamadas[0]
    assert alumno["correo"] == "inactivo@test.com"
    assert alumno["nombre"] == "Inactivo"
    assert (tipo, cantidad) == ("dias_gratis", 5)
    # `vence_en` se normaliza al FIN del día elegido en Chile (ver `_vence_en_chile`).
    assert fecha_chile(vence) == EN_10_DIAS.date()
    assert vence > AHORA


def test_post_si_el_correo_falla_la_oferta_se_guarda_igual(monkeypatch):
    """Best-effort: el envío devuelve False y la oferta existe igual."""
    sesion = _SesionFalsa(alumnos=[_alumno_inactivo()])
    _mock_envio(monkeypatch, (False, None))
    cliente = _cliente_con(sesion)

    r = cliente.post(f"{RUTA}/{ALUMNO_ID}/promocion", json=_cuerpo())

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["correo_enviado"] is False
    assert body["notificacion_id"] is None
    assert body["estado"] == "enviada"      # la oferta sigue en pie
    assert len(sesion.agregados) == 1


def test_post_si_el_envio_revienta_no_rompe_el_endpoint(monkeypatch):
    """Una excepción del SMTP no puede tumbar el alta de la oferta."""
    sesion = _SesionFalsa(alumnos=[_alumno_inactivo()])
    _mock_envio(monkeypatch, revienta=True)
    cliente = _cliente_con(sesion)

    r = cliente.post(f"{RUTA}/{ALUMNO_ID}/promocion", json=_cuerpo())

    assert r.status_code == 201, r.text
    assert r.json()["correo_enviado"] is False
    assert r.json()["notificacion_id"] is None
    assert len(sesion.agregados) == 1


def test_post_alumno_de_otro_box_404(monkeypatch):
    _mock_envio(monkeypatch)
    cliente = _cliente_con(_SesionFalsa(alumnos=[]))

    r = cliente.post(f"{RUTA}/{ALUMNO_ID}/promocion", json=_cuerpo())

    assert r.status_code == 404, r.text
    assert "no encontrado" in r.json()["detail"].lower()


def test_post_tipo_de_beneficio_invalido_422(monkeypatch):
    _mock_envio(monkeypatch)
    cliente = _cliente_con(_SesionFalsa(alumnos=[_alumno_inactivo()]))

    r = cliente.post(f"{RUTA}/{ALUMNO_ID}/promocion",
                     json=_cuerpo(tipo_beneficio="2x1"))

    assert r.status_code == 422, r.text


def test_post_vence_en_el_pasado_400(monkeypatch):
    llamadas = _mock_envio(monkeypatch)
    sesion = _SesionFalsa(alumnos=[_alumno_inactivo()])
    cliente = _cliente_con(sesion)

    r = cliente.post(f"{RUTA}/{ALUMNO_ID}/promocion",
                     json=_cuerpo(vence_en=AHORA - timedelta(days=1)))

    assert r.status_code == 400, r.text
    assert "pasado" in r.json()["detail"].lower()
    assert sesion.agregados == []       # no se guarda nada ni se manda nada
    assert llamadas == []


def test_post_vence_en_se_guarda_como_fin_de_dia_chile(monkeypatch):
    """La oferta vence al final del día elegido en Chile, venga como venga el payload.

    Sin esto, la medianoche UTC del 31/12 es en Chile el 30/12 a las 21:00: el correo
    diría una fecha corrida y el último día de la oferta se perdería.
    """
    for payload in ("2026-12-31T00:00:00", "2026-12-31T00:00:00Z",
                    "2026-12-31T23:59:59-03:00"):
        sesion = _SesionFalsa(alumnos=[_alumno_inactivo()])
        llamadas = _mock_envio(monkeypatch, (True, 1))
        cliente = _cliente_con(sesion)

        r = cliente.post(f"{RUTA}/{ALUMNO_ID}/promocion",
                         json=_cuerpo(vence_en=payload))

        assert r.status_code == 201, (payload, r.text)
        vence = llamadas[0][3]
        assert vence.tzinfo is not None
        assert fecha_chile(vence) == date(2026, 12, 31), payload
        assert r.json()["vence_en"].startswith("2026-12-31"), payload



# ── PUT: marcar recuperado ──────────────────────────────────────────────────
def test_put_marca_la_promocion_vigente_como_recuperada(monkeypatch):
    _mock_envio(monkeypatch)
    promo = _FilaPromo(40, usuario_id=ALUMNO_ID, estado="enviada",
                       vence_en=EN_10_DIAS)
    sesion = _SesionFalsa(alumnos=[_alumno_inactivo()], promociones=[promo])
    cliente = _cliente_con(sesion)

    r = cliente.put(f"{RUTA}/{ALUMNO_ID}/marcar-recuperado")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == 40
    assert body["estado"] == "recuperado"
    assert body["usuario_id"] == ALUMNO_ID
    # El cambio se persiste (commit) sobre la MISMA fila.
    assert promo.estado == "recuperado"
    assert sesion.commits == 1


def test_put_sin_promocion_vigente_404(monkeypatch):
    _mock_envio(monkeypatch)
    sesion = _SesionFalsa(alumnos=[_alumno_inactivo()], promociones=[])
    cliente = _cliente_con(sesion)

    r = cliente.put(f"{RUTA}/{ALUMNO_ID}/marcar-recuperado")

    assert r.status_code == 404, r.text
    assert "vigente" in r.json()["detail"].lower()
    assert sesion.commits == 0


def test_put_alumno_de_otro_box_404(monkeypatch):
    _mock_envio(monkeypatch)
    cliente = _cliente_con(_SesionFalsa(alumnos=[], promociones=[]))

    r = cliente.put(f"{RUTA}/{ALUMNO_ID}/marcar-recuperado")

    assert r.status_code == 404, r.text
    assert "no encontrado" in r.json()["detail"].lower()


# ── Autorización: los TRES endpoints ────────────────────────────────────────
@pytest.mark.parametrize("rol", ["alumno", "coach"])
@pytest.mark.parametrize("metodo,ruta,kwargs", [
    ("get", RUTA, {}),
    ("post", f"{RUTA}/{ALUMNO_ID}/promocion", {"json": _cuerpo()}),
    ("put", f"{RUTA}/{ALUMNO_ID}/marcar-recuperado", {}),
])
def test_no_admin_recibe_403(metodo, ruta, kwargs, rol, monkeypatch):
    llamadas = _mock_envio(monkeypatch)
    sesion, ultimas = _escenario_cuatro_estados()
    _parchear(monkeypatch, ultimas)
    cliente = _cliente_con(sesion, rol=rol)

    r = getattr(cliente, metodo)(ruta, **kwargs)

    assert r.status_code == 403, r.text
    assert "administrador" in r.json()["detail"].lower()
    # Ni se guardó la oferta ni se intentó mandar el correo.
    assert sesion.agregados == []
    assert llamadas == []

