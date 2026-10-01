"""Fase 2 de Fidelización: la tabla de beneficios y su ciclo de vida (servicio).

Qué fija este archivo
---------------------
Un beneficio es un regalo que el box le manda al alumno POR CORREO: clases gratis (que le suman
créditos a su plan vigente o le abren el pase) o un descuento en su próximo plan. El correo lo crea
—no hay aceptación— y el regalo vive 15 días. Este archivo fija lo que, si se afloja, rompe la
feature en silencio:

  * los estados y tipos del modelo son los del enum de la migración 038 (y NO existe `aceptado`);
  * la regla 1 — estado y ventana son UN criterio (`esta_vivo`): un `ofrecido` con la ventana pasada
    no se puede usar, diga lo que diga la fila;
  * la **corrección B** — `crear()` vence los vencidos ANTES y en la MISMA transacción (UN solo
    `commit()`): si no, el alumno tendría dos regalos vivos y podría usar los dos;
  * la regla 3 — el acceso se materializa AL DARLO: con plan vigente se SUMAN las clases (y **caducan
    con ese plan**: la ventana se recorta a su expiración), sin plan se abre el pase, y el pase NO
    puede quedar como una membresía (corrección A);
  * la regla 10 — el plan del pase lo crea el SISTEMA (`plan_del_pase`), uno por box y reusado por los
    regalos siguientes: el admin no configura nada y el plan nace gratis, no comercial y fuera del
    catálogo;
  * la regla 6 — el descuento se calcula AL USARLO: al ofrecerlo no se sabe qué plan va a comprar;
  * la regla 9 (decisión 3) — **un solo regalo VIVO por alumno y tipo**: el segundo se rechaza con el
    texto de `aviso_vigente()` (el router lo devuelve como 409) y no materializa nada;
  * **`notificacion_id` es OPCIONAL**: el panel puede dar un beneficio sin avisar por correo.

  A. PURAS (sin BD): catálogo/enums, `esta_vivo`, el tope del box, la aritmética del descuento y el
     ORDEN vencimiento→alta→UN `commit()` (con una sesión falsa que registra los eventos).
  B. CONTRA TEST (escribe y RESTAURA): el vencimiento real contra el enum nativo, el alcance del
     `WHERE`, la materialización (pase vs créditos extra) y la anulación con su revocación.

Correr:
    ENVIRONMENT=test py -3.12 -m pytest tests/test_beneficios_service.py -q
"""
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import settings                                          # noqa: E402
from app.models.beneficio import Beneficio, EstadoBeneficio, TipoBeneficio     # noqa: E402
from app.models.plan import Plan                                              # noqa: E402
from app.models.suscripcion import EstadoSuscripcion, Suscripcion             # noqa: E402
from app.models.usuario import Usuario                                        # noqa: E402
from app.services import beneficios_service as svc                            # noqa: E402
from app.utils.santiago import SANTIAGO, fin_del_dia_chile                        # noqa: E402

TENANT_ID = 1
PRECIO_PASE = 25000
CLASES = 3
TOPE_TEST = 20
# Instante de referencia fijo: los tests son consistentes entre sí sin depender del reloj.
T0 = datetime(2026, 9, 29, 12, 0, tzinfo=SANTIAGO)


def _beneficio(estado, vence, tipo=TipoBeneficio.clases_gratis, valor=CLASES):
    """Un beneficio de mentira para las reglas puras (no toca la BD ni el ORM)."""
    return SimpleNamespace(estado=estado, tipo=tipo, valor=valor, vigente_hasta=vence,
                           descuento_clp=None, plan_id=None, suscripcion_id=None,
                           anulado_por=None, anulado_at=None, anulado_motivo=None)


def _instante(valor):
    """El instante en UTC (las columnas son `timestamptz`: comparar zonas es comparar instantes)."""
    return valor.astimezone(timezone.utc)


def _cargar_migracion(nombre):
    """El módulo de la migración (sin conectarse a la base): el enum de la BD y el del modelo."""
    ruta = BACKEND / "alembic" / "versions" / f"{nombre}.py"
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _valor_descuento(db):
    """Un % válido para este box, sin depender de cómo esté configurado el tope en TEST."""
    return min(10, svc.tope_descuento(db, TENANT_ID))

# ══════════════════════════════════════════════════════════════════════════════
# A. Reglas puras (sin BD)
# ══════════════════════════════════════════════════════════════════════════════
def test_a1_los_enums_del_modelo_son_los_de_la_migracion_y_no_existe_aceptado():
    """El `tipo`/`estado` salen del enum nativo (una sola definición con la migración 038)."""
    modulo = _cargar_migracion("038_beneficios")
    enums = dict(modulo.ENUMS)

    assert enums["estado_beneficio"] == tuple(e.value for e in EstadoBeneficio)
    assert enums["estado_beneficio"] == ("ofrecido", "usado", "vencido", "anulado")
    assert "aceptado" not in enums["estado_beneficio"], \
        "el acceso se materializa al enviar el correo: no hay paso de aceptación"
    assert enums["tipo_beneficio"] == tuple(t.value for t in TipoBeneficio)

    # El catálogo cubre exactamente los tipos del enum: ni un tipo sin reglas, ni reglas sin tipo.
    assert svc.TIPOS_VALIDOS == tuple(t.value for t in TipoBeneficio)
    for entrada in svc.TIPOS:
        assert set(entrada) == {"id", "label", "descripcion", "unidad", "valores", "materializa"}
    assert svc.etiqueta(svc.TIPO_CLASES_GRATIS) == "Clases gratis"
    assert svc.etiqueta("tipo_viejo") == "tipo_viejo", "un id viejo no rompe la lectura"
    # Sin aceptación no hay `aceptar()`: el regalo se entrega al mandarlo.
    assert not hasattr(svc, "aceptar")


def test_a2_el_estado_y_la_ventana_son_un_solo_criterio():
    """Regla 1: un `ofrecido` con la ventana pasada NO está vivo, diga lo que diga la fila."""
    dentro = T0 + timedelta(days=1)
    assert svc.esta_vivo(_beneficio(EstadoBeneficio.ofrecido, dentro), ahora=T0) is True
    assert svc.esta_vivo(_beneficio(EstadoBeneficio.ofrecido, T0 - timedelta(seconds=1)),
                         ahora=T0) is False
    # La ventana se cierra EXACTA: en el instante de vencimiento ya no está vivo.
    assert svc.esta_vivo(_beneficio(EstadoBeneficio.ofrecido, T0), ahora=T0) is False
    for estado in (EstadoBeneficio.usado, EstadoBeneficio.vencido, EstadoBeneficio.anulado):
        assert svc.esta_vivo(_beneficio(estado, dentro), ahora=T0) is False, estado
    assert svc.esta_vivo(None, ahora=T0) is False


