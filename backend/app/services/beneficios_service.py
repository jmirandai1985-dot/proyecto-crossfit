"""Beneficios del alumno (Fase 2 de Fidelización): UNA definición de su ciclo de vida.

Qué resuelve
------------
Un beneficio es un regalo que el box le manda a un alumno para traerlo de vuelta: clases gratis (el
"Pase de regreso") o un descuento en su próximo plan. Normalmente nace de un correo (`notificacion_id`
liga el regalo al envío, que es lo que la F4 mide), pero **el correo NO es obligatorio**: el panel
puede regalar sin avisar por correo. **No hay paso de aceptación**, el acceso se materializa al
darlo. Sin una tabla propia no hay forma de saber qué se regaló, quién lo usó ni si sirvió, que es
exactamente lo que mide la F4.

Reglas (una definición por criterio)
------------------------------------
1. **Estado y ventana se miran JUNTOS** (`esta_vivo`): un `ofrecido` con `vigente_hasta` pasado NO
   está vivo, aunque la fila siga diciendo `ofrecido`. Es la única definición de "este beneficio se
   puede usar hoy", y la usan la lectura, el uso y la anulación.
2. **La ventana son 15 días desde el alta** (`DIAS_VIGENCIA`) — el día del envío del correo, cuando lo
   hay — y el % lo topea el BOX (`configuracion_negocio.beneficio_descuento_max_pct`, default 50):
   quien ofrece no elige ni la duración ni el máximo, así que no puede regalar un pase eterno ni un
   100% por error.
3. **El acceso se materializa AL DARLO** (`crear`), no al aceptar: con un plan vigente COMERCIAL las
   clases se SUMAN a ese plan — y **caducan CON ÉL** (un plan mensual vence el último día del mes,
   `suscripciones.fecha_expiracion`), así que la ventana se RECORTA a lo que le quede al plan: los
   créditos viven en esa suscripción y el regalo no puede prometer más días que el acceso que los
   lleva. Sin plan vigente se abre el pase (una suscripción gratuita del plan no comercial, que dura
   EXACTAMENTE la ventana). Un descuento no materializa nada: se aplica al próximo plan que compre el
   alumno.
4. **Corrección B: al crear un beneficio se vencen antes los vencidos — en la MISMA transacción.**
   `crear()` marca `vencido` todo `ofrecido` del mismo alumno/tipo con la ventana pasada, da de alta
   el nuevo y hace UN solo `commit()`. Si la expiración quedara para un job aparte, entre que el
   beneficio vence y que el job corre el alumno tendría DOS pases vivos y podría usarlos dos veces.
5. **`usar()` = consumió la 1ª clase (o usó el descuento).** Es la conversión que mide la F4 y ocurre
   UNA vez. Los créditos NO se mueven acá: cada clase la descuenta la reserva, que es la que sabe
   qué clase se tomó — acá sólo se marca que el regalo sirvió.
6. **El descuento se calcula AL USARLO** (`desglose`), sobre el precio de lista del plan que el alumno
   compró: al ofrecerlo no se sabe qué plan va a comprar. El snapshot de esa compra vive en
   `solicitudes_planes` (`beneficio_id`, `descuento_pct`, `precio_final_clp`).
7. **La anulación es del admin y REVOCA lo entregado** (`anular`): sólo se anula un beneficio que
   nadie usó — lo usado no se revierte (la clase ya se tomó; la historia de la gestión no se
   reescribe). Un `descuento` no tiene nada materializado que revocar.
8. **Ningún número de negocio se inventa acá**: la ventana, el tope y el precio de lista vienen de la
   configuración del box o entran como parámetro.
9. **Un solo regalo VIVO por alumno y tipo** (decisión 3): si el alumno ya tiene uno, `crear()` no da
   de alta otro — levanta `BeneficioYaVigente` con el texto de `aviso_vigente()` ("Ya tiene un
   descuento vigente del 20 % hasta el 12-10-2026"), que el router devuelve como 409 y que el panel
   muestra en la fila. Dos regalos del mismo tipo vigentes a la vez son el mismo regalo dos veces, y
   es justo lo que la corrección B evitaba dejar pasar. Otro TIPO sí puede convivir (un % y un pase).
"""
from datetime import datetime, timedelta, timezone
from typing import Final

