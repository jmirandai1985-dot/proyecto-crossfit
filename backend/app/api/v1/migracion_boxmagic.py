"""Panel de control de la ACTIVACIÓN de los alumnos migrados desde BoxMagic.

⚠️ No confundir con `api/v1/migracion.py` (prefijo `/api/v1/migracion`), que es un
utillaje viejo para correr ALTER TABLE ad-hoc por HTTP. Este router es de sólo
lectura y responde bajo `/api/v1/migracion-boxmagic`.

QUÉ HACE
--------
`GET /activacion` responde en qué etapa del embudo está cada CANDIDATO del padrón de
BoxMagic (`candidatos_boxmagic`, grupo 'activacion'):

    sin_invitar -> correo_enviado -> password_cambiada -> registro_completo
                                                          -> plan_comprado

FUENTE DE DATOS (2026-12, antes de la migración real)
----------------------------------------------------
El padrón es el Excel de BoxMagic (`candidatos_boxmagic`): los alumnos reales existen
en el panel ANTES de tener cuenta en el SaaS. Cada candidato se cruza POR CORREO
(normalizado) con la tabla `usuarios` real:

  * si YA hay un `Usuario` con ese correo, la etapa se deduce de SUS columnas (la misma
    lógica de siempre, ver abajo);
  * si todavía NO hay cuenta, la etapa es `sin_invitar` SIEMPRE: no hay nada que haya
    pasado con él en el sistema (crear la cuenta es un paso POSTERIOR y aparte, el día
    de la migración real).

Todo se DEDUCE de columnas que ya existen (no hay tabla de etapas que se pueda
desincronizar del dato real):

  * `plan_comprado`      -> tiene al menos una fila en `suscripciones` (cualquier
                            estado: haber comprado es un hecho, no un estado actual).
  * `registro_completo`  -> `acepta_tyc_en` y `acepta_salud_en` no nulos (dejó los
                            dos consentimientos del alta).
  * `password_cambiada`  -> `cambiar_password_al_login` en False Y
                            `correo_migracion_enviado_en` no nulo (migración 077).
                            El segundo requisito es clave: el alta pública normal
                            también deja el flag en False, así que sin la marca de
                            migración TODO alumno normal aparecería acá.
  * `correo_enviado`     -> `correo_migracion_enviado_en` no nulo.
  * `sin_invitar`        -> el resto.

DECISIONES
----------
* Alcance: sólo el padrón del box del token (`candidatos_boxmagic.tenant_id`) y, del
  lado de `usuarios`, sólo alumnos (`rol = 'alumno'`) del mismo box. Es un panel de
  administración, así que nunca se puede ver otra tenant.
* `activado_hoy` = el hito de la etapa alcanzada cayó en las últimas 24 h (ventana
  móvil, no día calendario: el panel se mira a cualquier hora). `sin_invitar` no
  tiene hito, así que siempre es False.
* En `password_cambiada` no hay columna propia del cambio de contraseña: se usa
  `correo_migracion_enviado_en`, el único instante de ese tramo que está en la fila.
* En la respuesta, `id` es el id del `Usuario` REAL (None si todavía no hay cuenta) y
  `candidato_id` el de `candidatos_boxmagic`. El panel usa `candidato_id` como clave de
  la fila y `id` para las acciones (que necesitan una cuenta real).

RECUPERACIÓN DE INACTIVOS (Fase 2)
----------------------------------
`GET /recuperacion` lista los CANDIDATOS del padrón con grupo 'recuperacion' (los que
en BoxMagic están `Inactivo`) y el estado de su oferta. `POST
/recuperacion/{usuario_id}/promocion` configura una oferta puntual y manda un correo
DEDICADO a esa oferta, y `PUT /recuperacion/{usuario_id}/marcar-recuperado` cierra el
ciclo cuando el alumno vuelve.

`GET /recuperacion/{usuario_id}/promocion/preview` (Fase 6) devuelve el ASUNTO y el
HTML del correo que mandaría ese POST, para que el admin lo lea antes de confirmar. Es
de sólo lectura: no escribe en `promociones_recuperacion` ni manda nada.
"""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_admin
from app.db.database import get_db
from app.models.candidato_boxmagic import (
    GRUPO_ACTIVACION, GRUPO_RECUPERACION, CandidatoBoxmagic, normalizar_correo,
)
from app.models.plan import Plan
from app.models.promocion_recuperacion import (
    ESTADO_PROMO_ENVIADA, ESTADO_PROMO_RECUPERADO, ESTADO_PROMO_VENCIDA,
    TIPOS_BENEFICIO_PROMOCION, PromocionRecuperacion,
)
from app.models.suscripcion import Suscripcion
from app.models.usuario import RolUsuario, Usuario
from app.services import email_service
# "¿Hace cuánto no entrena?" = última asistencia REAL (`reservas.asistio`), la misma
# fuente que el panel de Fidelización y la campaña de inactividad (ver
# `services/asistencia_real.py`, bug "En riesgo = 251").
from app.services.asistencia_real import ultima_asistencia_por_alumno
# El "hoy" de Chile y el fin del día se reusan de `utils/santiago.py` para no crear un
# segundo criterio de fechas en el proyecto.
from app.utils.santiago import fin_del_dia_chile, hoy_santiago

