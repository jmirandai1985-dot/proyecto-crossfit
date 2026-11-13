"""Oferta de recuperación APLICADA en el alta (`services/promociones_recuperacion_service.py`).

Aislado: sin BD ni red. La sesión es falsa (devuelve las filas que arma el test) y el alta
del Beneficio se inyecta: lo que se prueba acá son las DECISIONES del servicio —qué tipo
crea qué Beneficio, cuándo NO se aplica y cómo queda la oferta—, no la aritmética de
`beneficios_service` (que tiene sus propios tests).

    cd backend && py -3.12 -m pytest tests/test_promocion_recuperacion_aplicada.py -q --noconftest
"""
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.models.beneficio import TipoBeneficio                           # noqa: E402
from app.models.candidato_boxmagic import CandidatoBoxmagic               # noqa: E402
from app.models.promocion_recuperacion import (                           # noqa: E402
    ESTADO_PROMO_ENVIADA, ESTADO_PROMO_RECUPERADO,
    TIPO_BENEFICIO_DESCUENTO_MONTO, PromocionRecuperacion,
)
from app.services import beneficios_service                               # noqa: E402
from app.services import promociones_recuperacion_service as svc          # noqa: E402

TENANT = 1
ALUMNO_ID = 501
CORREO = "desertor@test.com"


class _Consulta:
    """`query(modelo).filter(...).order_by(...).first()` con las filas que trae la sesión.

    Los filtros no se evalúan (como en el resto de los tests aislados del proyecto): el
    test ARMA las filas que el servicio tiene que encontrar y verifica qué hizo con ellas.
    """

    def __init__(self, filas):
        self._filas = list(filas)

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self._filas[0] if self._filas else None


class _SesionFalsa:
    """Sesión mínima: padrón, ofertas y los dos contadores que importan (commit/rollback)."""

    def __init__(self, candidatos=(), promociones=()):
        self._candidatos = list(candidatos)
        self._promociones = list(promociones)
        self.commits = 0
        self.rollbacks = 0

    def query(self, modelo=None, *args, **kwargs):
        if modelo is CandidatoBoxmagic:
            return _Consulta(self._candidatos)
        if modelo is PromocionRecuperacion:
            return _Consulta(self._promociones)
        return _Consulta([])

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _usuario(usuario_id=ALUMNO_ID, correo=CORREO):
    return SimpleNamespace(id=usuario_id, tenant_id=TENANT, correo=correo)


def _promo(tipo=svc.TIPO_BENEFICIO_DIAS_GRATIS, cantidad=7, promo_id=90):
    return SimpleNamespace(id=promo_id, tipo_beneficio=tipo, cantidad=cantidad,
                           usuario_id=None, estado=ESTADO_PROMO_ENVIADA)


def _mock_crear(monkeypatch, beneficio=None):
    """Inyecta `beneficios_service.crear` y devuelve la lista de llamadas (db, alumno, tipo, valor)."""
    llamadas = []
    creado = beneficio or SimpleNamespace(id=1234)

    def _falso(db, alumno, tipo, valor, **kwargs):
        llamadas.append((db, alumno, tipo, valor))
        return creado

    monkeypatch.setattr(beneficios_service, "crear", _falso)
    return llamadas


def _sin_busqueda(monkeypatch, promo):
    """Fija lo que encuentra `buscar_promocion_enviada` (su consulta se prueba aparte)."""
    monkeypatch.setattr(svc, "buscar_promocion_enviada", lambda *a, **k: promo)


def test_sin_oferta_no_toca_nada(monkeypatch):
    """Sin oferta `enviada` vigente no se crea nada ni se escribe una sola fila."""
    db = _SesionFalsa()
    _sin_busqueda(monkeypatch, None)
    llamadas = _mock_crear(monkeypatch)

    assert svc.aplicar_promocion_al_registrar(db, _usuario()) is None
    assert llamadas == []
    assert (db.commits, db.rollbacks) == (0, 0)


def test_sin_id_de_usuario_no_hace_nada(monkeypatch):
    """El alta llama al servicio antes de tener id: ahí no hay a quién ligar la oferta."""
    db = _SesionFalsa()
    _sin_busqueda(monkeypatch, _promo())
    llamadas = _mock_crear(monkeypatch)

    assert svc.aplicar_promocion_al_registrar(db, _usuario(usuario_id=None)) is None
    assert llamadas == []