from sqlalchemy.orm import Session

from app.core.estados import plan_comercial, vigente_hoy
from app.models.beneficio import Beneficio, EstadoBeneficio, TipoBeneficio
from app.models.configuracion import ConfiguracionNegocio
from app.models.plan import Plan
from app.models.suscripcion import EstadoSuscripcion, Suscripcion
from app.utils.santiago import ahora_santiago, fecha_chile, fin_del_dia_chile

# ── Reglas del box (una definición cada una) ──────────────────────────────────
# La ventana del regalo: 15 días desde el envío del correo. NO la fija quien ofrece.
DIAS_VIGENCIA: Final[int] = 15
# Tope del % cuando el box no lo configuró (o lo configuró imposible).
TOPE_DESCUENTO_DEFAULT: Final[int] = 50
# Las clases que se pueden regalar: el regalo es acotado, no "cualquier número".
CLASES_VALIDAS: Final[tuple] = (1, 2, 3, 5)

# ── El catálogo de regalos (una entrada por TIPO) ─────────────────────────────
# `id` es el label del enum `tipo_beneficio` y lo que agrupa la "tasa por beneficio" de la F4.
TIPO_DESCUENTO: Final[str] = TipoBeneficio.descuento.value
TIPO_CLASES_GRATIS: Final[str] = TipoBeneficio.clases_gratis.value

TIPOS: Final[tuple] = (
    {
        "id": TIPO_DESCUENTO,
        "label": "Descuento en su próximo plan",
        "descripcion": "El alumno paga menos en el próximo plan que compre (el % lo topea el box).",
        "unidad": "pct",        # `valor` es un porcentaje 1..tope del box
        "valores": None,        # cualquier entero dentro del tope
        "materializa": False,   # no da acceso: se descuenta al comprar el plan
    },
    {
        "id": TIPO_CLASES_GRATIS,
        "label": "Clases gratis",
        "descripcion": "Clases de regalo: se suman a su plan vigente, o se le abre un pase si no "
                       "tiene ninguno.",
        "unidad": "clases",     # `valor` es un número de clases
        "valores": CLASES_VALIDAS,
        "materializa": True,    # da acceso al enviar el correo
    },
)

TIPOS_VALIDOS: Final[tuple] = tuple(t["id"] for t in TIPOS)

class BeneficioError(ValueError):
    """Un beneficio no se puede crear/usar/anular como se pidió (el router lo traduce a 4xx)."""


class TipoDesconocido(BeneficioError):
    """El tipo no está en el catálogo de `tipo_beneficio`: no se inventa un regalo nuevo."""


class ValorInvalido(BeneficioError):
    """El `valor` del regalo no sirve (no es un entero positivo, o no es una cantidad permitida)."""


class DescuentoSobreTope(BeneficioError):
    """El descuento pide más de lo que el box autorizó regalar (`beneficio_descuento_max_pct`)."""


class BeneficioYaVigente(BeneficioError):
    """El alumno YA tiene un regalo vivo de ese tipo: no se le da otro (decisión 3).

    El router lo devuelve como **409 CONFLICT** con el texto de `aviso_vigente()` (el mismo que el
    panel muestra en la fila): dos regalos del mismo tipo vivos a la vez son el mismo regalo dos
    veces. Si el que ya tiene es de OTRO tipo, no hay conflicto.
    """


class BeneficioSinPlan(BeneficioError):
    """No hay plan con el que dar acceso: el alumno no tiene plan vigente y falta el del pase."""


class BeneficioNoVivo(BeneficioError):
    """El beneficio no está vivo: venció, ya se usó o lo anuló el admin (no se repite)."""


def _tipo(tipo) -> dict | None:
    """La entrada del catálogo con ese id, o `None` (una sola búsqueda para todo el módulo)."""
    for t in TIPOS:
        if t["id"] == tipo:
            return t
    return None


def tipo_valido(tipo) -> bool:
    """¿Este tipo existe en el catálogo? (un typo no puede entrar a la tabla)."""
    return _tipo(tipo) is not None


def etiqueta(tipo) -> str:
    """El label del catálogo para ese tipo (o el id crudo si es viejo/desconocido)."""
    entrada = _tipo(tipo)
    if entrada is None:
        return str(tipo)
    return entrada["label"]