def test_a3_la_ventana_sin_zona_se_asume_utc():
    """Un instante sin tzinfo no puede hacer explotar la comparación (`TypeError` = 500)."""
    naive = datetime(2026, 9, 29, 12, 0)
    assert svc.esta_vivo(_beneficio(EstadoBeneficio.ofrecido, naive + timedelta(days=1)),
                         ahora=naive) is True
    # Y con los DOS instantes naive la ventana se cierra igual de exacta que con zona (regla 1).
    assert svc.esta_vivo(_beneficio(EstadoBeneficio.ofrecido, naive), ahora=naive) is False
    assert svc._aware(naive).tzinfo == timezone.utc
    assert svc._aware(T0) is T0


def test_a4_el_tope_del_box_no_puede_regalar_mas_de_100():
    """El tope del % es configuración saneada: un valor imposible cae al default del diseño."""
    for imposible in (None, "50", 0, -5, 101, 1000, True):
        assert svc._normalizar_tope(imposible) == svc.TOPE_DESCUENTO_DEFAULT, imposible
    for valido in (1, 20, 50, 100):
        assert svc._normalizar_tope(valido) == valido

    # Y se lee de UNA sola fila: la configuración del box (`configuracion_negocio`).
    assert svc.tope_descuento(_SesionFalsa(tope=TOPE_TEST), TENANT_ID) == TOPE_TEST
    assert svc.tope_descuento(_SesionFalsa(tope=None), TENANT_ID) == svc.TOPE_DESCUENTO_DEFAULT


def test_a5_el_descuento_es_una_sola_aritmetica_sobre_el_precio_de_lista():
    """Regla 6: % sobre el precio de LISTA → precio final (es el snapshot que va a la solicitud)."""
    descuento = _beneficio(EstadoBeneficio.ofrecido, T0 + timedelta(days=1),
                           tipo=TipoBeneficio.descuento, valor=20)
    assert svc.desglose(descuento, 30000) == {
        "precio_lista_clp": 30000, "descuento_pct": 20,
        "descuento_clp": 6000, "precio_final_clp": 24000}
    # El redondeo es al peso: los precios son CLP (no hay centavos que guardar).
    descuento.valor = 33
    assert svc.desglose(descuento, 10000)["descuento_clp"] == 3300

    # Sólo un descuento se aplica sobre un precio, y el precio tiene que ser un precio.
    clases = _beneficio(EstadoBeneficio.ofrecido, T0 + timedelta(days=1))
    for malo in (clases, None):
        with pytest.raises(svc.ValorInvalido):
            svc.desglose(malo, 30000)
    for malo in (None, 0, -1, "30000", 30000.5, True):
        with pytest.raises(svc.ValorInvalido):
            svc.desglose(descuento, malo)