logger = logging.getLogger(__name__)

router = APIRouter()

# Embudo, de la etapa MENOS avanzada a la MÁS avanzada: es el orden en que se
# publica `resumen.por_etapa`, que siempre trae las CINCO claves (aunque estén en 0)
# para que el panel pueda dibujar el embudo completo sin defaults propios.
ETAPAS = (
    "sin_invitar",
    "correo_enviado",
    "password_cambiada",
    "registro_completo",
    "plan_comprado",
)

# "Activado hoy": el hito de la etapa alcanzada cayó en las últimas 24 h.
VENTANA_ACTIVACION = timedelta(hours=24)


def _etapa(alumno, plan_nombre):
    """Etapa del embudo, por prioridad de la MÁS avanzada a la MENOS avanzada."""
    if plan_nombre is not None:
        return "plan_comprado"
    if alumno.acepta_tyc_en is not None and alumno.acepta_salud_en is not None:
        return "registro_completo"
    if (alumno.cambiar_password_al_login is False
            and alumno.correo_migracion_enviado_en is not None):
        return "password_cambiada"
    if alumno.correo_migracion_enviado_en is not None:
        return "correo_enviado"
    return "sin_invitar"


def _como_utc(valor):
    """Instante tz-aware. Las columnas son `timestamptz`; sin zona se asume UTC."""
    if valor is None:
        return None
    if valor.tzinfo is None:
        return valor.replace(tzinfo=timezone.utc)
    return valor


def _hito(alumno, etapa, fecha_plan):
    """Instante del hito que define la etapa (None = la etapa no tiene hito)."""
    if etapa == "plan_comprado":
        return _como_utc(fecha_plan)
    if etapa == "registro_completo":
        instantes = [i for i in (_como_utc(alumno.acepta_tyc_en),
                                 _como_utc(alumno.acepta_salud_en)) if i is not None]
        return max(instantes) if instantes else None
    if etapa in ("password_cambiada", "correo_enviado"):
        # Sin columna del cambio de contraseña: se usa el envío del correo, el
        # único instante de este tramo que está en la fila.
        return _como_utc(alumno.correo_migracion_enviado_en)
    return None  # sin_invitar: ningún hito alcanzado todavía


def _candidatos(db: Session, tenant_id: int, grupo: str) -> list:
    """Padrón del box para UN panel ('activacion' | 'recuperacion').

    Es la fuente de la lista: los alumnos reales de BoxMagic existen acá aunque todavía
    no tengan cuenta en el SaaS. Ordenados por nombre (lo que ve el admin).
    """
    return (
        db.query(CandidatoBoxmagic)
        .filter(
            CandidatoBoxmagic.tenant_id == tenant_id,
            CandidatoBoxmagic.grupo == grupo,
        )
        .order_by(CandidatoBoxmagic.nombre.asc(), CandidatoBoxmagic.id.asc())
        .all()
    )