def aviso_vigente(beneficio) -> str:
    """El texto del conflicto: el alumno YA tiene un regalo vivo de ese tipo (decisión 3).

    Es UN solo texto para los dos usos — el 409 que devuelve el router y lo que el panel muestra en
    la fila — y dice el VALOR y hasta CUÁNDO: "Ya tiene un descuento vigente del 20 % hasta el
    12-10-2026". Sin la fecha el admin no sabe si faltan días o minutos, y con dos textos distintos
    el error y el panel se contradicen.
    """
    if beneficio.tipo == TipoBeneficio.descuento:
        que = f"un descuento vigente del {beneficio.valor} %"
    else:
        # El plural es del sustantivo: "un regalo de 1 clase" / "un regalo de 3 clases".
        cuantas = f"{beneficio.valor} clase" + ("" if beneficio.valor == 1 else "s")
        que = f"un regalo de {cuantas} vigente"
    hasta = fecha_chile(beneficio.vigente_hasta)
    if hasta is None:
        # Una fila sin fecha no inventa una: mejor decir menos que mentir.
        return f"Ya tiene {que}."
    return f"Ya tiene {que} hasta el {hasta.strftime('%d-%m-%Y')}."


def _aware(momento: datetime | None) -> datetime | None:
    """Un instante CON zona: el que llega sin zona se asume UTC (las columnas son `timestamptz`).

    Mismo criterio que `app.utils.santiago.fecha_chile`: comparar un instante naive contra uno aware
    revienta con `TypeError`, y asumir la zona del servidor es peor que asumir UTC.
    """
    if momento is None:
        return None
    return momento if momento.tzinfo is not None else momento.replace(tzinfo=timezone.utc)


def _ahora(ahora: datetime | None = None) -> datetime:
    """El instante de referencia: el que se pase (tests) o el de Chile en este momento."""
    return _aware(ahora) if ahora is not None else ahora_santiago()


def esta_vivo(beneficio, ahora: datetime | None = None) -> bool:
    """¿Se puede usar HOY? Estado Y ventana, en una sola definición (regla 1).

    Es la única definición de "vivo": la lectura (`vivos`) la repite como `WHERE` y el test comprueba
    que las dos formas coinciden. Un beneficio ya usado, vencido o anulado NO está vivo: se usa una
    sola vez.
    """
    if beneficio is None or beneficio.estado != EstadoBeneficio.ofrecido:
        return False
    vence = _aware(beneficio.vigente_hasta)
    return vence is not None and vence > _ahora(ahora)


def _normalizar_tope(valor) -> int:
    """El tope de descuento del box, saneado: fuera de 1..100 NO se usa (nadie regala más del 100%).

    Un tope mal cargado (o un `NULL` de una fila vieja) no puede terminar en un descuento mayor al
    precio: en ese caso vale el default aprobado del diseño.
    """
    if isinstance(valor, bool) or not isinstance(valor, int):
        return TOPE_DESCUENTO_DEFAULT
    return valor if 1 <= valor <= 100 else TOPE_DESCUENTO_DEFAULT


def tope_descuento(db: Session, tenant_id: int) -> int:
    """Cuánto % autoriza este box (`configuracion_negocio`), saneado, con el default del diseño."""
    valor = db.query(ConfiguracionNegocio.beneficio_descuento_max_pct).filter(
        ConfiguracionNegocio.tenant_id == tenant_id
    ).scalar()
    return _normalizar_tope(valor)

def vivos(db: Session, alumno_id: int, *, tipo=None,
          ahora: datetime | None = None) -> list:
    """Los beneficios usables HOY (la MISMA regla que `esta_vivo`, escrita como `WHERE`).

    Ordenados por el que vence antes (el que hay que usar primero). La lectura NO escribe: al
    `ofrecido` con la ventana pasada lo vence `crear()` (corrección B), no un job.

    Es lo que mira el panel antes de mandar otro regalo: dos pases vivos son dos regalos usables.
    """
    consulta = db.query(Beneficio).filter(
        Beneficio.alumno_id == alumno_id,
        Beneficio.estado == EstadoBeneficio.ofrecido,
        Beneficio.vigente_hasta > _ahora(ahora),
    )
    if tipo is not None:
        consulta = consulta.filter(Beneficio.tipo == tipo)
    return consulta.order_by(Beneficio.vigente_hasta, Beneficio.id).all()