class _ConsultaFalsa:
    """`query(...).filter(...)` de la sesión falsa: registra los eventos y resuelve lo que le pidan."""

    def __init__(self, sesion, modo, valor=None):
        self.sesion = sesion
        self.modo = modo        # "plan" | "vigente" | "beneficio" | "tope"
        self.valor = valor

    def filter(self, *args, **kwargs):
        return self

    def join(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def update(self, valores, synchronize_session=None):
        self.sesion.eventos.append(("vencer", dict(valores)))
        return self.sesion.filas_vencidas

    def with_for_update(self):
        # El lock del box (`SELECT tenants.id ... FOR UPDATE`) que hace idempotente al "si no existe,
        # créalo": acá no hay concurrencia que serializar, pero la sesión falsa tiene que aceptarlo.
        self.sesion.eventos.append(("lock_box",))
        return self

    def first(self):
        # `plan` = el plan del pase del box (`plan_del_pase`); `vigente` = la suscripción del alumno.
        self.sesion.eventos.append(("buscar_" + self.modo,))
        return self.valor

    def scalar(self):
        self.sesion.eventos.append(("tope",))
        return self.valor

    def all(self):
        # `vivos()`: los regalos vivos que declare el escenario (la lectura de la decisión 3).
        self.sesion.eventos.append(("vivos",))
        return list(self.sesion.vivos_hoy)


class _SesionFalsa:
    """Sesión mínima que registra el ORDEN de los eventos y las filas dadas de alta (no toca la BD)."""

    def __init__(self, filas_vencidas=0, plan=None, vigente=None, tope=TOPE_TEST, vivos_hoy=()):
        self.eventos = []
        self.nuevos = []
        self.filas_vencidas = filas_vencidas
        self.plan = plan            # el plan del pase que se va a regalar (si no hay vigente)
        self.vigente = vigente      # la suscripción vigente comercial del alumno (o None)
        self.tope = tope
        self.vivos_hoy = list(vivos_hoy)   # lo que devuelve `vivos()` (un regalo vivo = decisión 3)

    def query(self, *modelos, **kwargs):
        modelo = modelos[0] if modelos else None
        if modelo is Plan:
            return _ConsultaFalsa(self, "plan", self.plan)
        if modelo is Suscripcion:
            return _ConsultaFalsa(self, "vigente", self.vigente)
        if modelo is Beneficio:
            return _ConsultaFalsa(self, "beneficio", self.filas_vencidas)
        return _ConsultaFalsa(self, "tope", self.tope)

    def add(self, obj):
        self.eventos.append(("add", type(obj).__name__))
        self.nuevos.append(obj)

    def flush(self):
        # El pase existe en la transacción: el beneficio ya puede apuntarle con su id.
        for obj in self.nuevos:
            if getattr(obj, "id", None) is None:
                obj.id = len(self.nuevos)
        self.eventos.append(("flush",))

    def commit(self):
        self.eventos.append(("commit",))

    def refresh(self, obj):
        self.eventos.append(("refresh", type(obj).__name__))


def test_a6_crear_rechaza_lo_imposible_antes_de_tocar_la_base():
    """Sin tipo válido, sin valor posible o sobre el tope: no se crea nada (el correo es opcional)."""
    alumno = SimpleNamespace(id=999, tenant_id=TENANT_ID)
    with pytest.raises(svc.TipoDesconocido) as err:
        svc.crear(None, alumno, "pase_regresoo", CLASES, notificacion_id=1, ahora=T0)
    assert svc.TIPO_CLASES_GRATIS in str(err.value), "el error dice cuáles son los válidos"

    sesion = _SesionFalsa()
    for malo in (0, -1, "3", None, True, 3.5):
        with pytest.raises(svc.ValorInvalido):
            svc.crear(sesion, alumno, svc.TIPO_CLASES_GRATIS, malo, notificacion_id=1, ahora=T0)
    for fuera in (4, 6, 100):
        with pytest.raises(svc.ValorInvalido):
            svc.crear(sesion, alumno, svc.TIPO_CLASES_GRATIS, fuera, notificacion_id=1, ahora=T0)
    assert sesion.eventos == [], "nada de esto llegó a consultar la base"

    # El % lo topea el box (acá 20): 20 entra, 21 no.
    with pytest.raises(svc.DescuentoSobreTope) as err:
        svc.crear(_SesionFalsa(tope=TOPE_TEST), alumno, svc.TIPO_DESCUENTO, TOPE_TEST + 1,
                  notificacion_id=1, ahora=T0)
    assert str(TOPE_TEST) in str(err.value)

    # Un regalo SIN correo también es válido (ajuste del paso 2): `notificacion_id` es opcional.
    sin_correo = svc.crear(_SesionFalsa(tope=TOPE_TEST), alumno, svc.TIPO_DESCUENTO, TOPE_TEST,
                           ahora=T0)
    assert sin_correo.notificacion_id is None


def test_a7_la_correccion_b_vence_y_da_de_alta_en_una_sola_transaccion():
    """`crear()` = vence los vencidos → alta → UN `commit()`: no hay ventana de dos regalos vivos."""
    alumno = SimpleNamespace(id=999, tenant_id=TENANT_ID)
    sesion = _SesionFalsa(filas_vencidas=1, tope=TOPE_TEST)

    beneficio = svc.crear(sesion, alumno, svc.TIPO_DESCUENTO, TOPE_TEST, notificacion_id=77,
                          ahora=T0)

    pasos = [e[0] for e in sesion.eventos
             if e[0] in ("vencer", "add", "flush", "commit", "refresh")]
    assert pasos == ["vencer", "add", "commit", "refresh"], \
        "un commit entre el vencimiento y el alta dejaría al alumno con dos regalos vivos"
    assert pasos.count("commit") == 1
    # El vencimiento se escribe con el instante de referencia (no con el reloj del server).
    vencido = [e[1] for e in sesion.eventos if e[0] == "vencer"][0]
    assert vencido["estado"] == EstadoBeneficio.vencido
    assert vencido["vencido_en"] == T0
    # El alta: la ventana son 15 días desde el envío y el descuento TODAVÍA no se calculó.
    assert (beneficio.estado, beneficio.tipo) == (EstadoBeneficio.ofrecido, TipoBeneficio.descuento)
    assert (beneficio.tenant_id, beneficio.alumno_id) == (TENANT_ID, 999)
    assert beneficio.valor == TOPE_TEST
    assert beneficio.vigente_hasta == T0 + timedelta(days=svc.DIAS_VIGENCIA)
    assert beneficio.notificacion_id == 77
    assert beneficio.descuento_clp is None, "se calcula al usarlo, no al ofrecerlo"
    assert beneficio.suscripcion_id is None, "un descuento no materializa acceso"
    assert beneficio.plan_id is None, "el plan lo elige el alumno al comprarlo"

def test_a8_el_acceso_se_materializa_al_enviar_el_correo():
    """Regla 3: sin plan vigente se abre el PASE en el mismo movimiento (no hay aceptación)."""
    alumno = SimpleNamespace(id=999, tenant_id=TENANT_ID)
    plan = SimpleNamespace(id=7, tenant_id=TENANT_ID, precio_clp=PRECIO_PASE, es_comercial=False)
    sesion = _SesionFalsa(plan=plan)

    beneficio = svc.crear(sesion, alumno, svc.TIPO_CLASES_GRATIS, CLASES, notificacion_id=77,
                          plan_id=plan.id, ahora=T0)

    pasos = [e[0] for e in sesion.eventos
             if e[0] in ("vencer", "add", "flush", "commit", "refresh")]
    assert pasos == ["add", "flush", "vencer", "add", "commit", "refresh"], \
        "el pase, el vencimiento y el alta van en UNA sola transacción"
    assert pasos.count("commit") == 1
    # El pase: la ventana ES la duración de la suscripción, que arranca con las clases regaladas.
    pase = sesion.nuevos[0]
    assert isinstance(pase, Suscripcion)
    assert pase.estado == EstadoSuscripcion.activo, "un acceso regalado es usable de inmediato"
    assert (pase.creditos_totales, pase.creditos_disponibles) == (CLASES, CLASES)
    assert pase.fecha_inicio == T0
    assert pase.fecha_expiracion == T0 + timedelta(days=svc.DIAS_VIGENCIA)
    assert pase.fecha_expiracion == beneficio.vigente_hasta
    # Y el beneficio apunta al acceso que acaba de abrir.
    assert beneficio.suscripcion_id == pase.id
    assert beneficio.plan_id == plan.id


def test_a8b_sin_plan_del_pase_el_alta_lo_crea_en_la_misma_transaccion():
    """Regla 10: el plan del pase lo crea el SISTEMA — el admin no lo elige ni lo configura.

    Es el bug que esto cierra: un box sin plan del pase dejaba el regalo de clases en un 400. Acá no
    se pasa `plan_id` y el alta crea el plan del box DENTRO de su propia transacción (nada de un plan
    suelto o de un acceso sin plan).
    """
    alumno = SimpleNamespace(id=999, tenant_id=TENANT_ID)
    sesion = _SesionFalsa()     # sin plan del pase y sin plan vigente del alumno

    beneficio = svc.crear(sesion, alumno, svc.TIPO_CLASES_GRATIS, CLASES, ahora=T0)

    plan = sesion.nuevos[0]
    assert isinstance(plan, Plan)
    assert plan.nombre == svc.NOMBRE_PLAN_PASE
    assert (plan.precio_clp, plan.creditos) == (0, CLASES), \
        "el plan del pase es gratis y nace con las clases que este regalo entrega"
    assert (plan.es_comercial, plan.activo) == (False, False), \
        "no es una membresía (corrección A) y no se vende (corrección C)"
    assert (plan.es_ilimitado, plan.duracion_dias) == (False, svc.DIAS_VIGENCIA)
    # El lock del box se toma antes de crear: es lo que hace idempotente al "si no existe, créalo".
    assert ("lock_box",) in sesion.eventos

    pase = sesion.nuevos[1]
    assert isinstance(pase, Suscripcion)
    assert beneficio.plan_id == plan.id and beneficio.suscripcion_id == pase.id
    pasos = [e[0] for e in sesion.eventos
             if e[0] in ("add", "flush", "vencer", "commit", "refresh")]
    assert pasos == ["add", "flush", "add", "flush", "vencer", "add", "commit", "refresh"], \
        "el plan, el pase y el alta van en UNA transacción (los dos `add`+`flush` son plan y pase)"
    assert pasos.count("commit") == 1


def test_a9_usar_y_anular_no_se_repiten_ni_revierten_lo_usado():
    """Reglas 5 y 7: se usa/anula UNA vez, y sólo lo que sigue vivo."""
    descuento = _beneficio(EstadoBeneficio.ofrecido, T0 + timedelta(days=1),
                           tipo=TipoBeneficio.descuento, valor=20)
    # Un descuento necesita el precio de lista: sin él no se marca usado (y no se toca la BD).
    with pytest.raises(svc.ValorInvalido):
        svc.usar(None, descuento, ahora=T0)

    # Lo que ya no está vivo no se usa ni se anula (`db=None`: falla antes de consultar la base).
    for estado in (EstadoBeneficio.usado, EstadoBeneficio.vencido, EstadoBeneficio.anulado):
        with pytest.raises(svc.BeneficioNoVivo):
            svc.usar(None, _beneficio(estado, T0 + timedelta(days=1)), ahora=T0)
        with pytest.raises(svc.BeneficioNoVivo):
            svc.anular(None, _beneficio(estado, T0 + timedelta(days=1)), motivo="x", ahora=T0)
    with pytest.raises(svc.BeneficioNoVivo):
        svc.usar(None, None, ahora=T0)

    # La anulación necesita motivo: una fila sin explicación no se puede auditar después.
    for vacio in ("", "   ", None):
        with pytest.raises(svc.ValorInvalido):
            svc.anular(None, _beneficio(EstadoBeneficio.ofrecido, T0 + timedelta(days=1)),
                       motivo=vacio, ahora=T0)

def test_a10_un_solo_regalo_vivo_por_alumno_y_tipo():
    """Regla 9 (decisión 3): si ya hay uno vivo, `crear()` no da de alta otro y dice valor y fecha."""
    alumno = SimpleNamespace(id=999, tenant_id=TENANT_ID)
    vivo = _beneficio(EstadoBeneficio.ofrecido, T0 + timedelta(days=5),
                      tipo=TipoBeneficio.descuento, valor=20)
    sesion = _SesionFalsa(vivos_hoy=[vivo], tope=TOPE_TEST)

    with pytest.raises(svc.BeneficioYaVigente) as err:
        svc.crear(sesion, alumno, svc.TIPO_DESCUENTO, 10, ahora=T0)

    # El texto es UNO solo (el 409 del router y el aviso del panel): dice el % y hasta cuándo.
    assert str(err.value) == "Ya tiene un descuento vigente del 20 % hasta el 04-10-2026."
    assert [e for e in sesion.eventos if e[0] in ("add", "commit")] == [], \
        "un alta rechazada no materializa nada (ni fila, ni créditos)"

    # Las clases dicen las clases (y el plural es del sustantivo, no del valor).
    vivo.tipo, vivo.valor = TipoBeneficio.clases_gratis, CLASES
    assert svc.aviso_vigente(vivo) == "Ya tiene un regalo de 3 clases vigente hasta el 04-10-2026."
    vivo.valor = 1
    assert svc.aviso_vigente(vivo) == "Ya tiene un regalo de 1 clase vigente hasta el 04-10-2026."
    # Una fila sin fecha no inventa una: el aviso dice menos, pero no miente.
    vivo.vigente_hasta = None
    assert svc.aviso_vigente(vivo) == "Ya tiene un regalo de 1 clase vigente."



# ══════════════════════════════════════════════════════════════════════════════
# B. Contra TEST (escribe y RESTAURA)
# ══════════════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def db():
    """Sesión contra la MISMA rama TEST que ve la API (falla cerrado)."""
    from app.core.config import is_test_db_url
    from app.db.database import SessionLocal

    if not is_test_db_url(settings.DATABASE_URL):
        pytest.fail("DATABASE_URL no es una rama de TEST: aborto por seguridad "
                    "(define ENVIRONMENT=test / revisa .env.test)")
    print("\n[OK] base de datos de TEST confirmada\n")
    sesion = SessionLocal()
    yield sesion
    sesion.close()


@pytest.fixture
def escenario(db):
    """Dos alumnos de prueba, el PLAN del pase (no comercial), un plan de pago y un correo real.

    El plan del pase se crea `activo=false` y `es_comercial=false` a propósito: un plan regalo no se
    vende y no cuenta como membresía (corrección A), pero el pase tiene que funcionar igual (el
    criterio de acceso NO es `planes.activo`, corrección C). El plan comercial es "el plan del
    alumno": con él vigente, las clases gratis se SUMAN a su suscripción (regla 3).
    """
    sufijo = f"{datetime.now():%Y%m%d%H%M%S%f}"
    ids = []
    plan_pase = plan_pago = notificacion = None
    try:
        for n in (1, 2):
            ids.append(db.execute(text("""
                INSERT INTO usuarios (tenant_id, rut, nombre, correo, password_hash, rol, activo,
                                      estado, created_at)
                VALUES (:t, :r, 'Alumno Beneficio TEST', :c, 'x', 'alumno', true, 'activo', :alta)
                RETURNING id"""),
                {"t": TENANT_ID, "r": f"9{n}{sufijo[-7:]}-{n}",
                 "c": f"beneficio{n}.{sufijo}@test.local",
                 "alta": datetime.combine(T0.date() - timedelta(days=120), T0.time(),
                                          tzinfo=SANTIAGO)}).scalar())
        plan_pase = db.execute(text("""
            INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, precio_clp,
                                duracion_dias, activo, es_comercial)
            VALUES (:t, :n, :cr, false, :p, 14, false, false) RETURNING id"""),
            {"t": TENANT_ID, "n": f"Pase de regreso TEST {sufijo}", "cr": CLASES,
             "p": PRECIO_PASE}).scalar()
        plan_pago = db.execute(text("""
            INSERT INTO planes (tenant_id, nombre, creditos, es_ilimitado, precio_clp,
                                duracion_dias, activo, es_comercial)
            VALUES (:t, :n, 10, false, 40000, 30, true, true) RETURNING id"""),
            {"t": TENANT_ID, "n": f"Plan mensual TEST {sufijo}"}).scalar()
        # El correo que origina el beneficio existe de verdad (es una FK): como en el envío real.
        notificacion = db.execute(text("""
            INSERT INTO notificaciones_enviadas (alumno_id, tenant_id, tipo, estado, fecha_envio)
            VALUES (:a, :t, 'inactividad', 'enviado', :f) RETURNING id"""),
            {"a": ids[0], "t": TENANT_ID, "f": T0}).scalar()
        db.commit()
    except Exception:
        db.rollback()
        raise

    alumnos = {i: db.query(Usuario).filter(Usuario.id == i).first() for i in ids}
    yield {"db": db, "alumno": alumnos[ids[0]], "otro": alumnos[ids[1]],
           "alumno_id": ids[0], "otro_id": ids[1], "plan_id": plan_pase,
           "plan_pago_id": plan_pago, "notificacion_id": notificacion}

    # ── limpieza (siempre, aunque el test falle) ──
    db.rollback()
    try:
        for i in ids:
            db.execute(text("DELETE FROM beneficios WHERE alumno_id = :a"), {"a": i})
            db.execute(text("DELETE FROM suscripciones WHERE usuario_id = :a"), {"a": i})
        if notificacion is not None:
            db.execute(text("DELETE FROM notificaciones_enviadas WHERE id = :n"),
                       {"n": notificacion})
        for i in ids:
            db.execute(text("DELETE FROM usuarios WHERE id = :a"), {"a": i})
        for p in (plan_pase, plan_pago):
            if p is not None:
                db.execute(text("DELETE FROM planes WHERE id = :p"), {"p": p})
        db.commit()
    except Exception as e:      # el borrado no debe tapar el fallo real del test
        db.rollback()
        print(f"\n[WARN] no se pudo limpiar el escenario de beneficios: {e}")


def _estado_en_la_base(db, beneficio_id):
    """El estado tal como quedó en Postgres (`::text`): lee el enum NATIVO, no la copia del ORM."""
    return db.execute(text("SELECT estado::text FROM beneficios WHERE id = :i"),
                      {"i": beneficio_id}).scalar()


def _columna(db, beneficio_id, columna):
    return db.execute(text(f"SELECT {columna} FROM beneficios WHERE id = :i"),
                      {"i": beneficio_id}).scalar()


def _suscripcion(db, alumno_id, plan_id, creditos, dias=30, fin=None):
    """Una suscripción vigente hecha a mano: "el plan que el alumno YA tenía".

    `fin` permite fijar el instante de vencimiento exacto (para probar el borde del último día);
    por defecto vence a los `dias` días de `T0`.
    """
    sid = db.execute(text("""
        INSERT INTO suscripciones (tenant_id, usuario_id, plan_id, estado, creditos_totales,
                                   creditos_disponibles, fecha_inicio, fecha_expiracion,
                                   created_at, updated_at)
        VALUES (:t, :u, :p, CAST('activo' AS estado_suscripcion), :c, :c, :ini, :fin, :ini, :ini)
        RETURNING id"""),
        {"t": TENANT_ID, "u": alumno_id, "p": plan_id, "c": creditos, "ini": T0,
         "fin": fin or (T0 + timedelta(days=dias))}).scalar()
    db.commit()
    return sid


def _creditos(db, suscripcion_id):
    return db.execute(text("SELECT creditos_disponibles FROM suscripciones WHERE id = :i"),
                      {"i": suscripcion_id}).scalar()

def test_b1_la_correccion_b_vence_los_vencidos_en_la_misma_transaccion(escenario):
    """Un beneficio con la ventana pasada se lee `vencido` apenas se da de alta el nuevo."""
    db, alumno, correo = escenario["db"], escenario["alumno"], escenario["notificacion_id"]
    valor = _valor_descuento(db)

    viejo = svc.crear(db, alumno, svc.TIPO_DESCUENTO, valor, notificacion_id=correo, ahora=T0)
    # La ventana del viejo se mueve al pasado (no se puede "ofrecer" uno ya vencido): queda el caso
    # exacto de la corrección B — un beneficio que venció sin que nadie lo usara.
    db.execute(text("UPDATE beneficios SET vigente_hasta = :v WHERE id = :i"),
               {"v": T0 - timedelta(hours=1), "i": viejo.id})
    db.commit()
    assert _estado_en_la_base(db, viejo.id) == "ofrecido"

    # El alta del nuevo lo vence EN LA MISMA transacción (sin llamar a nada más: si la expiración
    # dependiera de un job, acá se verían los dos regalos vivos).
    nuevo = svc.crear(db, alumno, svc.TIPO_DESCUENTO, valor, notificacion_id=correo, ahora=T0)

    assert _estado_en_la_base(db, viejo.id) == "vencido", \
        "quedaron dos regalos vivos: el alumno podría usarlos dos veces"
    assert _columna(db, viejo.id, "vencido_en") is not None, "el vencimiento queda fechado"
    assert _estado_en_la_base(db, nuevo.id) == "ofrecido"
    # Y la lectura coincide: sólo el nuevo queda vivo.
    referencia = T0 + timedelta(minutes=5)
    assert [b.id for b in svc.vivos(db, alumno.id, ahora=referencia)] == [nuevo.id]
    assert svc.vigente(db, alumno.id, ahora=referencia).id == nuevo.id


def test_b2_el_vencimiento_es_de_ese_alumno_y_de_ese_tipo(escenario):
    """El `WHERE` de la corrección B no se lleva por delante a otro alumno ni a otro tipo."""
    db, correo = escenario["db"], escenario["notificacion_id"]
    alumno, otro = escenario["alumno"], escenario["otro"]
    valor = _valor_descuento(db)

    # El regalo vencido de OTRO alumno.
    ajeno = svc.crear(db, otro, svc.TIPO_DESCUENTO, valor, notificacion_id=correo, ahora=T0)
    db.execute(text("UPDATE beneficios SET vigente_hasta = :v WHERE id = :i"),
               {"v": T0 - timedelta(hours=1), "i": ajeno.id})
    # Y una fila de OTRO tipo y vencida, para el mismo alumno (como dejaría una versión vieja).
    otro_tipo = db.execute(text("""
        INSERT INTO beneficios (tenant_id, alumno_id, tipo, estado, valor, vigente_hasta,
                                notificacion_id)
        VALUES (:t, :a, CAST('clases_gratis' AS tipo_beneficio),
                CAST('ofrecido' AS estado_beneficio), 2, :v, :n)
        RETURNING id"""),
        {"t": TENANT_ID, "a": alumno.id, "v": T0 - timedelta(days=1), "n": correo}).scalar()
    db.commit()

    svc.crear(db, alumno, svc.TIPO_DESCUENTO, valor, notificacion_id=correo,
              ahora=T0 + timedelta(minutes=1))

    assert _estado_en_la_base(db, ajeno.id) == "ofrecido", \
        "el vencimiento es por alumno: el regalo de otro alumno no se toca"
    assert _estado_en_la_base(db, otro_tipo) == "ofrecido", \
        "el vencimiento es por tipo: el regalo de otro tipo no se toca"
    # Esas filas siguen `ofrecido`, pero la LECTURA no las da por vivas: la regla 1 es una sola.
    referencia = T0 + timedelta(minutes=5)
    assert not svc.esta_vivo(db.get(Beneficio, ajeno.id), ahora=referencia)
    assert not svc.esta_vivo(db.get(Beneficio, otro_tipo), ahora=referencia)
    assert svc.vivos(db, otro.id, ahora=referencia) == []

def test_b3_sin_plan_vigente_el_pase_se_abre_al_enviar_el_correo(escenario):
    """Regla 3: sin plan vigente, el regalo se materializa como el pase — al enviarlo."""
    db, alumno = escenario["db"], escenario["alumno"]
    beneficio = svc.crear(db, alumno, svc.TIPO_CLASES_GRATIS, CLASES,
                          notificacion_id=escenario["notificacion_id"],
                          plan_id=escenario["plan_id"], ahora=T0)

    assert _estado_en_la_base(db, beneficio.id) == "ofrecido"
    assert _columna(db, beneficio.id, "valor") == CLASES
    assert _columna(db, beneficio.id, "notificacion_id") == escenario["notificacion_id"], \
        "el beneficio queda ligado al correo que lo mandó (métricas de la F4)"
    assert _columna(db, beneficio.id, "descuento_clp") is None, "un pase no descuenta pesos"
    # El pase: la suscripción del plan NO comercial, con las clases regaladas y la ventana exacta.
    sub = db.execute(text("""
        SELECT id, estado::text, creditos_totales, creditos_disponibles, fecha_expiracion, plan_id
        FROM suscripciones WHERE id = :i"""),
        {"i": beneficio.suscripcion_id}).mappings().one()
    assert sub["estado"] == "activo"
    assert (sub["creditos_totales"], sub["creditos_disponibles"]) == (CLASES, CLASES)
    assert _instante(sub["fecha_expiracion"]) == _instante(T0 + timedelta(days=svc.DIAS_VIGENCIA))
    assert sub["plan_id"] == escenario["plan_id"]
    # Y el plan del pase sigue fuera de las métricas (corrección A).
    assert db.execute(text("SELECT es_comercial FROM planes WHERE id = :p"),
                      {"p": escenario["plan_id"]}).scalar() is False
    # Una sola definición de la ventana: el beneficio vive hasta la misma fecha que su pase.
    assert svc.esta_vivo(beneficio, ahora=T0 + timedelta(days=14))
    assert not svc.esta_vivo(beneficio, ahora=T0 + timedelta(days=15))


def test_b4_con_plan_vigente_las_clases_se_suman_a_su_plan(escenario):
    """Regla 3: si el alumno ya paga un plan, el regalo son créditos extra — no una segunda sub."""
    db, alumno = escenario["db"], escenario["alumno"]
    sub_id = _suscripcion(db, alumno.id, escenario["plan_pago_id"], creditos=10)

    beneficio = svc.crear(db, alumno, svc.TIPO_CLASES_GRATIS, 5,
                          notificacion_id=escenario["notificacion_id"], ahora=T0)

    assert db.execute(text("SELECT count(*) FROM suscripciones WHERE usuario_id = :a"),
                      {"a": alumno.id}).scalar() == 1, \
        "no se abre un pase a quien ya tiene plan: las clases van a ESA suscripción"
    assert beneficio.suscripcion_id == sub_id
    assert beneficio.plan_id == escenario["plan_pago_id"]
    assert _creditos(db, sub_id) == 15
    assert db.execute(text("SELECT creditos_totales FROM suscripciones WHERE id = :i"),
                      {"i": sub_id}).scalar() == 15
    assert db.execute(text("SELECT estado::text FROM suscripciones WHERE id = :i"),
                      {"i": sub_id}).scalar() == "activo", \
        "la membresía del alumno no se toca: sólo se le suman clases"


def test_b4b_un_plan_que_vence_hoy_sigue_vigente_todo_el_dia(escenario):
    """Regla E: el plan vale hasta las 23:59:59 de su ÚLTIMO día, hora de Chile.

    El instante de vencimiento de este plan ya pasó (06:00 de Chile) pero el DÍA es hoy: con la
    comparación por instante (`fecha_expiracion > ahora`) `plan_vigente()` no lo veía, así que el
    regalo le abría un PASE a un alumno que todavía tiene plan hoy (y en el pase los créditos se
    fugarían de la membresía que está pagando).
    """
    db, alumno = escenario["db"], escenario["alumno"]
    sub_id = _suscripcion(db, alumno.id, escenario["plan_pago_id"], creditos=10,
                          fin=T0.replace(hour=6, minute=0))

    beneficio = svc.crear(db, alumno, svc.TIPO_CLASES_GRATIS, CLASES, ahora=T0)

    assert beneficio.suscripcion_id == sub_id, "el plan de HOY está vigente hasta las 23:59 CLT"
    assert beneficio.plan_id == escenario["plan_pago_id"]
    assert _creditos(db, sub_id) == 10 + CLASES
    assert db.execute(text("SELECT count(*) FROM suscripciones WHERE usuario_id = :a"),
                      {"a": alumno.id}).scalar() == 1, "no se abre un pase teniendo plan hoy"


def test_b5_un_plan_ilimitado_no_se_convierte_en_limitado(escenario):
    """`NULL` = ilimitado: sumarle clases no puede dejarlo con un tope contable."""
    db, alumno = escenario["db"], escenario["alumno"]
    sub_id = _suscripcion(db, alumno.id, escenario["plan_pago_id"], creditos=None)

    beneficio = svc.crear(db, alumno, svc.TIPO_CLASES_GRATIS, CLASES,
                          notificacion_id=escenario["notificacion_id"], ahora=T0)

    assert beneficio.suscripcion_id == sub_id
    fila = db.execute(text("SELECT creditos_totales, creditos_disponibles FROM suscripciones "
                           "WHERE id = :i"), {"i": sub_id}).mappings().one()
    assert fila["creditos_disponibles"] is None and fila["creditos_totales"] is None, \
        "un plan ilimitado no se vuelve limitado por un regalo"

def test_b6_el_descuento_se_calcula_al_usarlo_no_al_ofrecerlo(escenario):
    """Regla 6: al ofrecer no hay precio ni plan; el descuento en pesos se calcula al usarlo."""
    db, alumno, correo = escenario["db"], escenario["alumno"], escenario["notificacion_id"]
    valor = _valor_descuento(db)
    beneficio = svc.crear(db, alumno, svc.TIPO_DESCUENTO, valor, notificacion_id=correo, ahora=T0)

    assert _columna(db, beneficio.id, "descuento_clp") is None, "todavía no se usó"
    assert _columna(db, beneficio.id, "suscripcion_id") is None, \
        "un descuento no materializa acceso: se aplica al próximo plan"
    assert _columna(db, beneficio.id, "plan_id") is None, "ese plan lo compra el alumno después"

    precio_lista = 40000
    svc.usar(db, beneficio, precio_lista_clp=precio_lista, ahora=T0 + timedelta(days=2))
    esperado = round(precio_lista * valor / 100)

    assert _estado_en_la_base(db, beneficio.id) == "usado"
    assert _columna(db, beneficio.id, "descuento_clp") == esperado
    assert _columna(db, beneficio.id, "usado_en") is not None
    # El mismo desglose es el que se guarda en la solicitud (el snapshot de ESA compra).
    assert svc.desglose(SimpleNamespace(tipo=TipoBeneficio.descuento, valor=valor),
                        precio_lista) == {
        "precio_lista_clp": precio_lista, "descuento_pct": valor,
        "descuento_clp": esperado, "precio_final_clp": precio_lista - esperado}
    # Y un descuento se usa UNA sola vez.
    with pytest.raises(svc.BeneficioNoVivo):
        svc.usar(db, beneficio, precio_lista_clp=precio_lista, ahora=T0 + timedelta(days=3))


def test_b7_el_uso_es_una_sola_vez_y_la_ventana_cruzada_no_se_usa(escenario):
    """Regla 5: consumir la 1ª clase marca `usado`; lo vencido no se usa y deja de decir `ofrecido`."""
    db, alumno, correo = escenario["db"], escenario["alumno"], escenario["notificacion_id"]

    pase = svc.crear(db, alumno, svc.TIPO_CLASES_GRATIS, CLASES, notificacion_id=correo,
                     plan_id=escenario["plan_id"], ahora=T0)
    svc.usar(db, pase, ahora=T0 + timedelta(days=1))
    assert _estado_en_la_base(db, pase.id) == "usado"
    assert _columna(db, pase.id, "usado_en") is not None
    # Los créditos NO los mueve el servicio: el regalo no se gasta por marcarlo usado.
    assert _creditos(db, pase.suscripcion_id) == CLASES, \
        "cada clase la descuenta la reserva; acá sólo se marca que el regalo sirvió"
    with pytest.raises(svc.BeneficioNoVivo):
        svc.usar(db, pase, ahora=T0 + timedelta(days=2))

    # Un descuento con la ventana cruzada no se usa Y la fila deja de mentir.
    cruzado = svc.crear(db, alumno, svc.TIPO_DESCUENTO, _valor_descuento(db),
                        notificacion_id=correo, ahora=T0)
    with pytest.raises(svc.BeneficioNoVivo):
        svc.usar(db, cruzado, precio_lista_clp=10000,
                 ahora=T0 + timedelta(days=svc.DIAS_VIGENCIA))

    assert _estado_en_la_base(db, cruzado.id) == "vencido"
    assert _columna(db, cruzado.id, "vencido_en") is not None
    assert _columna(db, cruzado.id, "descuento_clp") is None, \
        "un descuento que no se usó no descuenta nada"
    assert svc.vivos(db, alumno.id, ahora=T0 + timedelta(days=svc.DIAS_VIGENCIA)) == []

def test_b8_la_anulacion_revoca_el_pase_y_queda_auditada(escenario):
    """Regla 7: el admin anula → el pase deja de dar acceso y la fila dice quién/cuándo/por qué."""
    db, alumno, correo = escenario["db"], escenario["alumno"], escenario["notificacion_id"]
    pase = svc.crear(db, alumno, svc.TIPO_CLASES_GRATIS, CLASES, notificacion_id=correo,
                     plan_id=escenario["plan_id"], ahora=T0)

    svc.anular(db, pase, motivo="Se lo mandamos al alumno equivocado",
               ahora=T0 + timedelta(hours=3))

    assert _estado_en_la_base(db, pase.id) == "anulado"
    assert _columna(db, pase.id, "anulado_at") is not None
    assert _columna(db, pase.id, "anulado_motivo") == "Se lo mandamos al alumno equivocado"
    # La revocación: sin créditos y con la suscripción vencida, no queda un acceso "fantasma".
    fila = db.execute(text("SELECT estado::text, creditos_disponibles FROM suscripciones "
                           "WHERE id = :i"), {"i": pase.suscripcion_id}).mappings().one()
    assert fila["creditos_disponibles"] == 0
    assert fila["estado"] == "vencido", "un regalo anulado no puede seguir dando acceso"
    assert svc.vivos(db, alumno.id, ahora=T0 + timedelta(hours=4)) == []
    # Y no se anula dos veces.
    with pytest.raises(svc.BeneficioNoVivo):
        svc.anular(db, pase, motivo="otra vez", ahora=T0 + timedelta(hours=5))


def test_b9_anular_las_clases_extra_no_toca_la_membresia_del_alumno(escenario):
    """La anulación devuelve lo que QUEDE del regalo; el plan que el alumno paga queda intacto."""
    db, alumno, correo = escenario["db"], escenario["alumno"], escenario["notificacion_id"]
    sub_id = _suscripcion(db, alumno.id, escenario["plan_pago_id"], creditos=10)
    beneficio = svc.crear(db, alumno, svc.TIPO_CLASES_GRATIS, CLASES, notificacion_id=correo,
                          ahora=T0)
    # El alumno ya consumió una clase (la descuenta la reserva: acá se simula ese movimiento).
    db.execute(text("UPDATE suscripciones SET creditos_disponibles = 12 WHERE id = :i"),
               {"i": sub_id})
    db.commit()

    svc.anular(db, beneficio, motivo="Se cargó dos veces", ahora=T0 + timedelta(days=1))

    assert _creditos(db, sub_id) == 9, "se descuenta lo que quedaba del regalo (12 - 3)"
    assert db.execute(text("SELECT estado::text FROM suscripciones WHERE id = :i"),
                      {"i": sub_id}).scalar() == "activo", \
        "su membresía (pagada) no se vence por un regalo"
    assert db.execute(text("SELECT count(*) FROM suscripciones WHERE usuario_id = :a"),
                      {"a": alumno.id}).scalar() == 1

def test_b10_la_base_quedo_como_el_diseno(db):
    """El esquema de la 038: dos enums nativos, las columnas del beneficio y los snapshots."""
    labels = dict(db.execute(text("""
        SELECT t.typname, array_agg(e.enumlabel ORDER BY e.enumsortorder)
        FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid
        WHERE t.typname IN ('estado_beneficio', 'tipo_beneficio')
        GROUP BY t.typname""")).all())
    assert labels["estado_beneficio"] == ["ofrecido", "usado", "vencido", "anulado"]
    assert labels["tipo_beneficio"] == ["descuento", "clases_gratis"]

    columnas = set(db.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'beneficios'""")).scalars())
    assert {"valor", "vigente_hasta", "plan_id", "suscripcion_id", "descuento_clp",
            "notificacion_id", "usado_en", "vencido_en",
            "anulado_por", "anulado_at", "anulado_motivo"} <= columnas
    assert "aceptado_en" not in columnas, "no hay paso de aceptación"

    # El tope del % es configuración del box, y el snapshot del descuento vive en la solicitud.
    assert db.execute(text("""
        SELECT count(*) FROM information_schema.columns
        WHERE table_name = 'configuracion_negocio'
          AND column_name = 'beneficio_descuento_max_pct'""")).scalar() == 1
    assert db.execute(text("""
        SELECT column_default FROM information_schema.columns
        WHERE table_name = 'configuracion_negocio'
          AND column_name = 'beneficio_descuento_max_pct'""")).scalar().startswith("50")
    solicitud = set(db.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'solicitudes_planes'""")).scalars())
    assert {"precio_clp_snapshot", "beneficio_id", "descuento_pct", "precio_final_clp"} <= solicitud


