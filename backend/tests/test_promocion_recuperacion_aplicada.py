"""Oferta de recuperación APLICADA en el alta (`services/promociones_recuperacion_service.py`).

Aislado: sin BD ni red. La sesión es falsa (devuelve las filas que arma el test) y el alta
del Beneficio se inyecta: lo que se prueba acá son las DECISIONES del servicio —qué tipo
crea qué Beneficio, cuándo NO se aplica y cómo queda la oferta—, no la aritmética de
`beneficios_service` (que tiene sus propios tests).

A diferencia de otros dobles del proyecto, acá los filtros SÍ se evalúan: la VIGENCIA de
la oferta (`vence_en`) es una de las reglas que hay que probar, y un fake que devolviera
la fila pase lo que pase no podría distinguir una oferta vigente de una vencida.

    cd backend && py -3.12 -m pytest tests/test_promocion_recuperacion_aplicada.py -q --noconftest
"""
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import Column
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import (
    BinaryExpression,
    BindParameter,
    BooleanClauseList,
)
from sqlalchemy.sql.functions import Function

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.models.beneficio import TipoBeneficio  # noqa: E402
from app.models.candidato_boxmagic import CandidatoBoxmagic  # noqa: E402
from app.models.promocion_recuperacion import (  # noqa: E402
    ESTADO_PROMO_ENVIADA,
    ESTADO_PROMO_RECUPERADO,
    TIPO_BENEFICIO_DESCUENTO_MONTO,
    PromocionRecuperacion,
)
from app.services import beneficios_service  # noqa: E402
from app.services import promociones_recuperacion_service as svc  # noqa: E402

TENANT = 1
ALUMNO_ID = 501
CANDIDATO_ID = 201
CORREO = "desertor@test.com"
AHORA = datetime.now(UTC)
# Una oferta con esta fecha sigue vigente en cualquier corrida (10 días de margen).
VIGENTE_HASTA = AHORA + timedelta(days=10)


def _valor(expresion, fila):
    """Valor de un lado de la comparación para ESA fila (columna, bind o función)."""
    if isinstance(expresion, BindParameter):
        return expresion.value
    if isinstance(expresion, (InstrumentedAttribute, Column)):
        return getattr(fila, expresion.key)
    if isinstance(expresion, Function):
        argumentos = [_valor(arg, fila) for arg in expresion.clauses]
        nombre = (expresion.name or "").lower()
        if nombre == "lower":
            return str(argumentos[0] or "").lower()
        if nombre == "trim":
            return str(argumentos[0] or "").strip()
    raise AssertionError(f"el fake no sabe evaluar {expresion!r}")


def _cumple(expresion, fila) -> bool:
    """Evalúa el criterio de SQLAlchemy contra una fila, sin base de datos."""
    if isinstance(expresion, BooleanClauseList):
        resultados = [_cumple(criterio, fila) for criterio in expresion.clauses]
        if expresion.operator is operators.or_:
            return any(resultados)
        if expresion.operator is operators.and_:
            return all(resultados)
        raise AssertionError(f"operador booleano no soportado: {expresion.operator!r}")
    if isinstance(expresion, BinaryExpression):
        return bool(expresion.operator(_valor(expresion.left, fila),
                                       _valor(expresion.right, fila)))
    raise AssertionError(f"el fake no sabe evaluar {expresion!r}")


class _Consulta:
    """`query(modelo).filter(...).order_by(...).first()` sobre las filas de la sesión.

    Los filtros se evalúan de verdad (ver el docstring del módulo). Se soportan los
    criterios que arma `buscar_promocion_enviada`: igualdad, comparación, `or_` y
    `lower(trim(...))` para el cruce por correo.
    """

    def __init__(self, filas):
        self._filas = list(filas)

    def filter(self, *criterios, **kwargs):
        self._filas = [fila for fila in self._filas
                       if all(_cumple(criterio, fila) for criterio in criterios)]
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self._filas[0] if self._filas else None


class _SesionFalsa:
    """Sesión mínima: padrón, ofertas y los dos contadores que importan (commit/rollback)."""

    def __init__(self, candidatos=(), promociones=(), fallar_commit=False):
        self._candidatos = list(candidatos)
        self._promociones = list(promociones)
        self.fallar_commit = fallar_commit
        self.commits = 0
        self.rollbacks = 0

    def query(self, modelo=None, *args, **kwargs):
        if modelo is CandidatoBoxmagic:
            return _Consulta(self._candidatos)
        if modelo is PromocionRecuperacion:
            return _Consulta(self._promociones)
        return _Consulta([])

    def commit(self):
        if self.fallar_commit:
            raise RuntimeError("commit caído (test)")
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _usuario(usuario_id=ALUMNO_ID, correo=CORREO):
    return SimpleNamespace(id=usuario_id, tenant_id=TENANT, correo=correo)


def _candidato(candidato_id=CANDIDATO_ID, correo=CORREO):
    return SimpleNamespace(id=candidato_id, tenant_id=TENANT, correo=correo)