def vigente(db: Session, alumno_id: int, *, tipo=None,
            ahora: datetime | None = None) -> Beneficio | None:
    """El beneficio vivo que vence antes (o `None`): lo que el panel muestra como "ya tiene uno"."""
    vivos_hoy = vivos(db, alumno_id, tipo=tipo, ahora=ahora)
    return vivos_hoy[0] if vivos_hoy else None


def plan_vigente(db: Session, alumno, *, ahora: datetime | None = None) -> Suscripcion | None:
    """La suscripción vigente del alumno que ES una membresía (no un pase).

    `plan_comercial` es la MISMA definición que usan MRR, retención, churn y el ML (corrección A): un
    pase vigente NO cuenta como "tiene plan". Si contara, el box no podría regalarle clases nuevas a
    un alumno que sigue con el pase y el regalo no le daría nada.

    El orden de los créditos es el mismo de `POST /reservas`: el plan con más créditos disponibles
    (los `NULL` —ilimitado— al final, nunca elegidos antes que uno con créditos contables).
    """
    momento = _ahora(ahora)
    # El plan vale hasta las 23:59:59 de su último día (hora de Chile): se compara el DÍA, no el
    # instante — con `> momento` un plan que vence HOY dejaba de estar vigente a las 20:59 CLT y el
    # regalo abría un pase en vez de sumarle las clases al plan que el alumno ya tiene.
    return db.query(Suscripcion).join(
        Plan, Suscripcion.plan_id == Plan.id
    ).filter(
        Suscripcion.usuario_id == alumno.id,
        Suscripcion.tenant_id == alumno.tenant_id,
        Suscripcion.estado == EstadoSuscripcion.activo,
        vigente_hoy(Suscripcion.fecha_expiracion, hoy=fecha_chile(momento)),
        plan_comercial(Plan.es_comercial),
    ).order_by(
        Suscripcion.creditos_disponibles.desc().nulls_last(),
        Suscripcion.fecha_expiracion.desc(),
    ).first()


def vencer_vencidos(db: Session, *, alumno_id: int, tipo, ahora: datetime | None = None) -> int:
    """Corrección B: marca `vencido` todo `ofrecido` vencido de ESE alumno y ESE tipo.

    NO hace `commit()` a propósito: lo llama `crear()` dentro de SU transacción. Un commit acá
    volvería a abrir la ventana en la que el alumno tiene dos regalos vivos y puede usar los dos.

    Devuelve cuántas filas venció (lo usan los tests para comprobar el alcance del `WHERE`).
    """
    momento = _ahora(ahora)
    return db.query(Beneficio).filter(
        Beneficio.alumno_id == alumno_id,
        Beneficio.tipo == tipo,
        Beneficio.estado == EstadoBeneficio.ofrecido,
        Beneficio.vigente_hasta <= momento,
    ).update({"estado": EstadoBeneficio.vencido, "vencido_en": momento},
             synchronize_session=False)

def _exigir_valor(db: Session, alumno, entrada: dict, valor) -> int:
    """El `valor` según su unidad: entero positivo, cantidad permitida y dentro del tope del box.

    Se valida ANTES de materializar nada: un valor imposible no puede dejar un acceso a medio dar.
    """
    if isinstance(valor, bool) or not isinstance(valor, int) or valor <= 0:
        raise ValorInvalido(
            f"El valor del beneficio tiene que ser un entero positivo (llegó {valor!r}).")
    permitidos = entrada["valores"]
    if permitidos is not None and valor not in permitidos:
        raise ValorInvalido(
            f"`{entrada['id']}` sólo puede regalar "
            f"{'/'.join(str(v) for v in permitidos)} clases (llegó {valor}).")
    if entrada["unidad"] == "pct":
        tope = tope_descuento(db, alumno.tenant_id)
        if valor > tope:
            raise DescuentoSobreTope(
                f"Este box autoriza descuentos de hasta {tope}% "
                f"(`beneficio_descuento_max_pct`, llegó {valor}).")
    return valor