def test_b11_el_tope_lo_decide_el_box(escenario):
    """El % se topea con la configuración del box: 25 sobre un tope de 20 no se regala."""
    db, alumno, correo = escenario["db"], escenario["alumno"], escenario["notificacion_id"]
    previo = db.execute(text("SELECT beneficio_descuento_max_pct FROM configuracion_negocio "
                             "WHERE tenant_id = :t"), {"t": TENANT_ID}).scalar()
    crear_fila = previo is None
    try:
        db.execute(text("""
            INSERT INTO configuracion_negocio (tenant_id, beneficio_descuento_max_pct)
            VALUES (:t, :v)
            ON CONFLICT (tenant_id) DO UPDATE SET beneficio_descuento_max_pct = :v"""),
            {"t": TENANT_ID, "v": TOPE_TEST})
        db.commit()

        assert svc.tope_descuento(db, TENANT_ID) == TOPE_TEST
        with pytest.raises(svc.DescuentoSobreTope):
            svc.crear(db, alumno, svc.TIPO_DESCUENTO, TOPE_TEST + 5, notificacion_id=correo,
                      ahora=T0)
        assert db.execute(text("SELECT count(*) FROM beneficios WHERE alumno_id = :a"),
                          {"a": alumno.id}).scalar() == 0, "no puede quedar un alta a medias"

        justo = svc.crear(db, alumno, svc.TIPO_DESCUENTO, TOPE_TEST, notificacion_id=correo,
                          ahora=T0)
        assert justo.valor == TOPE_TEST
    finally:
        if crear_fila:
            db.execute(text("DELETE FROM configuracion_negocio WHERE tenant_id = :t"),
                       {"t": TENANT_ID})
        else:
            db.execute(text("UPDATE configuracion_negocio SET beneficio_descuento_max_pct = :v "
                            "WHERE tenant_id = :t"), {"v": previo, "t": TENANT_ID})
        db.commit()