def _promo(tipo=svc.TIPO_BENEFICIO_DIAS_GRATIS, cantidad=7, promo_id=90,
           vence_en=VIGENTE_HASTA):
    return SimpleNamespace(id=promo_id, tenant_id=TENANT,
                           candidato_id=CANDIDATO_ID, usuario_id=None,
                           tipo_beneficio=tipo, cantidad=cantidad,
                           estado=ESTADO_PROMO_ENVIADA, vence_en=vence_en)


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
    """`dias_gratis` → Beneficio `clases_gratis` y la oferta queda `recuperado`.

    Es el camino COMPLETO del alta: `buscar_promocion_enviada` encuentra la oferta
    pendiente del padrón (con los filtros REALES, incluida la vigencia) y el servicio la
    liga a la cuenta nueva, crea el Beneficio y la marca `recuperado` sin que nadie
    apriete el botón del panel.
    """
    promo = _promo()
    db = _SesionFalsa(candidatos=[_candidato()], promociones=[promo])
    usuario = _usuario()
    llamadas = _mock_crear(monkeypatch)

    beneficio = svc.aplicar_promocion_al_registrar(db, usuario)

    assert beneficio is not None
    assert llamadas == [(db, usuario, TipoBeneficio.clases_gratis.value, 7)]
    assert promo.usuario_id == ALUMNO_ID, "la oferta queda ligada a la cuenta nueva"
    assert promo.estado == ESTADO_PROMO_RECUPERADO, \
        "el alta deja de mostrar la oferta como 'enviada' para siempre"
    assert (db.commits, db.rollbacks) == (1, 0)


def test_oferta_vencida_no_se_marca_aunque_el_alumno_se_registre(monkeypatch):
    """Una oferta vencida NO se canjea ni se marca al registrarse.

    Mismo criterio que el panel y el botón manual: la ventana se mira contra `vence_en`.
    El alta sigue su curso, pero no regala nada ni falsea el estado de la oferta.
    """
    vencida = _promo(vence_en=AHORA - timedelta(seconds=1))
    db = _SesionFalsa(candidatos=[_candidato()], promociones=[vencida])
    llamadas = _mock_crear(monkeypatch)

    assert svc.aplicar_promocion_al_registrar(db, _usuario()) is None

    assert llamadas == [], "una oferta vencida no crea Beneficio"
    assert vencida.usuario_id is None and vencida.estado == ESTADO_PROMO_ENVIADA, \
        "la oferta vencida se queda como estaba"
    assert (db.commits, db.rollbacks) == (0, 0)


def test_oferta_que_vence_exactamente_ahora_ya_no_se_aplica(monkeypatch):
    """`vence_en == ahora` ya es 'vencida': criterio estricto, igual que el botón manual."""
    justo_ahora = _promo(vence_en=AHORA)
    db = _SesionFalsa(candidatos=[_candidato()], promociones=[justo_ahora])
    _mock_crear(monkeypatch)

    assert svc.aplicar_promocion_al_registrar(db, _usuario(), ahora=AHORA) is None
    assert justo_ahora.estado == ESTADO_PROMO_ENVIADA


def test_si_falla_el_commit_del_marcado_el_alta_no_se_cae(monkeypatch, caplog):
    """Best-effort: el Beneficio ya está dado; un commit caído al marcar no se propaga.

    El alta ya está guardada por el llamador y `beneficios_service.crear()` ya commiteó
    el regalo: si falla el `commit` que marca la oferta, se loguea y se devuelve el
    Beneficio. El registro del alumno NUNCA se cae por esta señal secundaria.
    """
    db = _SesionFalsa(candidatos=[_candidato()], promociones=[_promo()],
                      fallar_commit=True)
    creado = SimpleNamespace(id=1234)
    _mock_crear(monkeypatch, creado)

    with caplog.at_level(logging.ERROR, logger=svc.__name__):
        beneficio = svc.aplicar_promocion_al_registrar(db, _usuario())

    assert beneficio is creado, "el regalo ya está dado y no se revierte"
    assert (db.commits, db.rollbacks) == (0, 1)
    assert "no se pudo marcar la oferta" in caplog.text


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
    db = _SesionFalsa(candidatos=[_candidato()],
                      promociones=[reciente, _promo(promo_id=90)])

    assert svc.buscar_promocion_enviada(db, _usuario()) is reciente


def test_buscar_promocion_enviada_sin_candidato_es_none():
    """Un correo que no está en el padrón no tiene oferta: no se inventa nada."""
    db = _SesionFalsa(candidatos=[], promociones=[_promo()])

    assert svc.buscar_promocion_enviada(db, _usuario()) is None


def test_buscar_promocion_enviada_sin_correo_es_none():
    """Una cuenta sin correo no puede cruzarse con el padrón."""
    db = _SesionFalsa(candidatos=[_candidato()], promociones=[_promo()])

    assert svc.buscar_promocion_enviada(db, _usuario(correo="")) is None
    assert svc.buscar_promocion_enviada(db, None) is None