def _exigir_plan(db: Session, alumno, plan_id) -> Plan:
    """El plan del pase: sin él no hay acceso que darle a un alumno sin plan vigente.

    NO se filtra por `planes.activo`: un plan regalo se crea `activo = false` justamente para que no
    aparezca en el catálogo que compra el alumno — usarlo como criterio de acceso dejaría el pase
    inusable (el `activo=False` de la corrección C).
    """
    if plan_id is None:
        raise BeneficioSinPlan(
            "El alumno no tiene un plan vigente: hace falta el plan del pase (`plan_id`) para "
            "abrirle el acceso.")
    plan = db.query(Plan).filter(
        Plan.id == plan_id, Plan.tenant_id == alumno.tenant_id).first()
    if plan is None:
        raise BeneficioSinPlan(
            "Ese plan no existe en este box: no se puede regalar un plan de otro box.")
    return plan


def _vence_con_el_plan(vigente_hasta: datetime, suscripcion) -> datetime:
    """Recorta la ventana a lo que le quede al plan que lleva los créditos (regla 3).

    Un `clases_gratis` sumado al plan del alumno son créditos DE ESA suscripción: cuando el plan vence
    (un plan mensual vence el último día del mes a las 23:59:59) los créditos se van con él, así que la
    ventana de 15 días no puede prometer más días que el acceso. Con el pase no cambia nada: su
    `fecha_expiracion` ES la ventana que se acaba de calcular.

    ⚠️ El recorte es al FIN DEL ÚLTIMO DÍA del plan, hora de Chile (regla E, 29/09/2026): los
    créditos del plan sirven hasta las 23:59:59 de su último día, así que cortar la ventana en el
    reloj crudo de la fila (una fila legado guardada `23:59:59+00` es 20:59 CLT) dejaba al regalo sin
    las últimas horas que el alumno todavía tenía.
    """
    if suscripcion is None:
        return vigente_hasta
    vence_plan = _aware(getattr(suscripcion, "fecha_expiracion", None))
    if vence_plan is None:
        return vigente_hasta
    return min(vigente_hasta, fin_del_dia_chile(fecha_chile(vence_plan)))


def _materializar_acceso(db: Session, alumno, valor: int, vigente_hasta: datetime,
                         plan_id, momento: datetime):
    """Le da el acceso al alumno AHORA (al dar el regalo) y devuelve `(plan_id, suscripción)`.

    Con un plan vigente COMERCIAL las clases se le SUMAN a ESE plan: no se crea una segunda
    suscripción, porque el alumno ya tiene dónde usarlas. Si ese plan es ilimitado
    (`creditos_disponibles NULL`) no hay nada que sumar — y NO se lo convierte en limitado.

    Sin plan vigente se abre el PASE: una suscripción del plan no comercial que dura EXACTAMENTE la
    ventana del beneficio y nace `activo` (un acceso regalado es usable de inmediato; no hay pago que
    aprobar), con tantos créditos como clases se regalaron.
    """
    vigente_actual = plan_vigente(db, alumno, ahora=momento)
    if vigente_actual is not None:
        if vigente_actual.creditos_disponibles is not None:
            vigente_actual.creditos_disponibles += valor
            if vigente_actual.creditos_totales is not None:
                vigente_actual.creditos_totales += valor
        return vigente_actual.plan_id, vigente_actual

    plan = _exigir_plan(db, alumno, plan_id)
    suscripcion = Suscripcion(
        tenant_id=alumno.tenant_id,
        usuario_id=alumno.id,
        plan_id=plan.id,
        estado=EstadoSuscripcion.activo,
        creditos_totales=valor,
        creditos_disponibles=valor,
        fecha_inicio=momento,
        fecha_expiracion=vigente_hasta,     # la ventana ES la duración del pase
    )
    db.add(suscripcion)
    db.flush()      # el pase ya existe en esta transacción: el beneficio puede apuntarle
    return plan.id, suscripcion