def _usuarios_por_correo(db: Session, tenant_id: int, correos: list) -> dict:
    """{correo_normalizado: Usuario} de las cuentas REALES del box.

    El cruce con el padrón es por correo porque `candidatos_boxmagic` no tiene FK a
    `usuarios` (la mayoría de los candidatos todavía no tiene cuenta). Se normalizan los
    DOS lados: `lower(trim(correo))` en SQL (el SaaS guarda el correo como lo escribió
    cada alumno) contra el correo ya normalizado del padrón. UNA consulta para todo el
    listado, no una por fila.
    """
    if not correos:
        return {}
    filas = (
        db.query(Usuario)
        .filter(
            Usuario.tenant_id == tenant_id,
            Usuario.rol == RolUsuario.alumno,
            func.lower(func.trim(Usuario.correo)).in_(correos),
        )
        .order_by(Usuario.id.asc())
        .all()
    )
    mapa: dict = {}
    for usuario in filas:
        # `setdefault`: si hubiera dos cuentas con el mismo correo, gana la más vieja
        # (id asc) en vez de que el resultado dependa del orden que devuelva Postgres.
        mapa.setdefault(normalizar_correo(usuario.correo), usuario)
    return mapa


@router.get("/activacion")
def get_activacion(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Estado de activación de CADA candidato del padrón + resumen del embudo.

    Sólo lectura: no escribe nada ni envía correos (el envío es Fase 2). Sirve para el
    panel que muestra a los ~712 alumnos reales de BoxMagic qué falta hacer con cada uno,
    ANTES de crear sus cuentas: mientras no exista el `Usuario`, el candidato aparece en
    `sin_invitar`.
    """
    tenant_id = current_user["tenant_id"]

    candidatos = _candidatos(db, tenant_id, GRUPO_ACTIVACION)
    # LEFT JOIN por correo contra las cuentas reales (una sola consulta para todo el
    # padrón): el candidato SIN cuenta simplemente no aparece en el mapa.
    usuarios = _usuarios_por_correo(
        db, tenant_id, [candidato.correo for candidato in candidatos])

    # UNA sola consulta de planes para todo el listado (no una por alumno: son
    # cientos de filas). Ordenada de la suscripción MÁS RECIENTE a la más vieja, así
    # la primera fila de cada alumno es el plan que se muestra y la fecha del hito.
    planes: dict = {}
    ids = [usuario.id for usuario in usuarios.values()]
    if ids:
        filas = (
            db.query(Suscripcion, Plan)
            .join(Plan, Plan.id == Suscripcion.plan_id)
            .filter(
                Suscripcion.tenant_id == tenant_id,
                Suscripcion.usuario_id.in_(ids),
            )
            .order_by(Suscripcion.fecha_inicio.desc(), Suscripcion.id.desc())
            .all()
        )
        for suscripcion, plan in filas:
            # `setdefault`: gana la primera = la más reciente.
            planes.setdefault(suscripcion.usuario_id,
                              (plan.nombre, suscripcion.fecha_inicio))

    desde_ventana = datetime.now(timezone.utc) - VENTANA_ACTIVACION

    listado = []
    por_etapa = {etapa: 0 for etapa in ETAPAS}
    total_activados_hoy = 0

    for candidato in candidatos:
        alumno = usuarios.get(candidato.correo)
        if alumno is None:
            # Todavía no existe la cuenta real: no pasó NADA con él en el sistema.
            etapa, plan_nombre, hito = "sin_invitar", None, None
        else:
            plan_nombre, fecha_plan = planes.get(alumno.id, (None, None))
            etapa = _etapa(alumno, plan_nombre)
            hito = _hito(alumno, etapa, fecha_plan)
        # Sin hito (sin_invitar) no puede estar "activado hoy": no pasó nada.
        activado_hoy = hito is not None and hito >= desde_ventana

        por_etapa[etapa] += 1
        if activado_hoy:
            total_activados_hoy += 1

        listado.append({
            # Id de la cuenta REAL (None mientras no exista) y del padrón: la fila del
            # panel se identifica por `candidato_id`, y las acciones usan `id`.
            "id": alumno.id if alumno is not None else None,
            "candidato_id": candidato.id,
            "nombre": candidato.nombre,
            "correo": candidato.correo,
            "etapa": etapa,
            "plan_comprado": plan_nombre,
            "activado_hoy": activado_hoy,
        })

    return {
        "alumnos": listado,
        "resumen": {
            "total": len(listado),
            "por_etapa": por_etapa,
            "activados_hoy": total_activados_hoy,
        },
    }



# ═══════════════════════════════════════════════════════════════════════════════
#  RECUPERACIÓN DE ALUMNOS INACTIVOS (Fase 2)
#
#  CRITERIO DE "QUIÉN ESTÁ EN EL PANEL" (cambió en 2026-12, antes de la migración
#  real): la lista es el PADRÓN de BoxMagic, no la tabla `usuarios`:
#
#      candidatos_boxmagic.tenant_id = <box del token>  ∧  grupo = 'recuperacion'
#
#  y ese grupo se deriva del estado del Excel (`Inactivo` -> 'recuperacion', ver
#  `grupo_desde_estado`). Antes se filtraba por asistencia real (7+ días sin venir, el
#  criterio de `fidelizacion.py`); ya no: los candidatos todavía no tienen cuenta, así
#  que no tienen asistencias que mirar, y quien decide quién dejó de venir es BoxMagic.
#
#  Cada candidato se cruza POR CORREO con `usuarios` (LEFT JOIN, ver
#  `_usuarios_por_correo`):
#    * CON cuenta real -> se muestran sus datos de contacto/asistencia y sus ofertas
#      (`promociones_recuperacion.usuario_id`), igual que antes;
#    * SIN cuenta real -> `ultima_asistencia`/`dias_ausente`/`telefono` en None y estado
#      `sin_contactar` SIEMPRE (no hay a quién mandarle el correo: el envío sale de
#      `usuarios`). Es el comportamiento esperado antes de crear las cuentas.
# ═══════════════════════════════════════════════════════════════════════════════

# Estados del alumno en el panel, en el orden en que se publican.
ESTADOS_RECUPERACION = (
    "sin_contactar",       # no se le envió ninguna oferta todavía
    "promocion_enviada",   # tiene una oferta con la ventana ABIERTA
    "vencida",             # se le ofreció algo y la ventana ya pasó
    "recuperado",          # volvió (lo marcó el admin)
)


def _estado_recuperacion(promo, ahora: datetime) -> str:
    """Estado del panel derivado de la ÚLTIMA oferta del alumno (None = sin ofertas).

    La ventana se mira junto con el estado: una fila guardada como 'enviada' con
    `vence_en` pasado es, a ojos del panel, 'vencida' (no hace falta que un job la
    reescriba; el estado persistido se respeta si alguien ya lo puso).
    """
    if promo is None:
        return "sin_contactar"
    if promo.estado == ESTADO_PROMO_RECUPERADO:
        return "recuperado"
    if promo.estado == ESTADO_PROMO_VENCIDA:
        return "vencida"
    vence = _como_utc(promo.vence_en)
    if vence is not None and vence > ahora:
        return "promocion_enviada"
    return "vencida"


def _promocion_json(promo):
    """La oferta tal como la publica el panel (None si el alumno no tiene ninguna)."""
    if promo is None:
        return None
    return {
        "id": promo.id,
        "tipo_beneficio": promo.tipo_beneficio,
        "cantidad": promo.cantidad,
        "vence_en": promo.vence_en.isoformat() if promo.vence_en else None,
        "estado": promo.estado,
        "creado_en": promo.creado_en.isoformat() if promo.creado_en else None,
        "notificacion_id": promo.notificacion_id,
    }


def _vence_en_chile(valor: datetime) -> datetime:
    """Instante de vencimiento: el FIN DEL DÍA (hora de Chile) de la fecha recibida.

    La oferta es un plazo por DÍA ("hasta el 31/12"), así que se usa la MISMA regla de
    vigencia que los planes (`fin_del_dia_chile`): vale hasta las 23:59:59 del día que
    el admin eligió, en Chile. Se toma el día TAL COMO viene en el payload (con o sin
    offset) y se descarta la hora: interpretar la medianoche UTC como medianoche local
    le robaba el último día a la oferta (en Chile son las 21:00 del día ANTERIOR) y el
    correo terminaba mostrando una fecha corrida.
    """
    return fin_del_dia_chile(valor.date())


def _alumno_del_tenant(db: Session, tenant_id: int, usuario_id: int) -> Usuario:
    """El alumno del box del token o 404 (nunca se opera sobre otra tenant)."""
    alumno = (
        db.query(Usuario)
        .filter(
            Usuario.id == usuario_id,
            Usuario.tenant_id == tenant_id,
            Usuario.rol == RolUsuario.alumno,
        )
        .first()
    )
    if alumno is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Alumno no encontrado",
        )
    return alumno


class PromocionRecuperacionIn(BaseModel):
    """Oferta que el admin configura para un alumno inactivo.

    `cantidad` es la unidad de `tipo_beneficio`: días (`dias_gratis`), porcentaje
    (`descuento_porcentaje`) o monto en CLP (`descuento_monto`). El tipo se valida
    acá para que la tabla no acumule valores que ningún correo sabe contar.
    """

    tipo_beneficio: str = Field(
        ..., description="dias_gratis | descuento_porcentaje | descuento_monto")
    cantidad: int = Field(..., ge=1, description="Días, % o monto CLP según el tipo")
    vence_en: datetime = Field(
        ..., description="Fecha hasta la que vale la oferta (ISO 8601). Se guarda el "
                         "FIN DE ESE DÍA en hora de Chile, igual que la vigencia de "
                         "los planes; la hora del payload se ignora.")

    model_config = ConfigDict(extra="forbid")

    @field_validator("tipo_beneficio")
    @classmethod
    def _tipo_valido(cls, valor):
        normalizado = str(valor or "").strip().lower()
        if normalizado not in TIPOS_BENEFICIO_PROMOCION:
            raise ValueError("Tipo de beneficio inválido: usa "
                             + " | ".join(TIPOS_BENEFICIO_PROMOCION))
        return normalizado


@router.get("/recuperacion")
def get_recuperacion(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Candidatos INACTIVOS del padrón + el estado de su oferta de recuperación.

    Sólo lectura. La lista sale de `candidatos_boxmagic` con grupo 'recuperacion' (los
    que en BoxMagic están Inactivo, ver el bloque de arriba) y cada uno se cruza por
    correo con la cuenta REAL del SaaS. Para cada uno se mira su oferta MÁS RECIENTE,
    que es la que manda: `sin_contactar` (nunca se le ofreció nada), `promocion_enviada`
    (oferta con ventana abierta), `vencida` (la ventana pasó) o `recuperado` (volvió).

    Un candidato SIN cuenta real cae siempre en `sin_contactar`: no hay `usuario_id` al
    que colgarle una oferta ni correo del que sacar el destinatario. Es lo esperado
    antes de la migración real (crear las cuentas es un paso POSTERIOR).
    """
    tenant_id = current_user["tenant_id"]
    candidatos = _candidatos(db, tenant_id, GRUPO_RECUPERACION)
    usuarios = _usuarios_por_correo(
        db, tenant_id, [candidato.correo for candidato in candidatos])

    # UNA sola consulta de ofertas para todo el listado, de la más reciente a la más
    # vieja: la primera fila de cada alumno es la que define su estado.
    promociones: dict = {}
    ids = [usuario.id for usuario in usuarios.values()]
    if ids:
        filas = (
            db.query(PromocionRecuperacion)
            .filter(
                PromocionRecuperacion.tenant_id == tenant_id,
                PromocionRecuperacion.usuario_id.in_(ids),
            )
            .order_by(PromocionRecuperacion.creado_en.desc(),
                      PromocionRecuperacion.id.desc())
            .all()
        )
        for promo in filas:
            promociones.setdefault(promo.usuario_id, promo)

    # Última asistencia REAL de las cuentas que existen (una sola consulta, sin N+1).
    # Los días se cuentan con el "hoy" de Chile, igual que `fidelizacion.py`: con la TZ
    # del servidor (UTC) el conteo se corre un día de noche.
    ultimas = ultima_asistencia_por_alumno(db, tenant_id, ids) if ids else {}
    hoy = hoy_santiago()

    ahora = datetime.now(timezone.utc)
    listado = []
    por_estado = {estado: 0 for estado in ESTADOS_RECUPERACION}

    for candidato in candidatos:
        alumno = usuarios.get(candidato.correo)
        promo = promociones.get(alumno.id) if alumno is not None else None
        estado = _estado_recuperacion(promo, ahora)
        por_estado[estado] += 1

        ultima = ultimas.get(alumno.id) if alumno is not None else None
        listado.append({
            # Id de la cuenta REAL (None mientras no exista) y del padrón: la fila del
            # panel se identifica por `candidato_id`, y las acciones (oferta / marcar
            # recuperado) necesitan el `id` de una cuenta real.
            "id": alumno.id if alumno is not None else None,
            "candidato_id": candidato.id,
            "nombre": candidato.nombre,
            "correo": candidato.correo,
            "telefono": alumno.telefono if alumno is not None else None,
            "ultima_asistencia": str(ultima) if ultima else None,
            "dias_ausente": (hoy - ultima).days if ultima else None,
            "estado": estado,
            "promocion": _promocion_json(promo),
        })

    return {
        "alumnos": listado,
        "resumen": {
            "total": len(listado),
            "por_estado": por_estado,
        },
    }


@router.get("/recuperacion/{usuario_id}/promocion/preview")
def preview_promocion_recuperacion(
    usuario_id: int,
    tipo_beneficio: str = Query(
        ..., description="dias_gratis | descuento_porcentaje | descuento_monto"),
    cantidad: int = Query(..., ge=1, description="Días, % o monto CLP según el tipo"),
    vence_en: datetime = Query(
        ..., description="Fecha hasta la que vale la oferta (ISO 8601). Igual que en el "
                         "POST, se toma el FIN DE ESE DÍA en hora de Chile."),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Vista previa (asunto + HTML) del correo de la oferta, SIN guardar ni enviar nada.

    Es un GET sin efectos secundarios: NO crea la fila de `promociones_recuperacion`, NO
    registra el envío en `notificaciones_enviadas` y NO llama a ningún método de envío de
    `email_service`. Sólo lee al alumno (para su nombre) y la configuración del box (para
    el pie de contacto).

    El copy lo arma la MISMA función que usa el envío real
    (`email_service.render_email_promocion_recuperacion`, documentada como fuente única
    del texto) y el `{{CONTACTO_BOX}}` se resuelve con `render_con_contacto` igual que en
    `_enviar`: así lo que el admin lee antes de confirmar es exactamente el correo que
    recibiría el alumno, con su WhatsApp real y no un placeholder.

    `vence_en` se normaliza con `_vence_en_chile` por el mismo motivo: el correo real
    muestra el FIN DEL DÍA en Chile, así que la vista previa tiene que mostrar esa fecha
    y no la del payload.

    Un tipo de beneficio fuera de `TIPOS_BENEFICIO_PROMOCION` responde 422 (igual que el
    body del POST) y un `usuario_id` de otro box 404. La fecha pasada NO se rechaza: acá
    no se crea nada, y el formulario ya la bloquea antes de llegar al POST.
    """
    tipo = str(tipo_beneficio or "").strip().lower()
    if tipo not in TIPOS_BENEFICIO_PROMOCION:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Tipo de beneficio inválido: usa "
                   + " | ".join(TIPOS_BENEFICIO_PROMOCION),
        )

    tenant_id = current_user["tenant_id"]
    alumno = _alumno_del_tenant(db, tenant_id, usuario_id)

    asunto, html = email_service.render_email_promocion_recuperacion(
        alumno.nombre, tipo, cantidad, _vence_en_chile(vence_en))
    # El template deja el contacto como placeholder y el envío real lo resuelve en
    # `_enviar`: acá se resuelve igual (con la MISMA sesión del request, ver
    # `contacto_del_box`) para que la vista previa no muestre `{{CONTACTO_BOX}}`.
    html = email_service.render_con_contacto(html, tenant_id, db=db)
    return {"asunto": asunto, "html": html}


@router.post("/recuperacion/{usuario_id}/promocion",
             status_code=status.HTTP_201_CREATED)
def crear_promocion_recuperacion(
    usuario_id: int,
    body: PromocionRecuperacionIn,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Configura la oferta de un alumno y le manda el correo DEDICADO a esa oferta.

    ⚠️ Requiere que el alumno YA tenga cuenta real en `usuarios`: la oferta se cuelga de
    `usuario_id` (FK) y el destinatario del correo sale de esa fila. Antes de la
    migración real, un candidato del padrón que todavía no tiene cuenta responde 404
    "Alumno no encontrado": es el estado esperado, no un bug.

    La fila se guarda ANTES de mandar el correo: si el envío falla, la oferta existe
    igual (el admin la ve en el panel y puede contactar al alumno a mano) y el
    response lo dice con `correo_enviado: false`. Es el mismo criterio best-effort
    del resto del proyecto: una promesa registrada no se pierde porque el SMTP esté
    caído. `notificacion_id` queda en NULL si no hubo envío (o si no se pudo registrar
    la fila del envío) y liga la oferta a su correo cuando sí lo hubo.
    """
    tenant_id = current_user["tenant_id"]
    alumno = _alumno_del_tenant(db, tenant_id, usuario_id)

    vence_en = _vence_en_chile(body.vence_en)
    if vence_en <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La oferta no puede vencer en el pasado",
        )

    promo = PromocionRecuperacion(
        tenant_id=tenant_id,
        usuario_id=alumno.id,
        tipo_beneficio=body.tipo_beneficio,
        cantidad=body.cantidad,
        vence_en=vence_en,
        estado=ESTADO_PROMO_ENVIADA,
        creado_por=current_user.get("usuario_id"),
    )
    db.add(promo)
    db.commit()
    db.refresh(promo)

    correo_enviado = False
    notificacion_id = None
    try:
        correo_enviado, notificacion_id = (
            email_service.enviar_email_promocion_recuperacion(
                {"id": alumno.id, "nombre": alumno.nombre,
                 "correo": alumno.correo, "tenant_id": tenant_id},
                body.tipo_beneficio, body.cantidad, vence_en)
        )
    except Exception as e:  # noqa: BLE001 — best-effort: la oferta YA está guardada
        logger.warning(
            f"[migracion_promocion] no se pudo enviar el correo al alumno "
            f"{alumno.id}: {e}")
        notificacion_id = None

    if notificacion_id:
        promo.notificacion_id = notificacion_id
        db.commit()

    return {
        **_promocion_json(promo),
        "usuario_id": alumno.id,
        "correo_enviado": bool(correo_enviado),
    }


@router.put("/recuperacion/{usuario_id}/marcar-recuperado")
def marcar_promocion_recuperado(
    usuario_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Marca como 'recuperado' la promoción VIGENTE del alumno.

    "Vigente" = la que el alumno todavía puede usar (`estado='enviada'` y
    `vence_en` futuro); una oferta vencida no se marca como recuperada porque no se
    puede canjear. Sin oferta vigente -> 404 (no es un error del cliente, es el
    estado real del dato).
    """
    tenant_id = current_user["tenant_id"]
    alumno = _alumno_del_tenant(db, tenant_id, usuario_id)
    ahora = datetime.now(timezone.utc)

    promo = (
        db.query(PromocionRecuperacion)
        .filter(
            PromocionRecuperacion.tenant_id == tenant_id,
            PromocionRecuperacion.usuario_id == alumno.id,
            PromocionRecuperacion.estado == ESTADO_PROMO_ENVIADA,
            PromocionRecuperacion.vence_en > ahora,
        )
        .order_by(PromocionRecuperacion.creado_en.desc(),
                  PromocionRecuperacion.id.desc())
        .first()
    )
    if promo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El alumno no tiene una promoción vigente",
        )

    promo.estado = ESTADO_PROMO_RECUPERADO
    db.commit()

    return {
        **_promocion_json(promo),
        "usuario_id": alumno.id,
    }