def test_b12_no_se_da_un_segundo_beneficio_del_mismo_tipo_si_hay_uno_vivo(escenario):
    """Decisión 3: con un regalo vivo de ese tipo, el segundo se rechaza (409) y no toca la base."""
    db, alumno = escenario["db"], escenario["alumno"]
    valor = _valor_descuento(db)
    primero = svc.crear(db, alumno, svc.TIPO_DESCUENTO, valor, ahora=T0)

    with pytest.raises(svc.BeneficioYaVigente) as err:
        svc.crear(db, alumno, svc.TIPO_DESCUENTO, valor, ahora=T0 + timedelta(days=1))

    assert str(err.value) == f"Ya tiene un descuento vigente del {valor} % hasta el 14-10-2026."
    # El rechazo no dejó una fila a medias: sigue habiendo UN solo regalo — el primero.
    assert db.execute(text("SELECT count(*) FROM beneficios WHERE alumno_id = :a"),
                      {"a": alumno.id}).scalar() == 1
    assert svc.vigente(db, alumno.id, ahora=T0 + timedelta(days=1)).id == primero.id

    # Otro TIPO sí convive (la regla es por tipo): un % y un pase a la vez es legítimo.
    pase = svc.crear(db, alumno, svc.TIPO_CLASES_GRATIS, CLASES, plan_id=escenario["plan_id"],
                     ahora=T0 + timedelta(days=1))
    assert _estado_en_la_base(db, pase.id) == "ofrecido"
    vivos = svc.vivos(db, alumno.id, ahora=T0 + timedelta(days=2))
    assert sorted(b.tipo.value for b in vivos) == ["clases_gratis", "descuento"]

    # Y cuando el primero se usa, el tipo queda libre otra vez.
    svc.usar(db, primero, precio_lista_clp=30000, ahora=T0 + timedelta(days=2))
    assert _estado_en_la_base(db, primero.id) == "usado"
    nuevo = svc.crear(db, alumno, svc.TIPO_DESCUENTO, valor, ahora=T0 + timedelta(days=2))
    assert _estado_en_la_base(db, nuevo.id) == "ofrecido"