def crear(db: Session, alumno, tipo, valor, *, notificacion_id=None, plan_id=None,
          ofrecido_por=None, ahora: datetime | None = None) -> Beneficio:
    """Da de alta el beneficio del alumno y MATERIALIZA su acceso — todo en UNA transacción.

    `notificacion_id` es OPCIONAL: si el regalo va con correo, la fila queda ligada al envío (que es
    lo que la F4 mide); si el panel lo da sin avisar por correo, el beneficio vale exactamente igual.
    La ventana NO se pide: son `DIAS_VIGENCIA` desde este instante, así nadie puede ofrecer un pase
    eterno — y se RECORTA si las clases se suman a un plan que vence antes (regla 3).

    `plan_id` es el plan del PASE y sólo hace falta cuando el alumno no tiene un plan vigente
    comercial (si tiene, las clases se le suman a ese plan) — regla 3.

    Decisión 3: si el alumno YA tiene un regalo vivo de ese tipo no se da de alta otro
    (`BeneficioYaVigente`: el router lo devuelve como 409). Corrección B: primero se vencen los
    `ofrecido` del mismo alumno/tipo que ya pasaron su ventana, después se da de alta el nuevo, y
    TODO dentro de UN solo `commit()`.
    """
    momento = _ahora(ahora)
    entrada = _tipo(tipo)
    if entrada is None:
        raise TipoDesconocido(
            f"Tipo de beneficio desconocido: `{tipo}`. Válidos: {', '.join(TIPOS_VALIDOS)}.")
    valor = _exigir_valor(db, alumno, entrada, valor)

    # Decisión 3: un solo regalo VIVO por alumno y tipo. Se mira ANTES de materializar nada, así un
    # rechazo no le deja al alumno créditos de más ni una fila a medias (el router lo devuelve 409).
    ya_vivo = vigente(db, alumno.id, tipo=entrada["id"], ahora=momento)
    if ya_vivo is not None:
        raise BeneficioYaVigente(aviso_vigente(ya_vivo))

    vigente_hasta = momento + timedelta(days=DIAS_VIGENCIA)
    plan_final = None
    suscripcion = None
    if entrada["materializa"]:
        plan_final, suscripcion = _materializar_acceso(
            db, alumno, valor, vigente_hasta, plan_id, momento)
        # Los créditos extra son de ESA suscripción: el regalo vence cuando vence el plan que los
        # lleva (regla 3), no 15 días después.
        vigente_hasta = _vence_con_el_plan(vigente_hasta, suscripcion)

    beneficio = Beneficio(
        tenant_id=alumno.tenant_id,
        alumno_id=alumno.id,
        tipo=TipoBeneficio(entrada["id"]),
        estado=EstadoBeneficio.ofrecido,
        valor=valor,
        vigente_hasta=vigente_hasta,
        plan_id=plan_final,
        suscripcion_id=(suscripcion.id if suscripcion is not None else None),
        notificacion_id=notificacion_id,
        ofrecido_por=ofrecido_por,
    )

    # Corrección B: el vencimiento de los vencidos va ACÁ, dentro de la misma transacción que el
    # alta (un `commit` entre los dos dejaría al alumno con dos regalos vivos a la vez).
    vencer_vencidos(db, alumno_id=alumno.id, tipo=entrada["id"], ahora=momento)
    db.add(beneficio)
    db.commit()
    db.refresh(beneficio)
    return beneficio


def desglose(beneficio, precio_lista_clp) -> dict:
    """La aritmética del descuento en UN lugar: % sobre el precio de LISTA → precio final.

    Devuelve el snapshot que se guarda en la solicitud (`solicitudes_planes`): el precio de lista, el
    % aplicado, el descuento en pesos y el precio final. Se calcula al USARLO, no al ofrecerlo: en ese
    momento todavía no se sabe qué plan va a comprar el alumno.
    """
    if isinstance(precio_lista_clp, bool) or not isinstance(precio_lista_clp, int) \
            or precio_lista_clp <= 0:
        raise ValorInvalido(
            f"El precio de lista tiene que ser un entero positivo (llegó {precio_lista_clp!r}).")
    if beneficio is None or beneficio.tipo != TipoBeneficio.descuento:
        raise ValorInvalido(
            "Sólo un beneficio de tipo `descuento` se aplica sobre el precio de un plan.")
    descuento = round(precio_lista_clp * beneficio.valor / 100)
    return {
        "precio_lista_clp": precio_lista_clp,
        "descuento_pct": beneficio.valor,
        "descuento_clp": descuento,
        "precio_final_clp": precio_lista_clp - descuento,
    }

