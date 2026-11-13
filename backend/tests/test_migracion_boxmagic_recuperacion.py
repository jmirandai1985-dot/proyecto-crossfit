"""Panel de RECUPERACIÓN de inactivos (`/api/v1/migracion-boxmagic/recuperacion*`) — AISLADO.

Cubre, SIN BD y SIN red (app mínima con el router REAL de `migracion_boxmagic.py`, una
`get_db` falsa y la última asistencia inyectada — mismo patrón que
`test_migracion_boxmagic_activacion.py`):

  * GET: la lista sale del PADRÓN (`candidatos_boxmagic`, grupo 'recuperacion'), cruzada
    por CORREO con las cuentas reales; un candidato sin cuenta cae en `sin_contactar`.
  * GET: los CUATRO estados (`sin_contactar`, `promocion_enviada`, `vencida`,
    `recuperado`), la oferta MÁS RECIENTE y el resumen agregado.
  * GET: la asistencia ya NO decide quién está en el panel (lo decide el estado de
    BoxMagic); sólo se usa para mostrar `ultima_asistencia` / `dias_ausente`.
  * POST: crea la fila, manda el correo (MOCKEADO, no sale nada) y responde
    `correo_enviado` true/false, incluido el caso en que el envío revienta: la oferta
    se guarda igual (best-effort).
  * GET preview: el ASUNTO y el HTML que mandaría el POST (el MISMO render del envío
    real), sin guardar la oferta ni llamar a ningún método de envío; 422/404.
  * PUT: marca recuperado y responde 404 cuando no hay promoción vigente.
  * 403 para un usuario que no es admin en los CUATRO endpoints.

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
from app.models.candidato_boxmagic import CandidatoBoxmagic  # noqa: E402
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


class _FilaCandidato:
    """Una fila del PADRÓN (`candidatos_boxmagic`), grupo 'recuperacion'."""

    def __init__(self, id_, nombre, correo, *, grupo="recuperacion",
                 estado_boxmagic="Inactivo", tenant_id=TENANT):
        self.id = id_
        self.tenant_id = tenant_id
        self.nombre = nombre
        self.correo = correo.lower()
        self.estado_boxmagic = estado_boxmagic
        self.grupo = grupo


class _FilaUsuario:
    """Una cuenta REAL del SaaS (`usuarios`): sólo la tienen los ya migrados.

    Los ids van en otro rango que los del padrón (1.. vs 201..) a propósito: si el
    endpoint mezclara los dos ids, los tests lo verían.
    """

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
    """Session mínima: `query(CandidatoBoxmagic)` devuelve el padrón, `query(Usuario)`
    las cuentas reales y `query(PromocionRecuperacion)` las ofertas tal como se
    configuraron; `add` les asigna id como haría Postgres."""

    def __init__(self, candidatos=None, usuarios=None, promociones=None):
        self._candidatos = candidatos or []
        self._usuarios = usuarios or []
        self._promociones = promociones or []
        self.agregados = []
        self.commits = 0
        self._siguiente_id = 100

    def query(self, *modelos):
        primero = modelos[0] if modelos else None
        if primero is CandidatoBoxmagic:
            return _Consulta(self._candidatos)
        if primero is Usuario:
            return _Consulta(self._usuarios)
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


def _por_candidato(body):
    """{candidato_id: fila}: la fila del panel se identifica por el padrón."""
    return {fila["candidato_id"]: fila for fila in body["alumnos"]}


def _escenario_cuatro_estados(ultima=HOY - timedelta(days=20)):
    """Un candidato inactivo por CADA estado del panel (padrón 201..204, cuentas 1..4).

    Los cuatro tienen cuenta REAL (es el escenario "ya migrados"): así se pueden colgar
    ofertas (`promociones_recuperacion.usuario_id`) y ver los cuatro estados.
    """
    candidatos = [
        _FilaCandidato(201, "Sin Contactar", "sin@test.com"),
        _FilaCandidato(202, "Con Oferta Viva", "viva@test.com"),
        _FilaCandidato(203, "Oferta Vencida", "vencida@test.com"),
        _FilaCandidato(204, "Ya Volvió", "volvio@test.com"),
    ]
    usuarios = [
        _FilaUsuario(1, "Sin Contactar", "sin@test.com"),
        _FilaUsuario(2, "Con Oferta Viva", "viva@test.com"),
        _FilaUsuario(3, "Oferta Vencida", "vencida@test.com"),
        _FilaUsuario(4, "Ya Volvió", "volvio@test.com"),
    ]
    promociones = [
        _FilaPromo(11, usuario_id=2, estado="enviada", vence_en=EN_10_DIAS),
        _FilaPromo(12, usuario_id=3, estado="enviada",
                   vence_en=AHORA - timedelta(days=2)),
        _FilaPromo(13, usuario_id=4, estado="recuperado", vence_en=EN_10_DIAS),
    ]
    return (_SesionFalsa(candidatos=candidatos, usuarios=usuarios,
                         promociones=promociones),
            {1: ultima, 2: ultima, 3: ultima, 4: ultima})


# ── GET: la lista sale del PADRÓN, no de `usuarios` ──────────────────────────
def test_get_lista_los_candidatos_del_padron(monkeypatch):
    """Aparecen los candidatos del padrón, incluso los que todavía no tienen cuenta."""
    candidatos = [
        _FilaCandidato(201, "Sin Cuenta", "sincuenta@test.com"),
        _FilaCandidato(202, "Con Cuenta", "concuenta@test.com"),
    ]
    usuarios = [
        _FilaUsuario(1, "Con Cuenta", "concuenta@test.com"),
        # Cuenta real que NO está en el padrón: no se lista.
        _FilaUsuario(9, "Alumno De Prueba", "prueba@test.com"),
    ]
    _parchear(monkeypatch, {1: HOY - timedelta(days=40)})
    cliente = _cliente_con(_SesionFalsa(candidatos=candidatos, usuarios=usuarios))

    body = cliente.get(RUTA).json()

    assert [f["nombre"] for f in body["alumnos"]] == ["Sin Cuenta", "Con Cuenta"]
    assert body["resumen"]["total"] == 2


def test_get_candidato_sin_cuenta_cae_en_sin_contactar(monkeypatch):
    """Sin `Usuario` no hay a quién ofrecerle ni de dónde sacar el correo: sin_contactar.

    Es el estado esperado ANTES de la migración real: la mayoría del padrón todavía no
    tiene cuenta, y el panel tiene que mostrarlos igual.
    """
    candidatos = [_FilaCandidato(201, "Nuevo del Padrón", "nuevo@test.com")]
    _parchear(monkeypatch, {})
    cliente = _cliente_con(_SesionFalsa(candidatos=candidatos, usuarios=[]))

    fila = _por_candidato(cliente.get(RUTA).json())[201]

    assert fila["estado"] == "sin_contactar"
    assert fila["id"] is None                 # no hay cuenta real todavía
    assert fila["promocion"] is None
    assert fila["telefono"] is None
    assert fila["ultima_asistencia"] is None
    assert fila["dias_ausente"] is None


def test_get_la_asistencia_ya_no_decide_quien_esta_en_el_panel(monkeypatch):
    """Quien vino ayer SIGUE en el panel si en BoxMagic está Inactivo.

    El criterio de "inactivo" pasó a ser el estado del Excel (grupo 'recuperacion'), no
    los 7+ días sin asistir de `fidelizacion.py`: los candidatos no tienen asistencias
    todavía y quien decide quién dejó de venir es BoxMagic. La asistencia sólo se usa
    para MOSTRAR cuánto hace que no viene.
    """
    candidatos = [_FilaCandidato(201, "Vino Ayer", "vinoayer@test.com")]
    usuarios = [_FilaUsuario(1, "Vino Ayer", "vinoayer@test.com")]
    _parchear(monkeypatch, {1: HOY - timedelta(days=2)})
    cliente = _cliente_con(_SesionFalsa(candidatos=candidatos, usuarios=usuarios))

    fila = _por_candidato(cliente.get(RUTA).json())[201]

    assert fila["estado"] == "sin_contactar"
    assert fila["dias_ausente"] == 2


# ── GET: los cuatro estados ─────────────────────────────────────────────────
def test_get_clasifica_los_cuatro_estados(monkeypatch):
    sesion, ultimas = _escenario_cuatro_estados()
    _parchear(monkeypatch, ultimas)
    cliente = _cliente_con(sesion)

    r = cliente.get(RUTA)

    assert r.status_code == 200, r.text
    alumnos = _por_candidato(r.json())
    assert alumnos[201]["estado"] == "sin_contactar"
    assert alumnos[201]["promocion"] is None
    assert alumnos[202]["estado"] == "promocion_enviada"
    assert alumnos[202]["promocion"]["id"] == 11
    assert alumnos[203]["estado"] == "vencida"
    assert alumnos[203]["promocion"]["id"] == 12
    assert alumnos[204]["estado"] == "recuperado"
    assert alumnos[204]["promocion"]["id"] == 13


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

    fila = _por_candidato(cliente.get(RUTA).json())[202]

    assert fila["nombre"] == "Con Oferta Viva"
    assert fila["correo"] == "viva@test.com"
    assert fila["ultima_asistencia"] == str(HOY - timedelta(days=20))
    assert fila["dias_ausente"] == 20
    assert fila["promocion"]["tipo_beneficio"] == "dias_gratis"
    assert fila["promocion"]["cantidad"] == 5
    assert fila["promocion"]["vence_en"] == EN_10_DIAS.isoformat()


# ── GET: borde del panel ────────────────────────────────────────────────────
def test_get_sin_candidatos_devuelve_panel_vacio(monkeypatch):
    """Un box sin padrón cargado: lista vacía (no los alumnos de prueba del SaaS)."""
    _parchear(monkeypatch, {})
    cliente = _cliente_con(_SesionFalsa(
        candidatos=[],
        usuarios=[_FilaUsuario(1, "Alumno De Prueba", "prueba@test.com")],
        promociones=[]))

    body = cliente.get(RUTA).json()

    assert body["alumnos"] == []
    assert body["resumen"] == {
        "total": 0,
        "por_estado": {"sin_contactar": 0, "promocion_enviada": 0,
                       "vencida": 0, "recuperado": 0},
    }


def test_get_manda_la_oferta_mas_reciente(monkeypatch):
    """Dos ofertas: la última (viva) define el estado, no la vieja vencida."""
    candidatos = [_FilaCandidato(201, "Renovó Oferta", "r@test.com")]
    usuarios = [_FilaUsuario(9, "Renovó Oferta", "r@test.com")]
    promociones = [
        _FilaPromo(30, usuario_id=9, estado="enviada", vence_en=EN_10_DIAS),
        _FilaPromo(20, usuario_id=9, estado="enviada",
                   vence_en=AHORA - timedelta(days=15)),
    ]
    _parchear(monkeypatch, {9: HOY - timedelta(days=40)})
    cliente = _cliente_con(_SesionFalsa(
        candidatos=candidatos, usuarios=usuarios, promociones=promociones))

    fila = _por_candidato(cliente.get(RUTA).json())[201]

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


def _alumno_real():
    """La cuenta REAL (`usuarios`) a la que se le configura la oferta.

    POST/PUT exigen un `Usuario` de verdad: la oferta se cuelga de `usuario_id` y el
    correo sale de esa fila. Un candidato del padrón sin cuenta no puede recibir oferta
    (404 "Alumno no encontrado"), que es lo esperado antes de la migración real.
    """
    return _FilaUsuario(ALUMNO_ID, "Inactivo", "inactivo@test.com",
                        telefono="+56911111111")


def test_post_crea_la_fila_y_manda_el_correo(monkeypatch):
    sesion = _SesionFalsa(usuarios=[_alumno_real()])
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
    sesion = _SesionFalsa(usuarios=[_alumno_real()])
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
    sesion = _SesionFalsa(usuarios=[_alumno_real()])
    _mock_envio(monkeypatch, revienta=True)
    cliente = _cliente_con(sesion)

    r = cliente.post(f"{RUTA}/{ALUMNO_ID}/promocion", json=_cuerpo())

    assert r.status_code == 201, r.text
    assert r.json()["correo_enviado"] is False
    assert r.json()["notificacion_id"] is None
    assert len(sesion.agregados) == 1


def test_post_alumno_de_otro_box_404(monkeypatch):
    _mock_envio(monkeypatch)
    cliente = _cliente_con(_SesionFalsa(usuarios=[]))

    r = cliente.post(f"{RUTA}/{ALUMNO_ID}/promocion", json=_cuerpo())

    assert r.status_code == 404, r.text
    assert "no encontrado" in r.json()["detail"].lower()


def test_post_tipo_de_beneficio_invalido_422(monkeypatch):
    _mock_envio(monkeypatch)
    cliente = _cliente_con(_SesionFalsa(usuarios=[_alumno_real()]))

    r = cliente.post(f"{RUTA}/{ALUMNO_ID}/promocion",
                     json=_cuerpo(tipo_beneficio="2x1"))

    assert r.status_code == 422, r.text


def test_post_vence_en_el_pasado_400(monkeypatch):
    llamadas = _mock_envio(monkeypatch)
    sesion = _SesionFalsa(usuarios=[_alumno_real()])
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
        sesion = _SesionFalsa(usuarios=[_alumno_real()])
        llamadas = _mock_envio(monkeypatch, (True, 1))
        cliente = _cliente_con(sesion)

        r = cliente.post(f"{RUTA}/{ALUMNO_ID}/promocion",
                         json=_cuerpo(vence_en=payload))

        assert r.status_code == 201, (payload, r.text)
        vence = llamadas[0][3]
        assert vence.tzinfo is not None
        assert fecha_chile(vence) == date(2026, 12, 31), payload
        assert r.json()["vence_en"].startswith("2026-12-31"), payload



# ── GET preview: el correo ANTES de mandarlo ────────────────────────────────
def _ruta_preview(usuario_id=ALUMNO_ID):
    return f"{RUTA}/{usuario_id}/promocion/preview"


def _params_preview(tipo_beneficio="dias_gratis", cantidad=5, vence_en=None):
    """Los TRES datos del formulario, como query params del preview."""
    valor = vence_en or EN_10_DIAS
    return {
        "tipo_beneficio": tipo_beneficio,
        "cantidad": cantidad,
        "vence_en": valor if isinstance(valor, str) else valor.isoformat(),
    }


def _mock_render(monkeypatch):
    """Espía del render REAL del correo: anota la llamada y delega en la función canónica.

    No reemplaza el copy (eso taparía justo lo que hay que probar): el test compara el
    asunto/HTML del endpoint con lo que produce `render_email_promocion_recuperacion`,
    la MISMA función del envío real. El espía sirve para ver CON QUÉ se la llamó.
    """
    llamadas = []
    real = email_service.render_email_promocion_recuperacion

    def _espia(nombre, tipo_beneficio, cantidad, vence_en):
        llamadas.append((nombre, tipo_beneficio, cantidad, vence_en))
        return real(nombre, tipo_beneficio, cantidad, vence_en)

    monkeypatch.setattr(email_service, "render_email_promocion_recuperacion", _espia)
    return llamadas


def test_preview_devuelve_el_mismo_correo_que_el_envio_real(monkeypatch):
    """El asunto/HTML del preview son los del envío real, y no se escribe nada."""
    # Lo que manda el envío real: el render canónico con el vencimiento ya normalizado.
    vence = migracion_boxmagic._vence_en_chile(EN_10_DIAS)
    asunto_esperado, html_esperado = email_service.render_email_promocion_recuperacion(
        "Inactivo", "dias_gratis", 5, vence)
    assert "{{CONTACTO_BOX}}" in html_esperado    # el template deja el pie pendiente

    sesion = _SesionFalsa(usuarios=[_alumno_real()])
    envios = _mock_envio(monkeypatch, (True, 555))
    renders = _mock_render(monkeypatch)
    cliente = _cliente_con(sesion)

    r = cliente.get(_ruta_preview(), params=_params_preview())

    assert r.status_code == 200, r.text
    body = r.json()
    # Sólo el correo: no hay ids de oferta ni nada que se haya guardado.
    assert set(body) == {"asunto", "html"}

    # Mismo asunto y mismo HTML que el envío real (que resuelve el pie de contacto en
    # `_enviar` justo antes de mandar).
    assert body["asunto"] == asunto_esperado
    assert body["html"] == email_service.render_con_contacto(
        html_esperado, TENANT, db=sesion)
    assert "{{CONTACTO_BOX}}" not in body["html"]

    # Se renderizó UNA vez, con el nombre/apellido real del alumno y la oferta exacta; el
    # vencimiento es el FIN DEL DÍA en Chile (lo mismo que recibe el envío real).
    assert len(renders) == 1
    nombre, tipo, cantidad, vence_recibido = renders[0]
    assert (nombre, tipo, cantidad) == ("Inactivo", "dias_gratis", 5)
    assert fecha_chile(vence_recibido) == EN_10_DIAS.date()

    # Sólo lectura: ninguna fila en promociones_recuperacion, ningún commit y NINGÚN envío.
    assert sesion.agregados == []
    assert sesion.commits == 0
    assert envios == []


@pytest.mark.parametrize("tipo,cantidad,texto", [
    ("dias_gratis", 5, "5 días gratis de clases"),
    ("descuento_porcentaje", 20, "20% de descuento"),
    ("descuento_monto", 10000, "$10.000 de descuento"),
])
def test_preview_nombra_el_beneficio_elegido(tipo, cantidad, texto, monkeypatch):
    """El correo que se ve es el de ESTA oferta: el beneficio va en asunto y cuerpo."""
    _mock_envio(monkeypatch)
    _mock_render(monkeypatch)
    cliente = _cliente_con(_SesionFalsa(usuarios=[_alumno_real()]))

    r = cliente.get(_ruta_preview(), params=_params_preview(tipo, cantidad))

    assert r.status_code == 200, r.text
    assert texto in r.json()["asunto"]
    assert texto in r.json()["html"]


def test_preview_tipo_de_beneficio_invalido_422(monkeypatch):
    sesion = _SesionFalsa(usuarios=[_alumno_real()])
    renders = _mock_render(monkeypatch)
    cliente = _cliente_con(sesion)

    r = cliente.get(_ruta_preview(), params=_params_preview("2x1", 5))

    assert r.status_code == 422, r.text
    assert renders == []            # ni siquiera se intentó renderizar
    assert sesion.agregados == []
    assert sesion.commits == 0


@pytest.mark.parametrize("cantidad", [0, -3, "dos"])
def test_preview_cantidad_invalida_422(cantidad, monkeypatch):
    sesion = _SesionFalsa(usuarios=[_alumno_real()])
    renders = _mock_render(monkeypatch)
    cliente = _cliente_con(sesion)

    r = cliente.get(_ruta_preview(), params=_params_preview(cantidad=cantidad))

    assert r.status_code == 422, r.text
    assert renders == []


def test_preview_alumno_de_otro_box_404(monkeypatch):
    renders = _mock_render(monkeypatch)
    envios = _mock_envio(monkeypatch)
    cliente = _cliente_con(_SesionFalsa(usuarios=[]))

    r = cliente.get(_ruta_preview(), params=_params_preview())

    assert r.status_code == 404, r.text
    assert "no encontrado" in r.json()["detail"].lower()
    assert renders == []
    assert envios == []


# ── PUT: marcar recuperado ──────────────────────────────────────────────────
def test_put_marca_la_promocion_vigente_como_recuperada(monkeypatch):
    _mock_envio(monkeypatch)
    promo = _FilaPromo(40, usuario_id=ALUMNO_ID, estado="enviada",
                       vence_en=EN_10_DIAS)
    sesion = _SesionFalsa(usuarios=[_alumno_real()], promociones=[promo])
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
    sesion = _SesionFalsa(usuarios=[_alumno_real()], promociones=[])
    cliente = _cliente_con(sesion)

    r = cliente.put(f"{RUTA}/{ALUMNO_ID}/marcar-recuperado")

    assert r.status_code == 404, r.text
    assert "vigente" in r.json()["detail"].lower()
    assert sesion.commits == 0


def test_put_alumno_de_otro_box_404(monkeypatch):
    _mock_envio(monkeypatch)
    cliente = _cliente_con(_SesionFalsa(usuarios=[], promociones=[]))

    r = cliente.put(f"{RUTA}/{ALUMNO_ID}/marcar-recuperado")

    assert r.status_code == 404, r.text
    assert "no encontrado" in r.json()["detail"].lower()


# ── Autorización: los CUATRO endpoints ──────────────────────────────────────
@pytest.mark.parametrize("rol", ["alumno", "coach"])
@pytest.mark.parametrize("metodo,ruta,kwargs", [
    ("get", RUTA, {}),
    ("get", f"{RUTA}/{ALUMNO_ID}/promocion/preview", {"params": _params_preview()}),
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