def test_b13_las_clases_extra_caducan_con_el_plan_que_las_lleva(escenario):
    """Regla 3: los créditos van al plan del alumno, así que el regalo vence CON ÉL, no a los 15 días."""
    db, alumno = escenario["db"], escenario["alumno"]
    # Un plan que vence ANTES de la ventana (el mensual vence el último día del mes).
    sub_id = _suscripcion(db, alumno.id, escenario["plan_pago_id"], creditos=10, dias=3)

    beneficio = svc.crear(db, alumno, svc.TIPO_CLASES_GRATIS, CLASES, ahora=T0)

    # Las clases SÍ se entregaron (se sumaron al plan); lo que caduca con el plan es el acceso.
    # El recorte es al FIN DEL ÚLTIMO DÍA del plan (23:59:59 hora de Chile): los créditos del plan
    # sirven hasta ahí, no hasta el reloj crudo de la fila (regla E, 29/09/2026).
    assert _creditos(db, sub_id) == 10 + CLASES
    assert _instante(beneficio.vigente_hasta) == _instante(
        fin_del_dia_chile(T0.date() + timedelta(days=3))), \
        "la ventana no puede prometer más días que el plan que lleva los créditos"
    assert svc.esta_vivo(beneficio, ahora=T0 + timedelta(days=2))
    assert not svc.esta_vivo(beneficio, ahora=T0 + timedelta(days=4)), \
        "con el plan vencido los créditos se fueron con él"
    # Y como la ventana quedó recortada, la corrección B lo vence apenas vence el plan.
    assert svc.vencer_vencidos(db, alumno_id=alumno.id, tipo=svc.TIPO_CLASES_GRATIS,
                               ahora=T0 + timedelta(days=4)) == 1
    db.commit()
    assert _estado_en_la_base(db, beneficio.id) == "vencido"

    # El pase, en cambio, dura EXACTAMENTE la ventana: no hay plan que lo recorte.
    db.execute(text("DELETE FROM suscripciones WHERE usuario_id = :a"), {"a": alumno.id})
    db.commit()
    pase = svc.crear(db, alumno, svc.TIPO_CLASES_GRATIS, CLASES, plan_id=escenario["plan_id"],
                     ahora=T0)
    assert _instante(pase.vigente_hasta) == _instante(T0 + timedelta(days=svc.DIAS_VIGENCIA))


def test_b14_un_beneficio_sin_correo_es_valido(escenario):
    """Ajuste del paso 2: `notificacion_id` es opcional — se puede regalar sin avisar por correo."""
    db, alumno = escenario["db"], escenario["alumno"]

    beneficio = svc.crear(db, alumno, svc.TIPO_DESCUENTO, _valor_descuento(db), ahora=T0)

    assert _columna(db, beneficio.id, "notificacion_id") is None
    assert _estado_en_la_base(db, beneficio.id) == "ofrecido", "sin correo el regalo vale igual"
    assert svc.vigente(db, alumno.id, ahora=T0).id == beneficio.id
    # Y se usa como cualquier otro: el correo sirve para medir la gestión, no para usar el regalo.
    svc.usar(db, beneficio, precio_lista_clp=30000, ahora=T0 + timedelta(days=1))
    assert _estado_en_la_base(db, beneficio.id) == "usado"