def test_dias_gratis_crea_un_beneficio_de_clases_y_marca_la_oferta(monkeypatch):
    """`dias_gratis` → Beneficio `clases_gratis` con la MISMA cantidad (7 clases)."""
    db = _SesionFalsa()
    promo = _promo()
    usuario = _usuario()
    _sin_busqueda(monkeypatch, promo)
    llamadas = _mock_crear(monkeypatch)

    beneficio = svc.aplicar_promocion_al_registrar(db, usuario)

    assert beneficio is not None
    assert llamadas == [(db, usuario, TipoBeneficio.clases_gratis.value, 7)]
    assert promo.usuario_id == ALUMNO_ID, "la oferta queda ligada a la cuenta nueva"
    assert promo.estado == ESTADO_PROMO_RECUPERADO, \
        "deja de aparecer como 'enviada' para siempre"
    assert (db.commits, db.rollbacks) == (1, 0)


def test_descuento_porcentaje_crea_un_beneficio_de_descuento(monkeypatch):
    """`descuento_porcentaje` → Beneficio `descuento` con el mismo % (20)."""
    db = _SesionFalsa()
    promo = _promo(tipo=svc.TIPO_BENEFICIO_DESCUENTO_PORCENTAJE, cantidad=20)
    _sin_busqueda(monkeypatch, promo)
    llamadas = _mock_crear(monkeypatch)

    assert svc.aplicar_promocion_al_registrar(db, _usuario()) is not None
    assert llamadas[0][2:] == (TipoBeneficio.descuento.value, 20)
    assert promo.estado == ESTADO_PROMO_RECUPERADO



def test_descuento_monto_heredado_no_crea_nada_ni_marca_la_oferta(monkeypatch, caplog):
    """El tipo "Descuento en dinero" no tiene equivalente en el cobro: no se inventa.

    La fila histórica NO se toca (ni se borra ni se marca): queda para que el admin la
    resuelva a mano, y el log lo dice.
    """
    db = _SesionFalsa()
    promo = _promo(tipo=TIPO_BENEFICIO_DESCUENTO_MONTO, cantidad=10000)
    _sin_busqueda(monkeypatch, promo)
    llamadas = _mock_crear(monkeypatch)

    with caplog.at_level(logging.WARNING, logger=svc.__name__):
        assert svc.aplicar_promocion_al_registrar(db, _usuario()) is None

    assert llamadas == [], "no se crea un Beneficio que el sistema no sabe cobrar"
    assert promo.usuario_id is None and promo.estado == ESTADO_PROMO_ENVIADA
    assert (db.commits, db.rollbacks) == (0, 0)
    assert "no tiene equivalente" in caplog.text


def test_si_el_beneficio_no_se_puede_crear_la_oferta_queda_enviada(monkeypatch):
    """Best-effort: un Beneficio rechazado (ya tiene uno vivo) no rompe el alta."""
    db = _SesionFalsa()
    promo = _promo()
    _sin_busqueda(monkeypatch, promo)

    def _revienta(*args, **kwargs):
        raise beneficios_service.BeneficioYaVigente("Ya tiene un regalo vigente")

    monkeypatch.setattr(beneficios_service, "crear", _revienta)

    assert svc.aplicar_promocion_al_registrar(db, _usuario()) is None
    assert promo.usuario_id is None and promo.estado == ESTADO_PROMO_ENVIADA
    assert db.rollbacks == 1, "la sesión queda usable para el resto del request"
    assert db.commits == 0


def test_buscar_promocion_enviada_encuentra_la_fila_del_padron():
    """Con candidato en el padrón devuelve su oferta (la MÁS RECIENTE que trae la sesión)."""
    reciente = _promo(promo_id=91)
    db = _SesionFalsa(candidatos=[SimpleNamespace(id=201, correo=CORREO)],
                      promociones=[reciente, _promo(promo_id=90)])

    assert svc.buscar_promocion_enviada(db, _usuario()) is reciente


def test_buscar_promocion_enviada_sin_candidato_es_none():
    """Un correo que no está en el padrón no tiene oferta: no se inventa nada."""
    db = _SesionFalsa(candidatos=[], promociones=[_promo()])

    assert svc.buscar_promocion_enviada(db, _usuario()) is None


def test_buscar_promocion_enviada_sin_correo_es_none():
    """Una cuenta sin correo no puede cruzarse con el padrón."""
    db = _SesionFalsa(candidatos=[SimpleNamespace(id=201, correo=CORREO)],
                      promociones=[_promo()])

    assert svc.buscar_promocion_enviada(db, _usuario(correo="")) is None
    assert svc.buscar_promocion_enviada(db, None) is None