def usar(db: Session, beneficio: Beneficio, *, precio_lista_clp=None,
         ahora: datetime | None = None) -> Beneficio:
    """`ofrecido → usado`: el alumno consumió la 1ª clase del regalo (o usó el descuento).

    Es la conversión que mide la F4, y ocurre UNA sola vez. Los créditos NO se mueven acá: cada clase
    la descuenta la reserva, que es la que sabe qué clase se tomó; esto sólo marca que el regalo
    sirvió.

    Un `descuento` necesita el precio de LISTA del plan que el alumno está comprando: el descuento se
    calcula en ese momento (`desglose`) y quien llama lo guarda en la solicitud, que es donde vive el
    snapshot de la compra.

    Si el beneficio ya no está vivo no se usa: se dice por qué y, si el motivo es que la ventana
    pasó, el `ofrecido` se marca `vencido` en el mismo movimiento (la lectura no miente: no queda una
    fila que parezca usable).
    """
    momento = _ahora(ahora)
    if not esta_vivo(beneficio, momento):
        if beneficio is not None and beneficio.estado == EstadoBeneficio.ofrecido:
            beneficio.estado = EstadoBeneficio.vencido
            beneficio.vencido_en = momento
            db.commit()
        raise BeneficioNoVivo(
            "Este beneficio ya no está vivo (pasó su ventana, ya se usó o lo anuló el "
            "admin): no se usa dos veces.")

    if beneficio.tipo == TipoBeneficio.descuento:
        # Se calcula AHORA, sobre el precio de lista (al ofrecerlo no se sabía qué plan compraría).
        beneficio.descuento_clp = desglose(beneficio, precio_lista_clp)["descuento_clp"]

    beneficio.estado = EstadoBeneficio.usado
    beneficio.usado_en = momento
    db.commit()
    db.refresh(beneficio)
    return beneficio


def anular(db: Session, beneficio: Beneficio, *, motivo: str, por=None,
           ahora: datetime | None = None) -> Beneficio:
    """`ofrecido → anulado`: el admin se arrepiente y el regalo se REVOCA.

    Sólo se anula un beneficio que nadie usó: si ya se usó, la clase se tomó (o el descuento ya se
    aplicó) y anularlo reescribiría la historia en vez de corregir el presente. El motivo es
    obligatorio: una anulación sin explicación es una fila que nadie puede auditar después.
    """
    momento = _ahora(ahora)
    if beneficio is None or beneficio.estado != EstadoBeneficio.ofrecido:
        raise BeneficioNoVivo(
            "Sólo se anula un beneficio que el alumno todavía no usó: este ya está "
            f"`{getattr(beneficio, 'estado', None)}`.")
    if not (motivo or "").strip():
        raise ValorInvalido(
            "La anulación necesita un motivo: sin él nadie puede auditarla después.")

    _revocar(db, beneficio)
    beneficio.estado = EstadoBeneficio.anulado
    beneficio.anulado_por = por
    beneficio.anulado_at = momento
    beneficio.anulado_motivo = motivo.strip()[:300]
    db.commit()
    db.refresh(beneficio)
    return beneficio


def _revocar(db: Session, beneficio: Beneficio) -> None:
    """Le quita al alumno lo que este beneficio le entregó (no hace `commit()`: lo hace `anular`).

    Las clases que se le sumaron a un plan se descuentan en lo que QUEDE del regalo: los créditos son
    fungibles, así que no se puede saber cuál se gastó y no se descuenta más de lo que hay. El pase
    que se abrió para el alumno se queda sin créditos y su suscripción vence. Un `descuento` no
    materializa nada: no hay nada que revocar.
    """
    if beneficio.tipo != TipoBeneficio.clases_gratis or beneficio.suscripcion_id is None:
        return
    suscripcion = db.get(Suscripcion, beneficio.suscripcion_id)
    if suscripcion is None:
        return
    if suscripcion.creditos_disponibles is not None:
        suscripcion.creditos_disponibles = max(
            0, suscripcion.creditos_disponibles - beneficio.valor)
    # ¿El acceso lo abrió ESTE beneficio? Sólo si el plan no es comercial (la MISMA columna que
    # `shared.estados.sql_plan_comercial()`, corrección A): entonces la suscripción ES el pase y se
    # vence entera. Si el plan es del alumno, su membresía no se toca.
    es_comercial = db.query(Plan.es_comercial).filter(Plan.id == beneficio.plan_id).scalar()
    if not es_comercial:
        suscripcion.estado = EstadoSuscripcion.vencido