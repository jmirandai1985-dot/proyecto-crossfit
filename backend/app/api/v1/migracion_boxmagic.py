"""Panel de control de la ACTIVACIÓN de los alumnos migrados desde BoxMagic.

⚠️ No confundir con `api/v1/migracion.py` (prefijo `/api/v1/migracion`), que es un
utillaje viejo para correr ALTER TABLE ad-hoc por HTTP. Este router responde bajo
`/api/v1/migracion-boxmagic`; es de sólo lectura SALVO la corrección puntual del
padrón (`PUT /candidatos/{id}`), que sólo escribe `candidatos_boxmagic`.

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
/recuperacion/{candidato_id}/promocion` configura una oferta puntual y manda un correo
DEDICADO a esa oferta, y `PUT /recuperacion/{candidato_id}/marcar-recuperado` cierra el
ciclo cuando el alumno vuelve.

La oferta es un BENEFICIO REAL, no sólo un correo: `dias_gratis` son CLASES gratis
(el nombre del tipo quedó mal desde el principio; se mantiene por compatibilidad) y se
pueden ofrecer de 1 a 15 — el MISMO rango que valida Fidelización
(`beneficios_service.CLASES_MIN/MAX`). `descuento_porcentaje` es 1-100 %. El tipo
`descuento_monto` ya NO se ofrece (no tiene equivalente en el sistema de cobro): la
constante sobrevive sólo para las filas históricas.

Cuando ese alumno se registra (`POST /api/v1/alumnos/registro/alumno-nuevo`), el alta
aplica la oferta: liga la fila a la cuenta nueva, crea el `Beneficio` real y la marca
como `recuperado` (ver `services/promociones_recuperacion_service.py`).

El destinatario es el CANDIDATO del padrón (`candidato_id`, migración 080): los
desertores de BoxMagic todavía no tienen cuenta y crearla es un paso posterior. Si ese
correo ya existe en `usuarios`, la oferta se liga TAMBIÉN a la cuenta (`usuario_id`) y
el correo sale a esa persona; si no, `usuario_id` queda NULL.

`GET /recuperacion/{candidato_id}/promocion/preview` (Fase 6) devuelve el ASUNTO y el
HTML del correo que mandaría ese POST, para que el admin lo lea antes de confirmar. Es
de sólo lectura: no escribe en `promociones_recuperacion` ni manda nada.

CORRECCIÓN DEL PADRÓN (ambos paneles)
------------------------------------
`PUT /candidatos/{candidato_id}` permite corregir `nombre` y `correo` del padrón (el
Excel real trae correos truncados/mal escritos). Valida el correo, respeta el UNIQUE
`(tenant_id, correo)` y BLOQUEA el cambio de correo si el candidato ya tiene una cuenta
real: ese vínculo es por correo y cambiarlo rompería el LEFT JOIN.
"""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_admin
from app.db.database import get_db
from app.models.candidato_boxmagic import (
    GRUPO_ACTIVACION, GRUPO_RECUPERACION, CandidatoBoxmagic, normalizar_correo,
)
from app.models.plan import Plan
from app.models.promocion_recuperacion import (
    ESTADO_PROMO_ENVIADA, ESTADO_PROMO_RECUPERADO, ESTADO_PROMO_VENCIDA,
    TIPO_BENEFICIO_DIAS_GRATIS, TIPOS_BENEFICIO_PROMOCION, PromocionRecuperacion,
)
from app.models.suscripcion import Suscripcion
from app.models.usuario import RolUsuario, Usuario
from app.services import beneficios_service, email_service
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
#      quedan ligadas a los DOS ids (`candidato_id` + `usuario_id`);
#    * SIN cuenta real -> `ultima_asistencia`/`dias_ausente`/`telefono` en None, pero
#      la oferta se puede configurar igual: se cuelga del `candidato_id` y el correo
#      sale con el nombre/correo del padrón (migración 080). Antes se bloqueaba con
#      404 y el 100% de los envíos fallaba, que es el bug que corrige esta versión.
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


def _candidato_del_tenant(db: Session, tenant_id: int, candidato_id: int):
    """El candidato INACTIVO del padrón del box del token, o 404.

    Es el destinatario de la oferta (migración 080): los desertores de BoxMagic no
    tienen cuenta real, así que no se puede resolver por `usuarios`. El filtro por
    `grupo` evita ofrecerle una recuperación a alguien del panel de activación.
    """
    candidato = (
        db.query(CandidatoBoxmagic)
        .filter(
            CandidatoBoxmagic.id == candidato_id,
            CandidatoBoxmagic.tenant_id == tenant_id,
            CandidatoBoxmagic.grupo == GRUPO_RECUPERACION,
        )
        .first()
    )
    if candidato is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidato no encontrado",
        )
    return candidato


def _cuenta_del_candidato(db: Session, tenant_id: int, candidato):
    """La cuenta REAL del candidato (por correo normalizado), o None si no tiene.

    No todas las filas del padrón tienen `usuarios`: la cuenta se crea el día de la
    migración real. Cuando existe, la oferta se liga también a `usuario_id`.
    """
    return _usuarios_por_correo(db, tenant_id, [candidato.correo]).get(candidato.correo)


def _candidato_del_box(db: Session, tenant_id: int, candidato_id: int):
    """Candidato del padrón del box (de CUALQUIER grupo), o 404.

    La edición del padrón aplica a activación y recuperación; a diferencia de
    `_candidato_del_tenant`, acá no se filtra por `grupo`.
    """
    candidato = (
        db.query(CandidatoBoxmagic)
        .filter(
            CandidatoBoxmagic.id == candidato_id,
            CandidatoBoxmagic.tenant_id == tenant_id,
        )
        .first()
    )
    if candidato is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidato no encontrado",
        )
    return candidato


class CandidatoEdicionIn(BaseModel):
    """Corrección puntual del padrón de BoxMagic (nombre + correo)."""

    nombre: str = Field(..., min_length=1, max_length=150)
    correo: EmailStr = Field(
        ..., max_length=150,
        description="Correo real del candidato (se guarda normalizado)")

    model_config = ConfigDict(extra="forbid")

    @field_validator("nombre")
    @classmethod
    def _nombre_no_vacio(cls, valor):
        limpio = " ".join(str(valor or "").split())
        if not limpio:
            raise ValueError("El nombre no puede estar vacío")
        return limpio

    @field_validator("correo")
    @classmethod
    def _correo_normalizado(cls, valor):
        return normalizar_correo(str(valor))


@router.put("/candidatos/{candidato_id}")
def editar_candidato(
    candidato_id: int,
    body: CandidatoEdicionIn,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Corrige `nombre` y `correo` de UN candidato del padrón (ambos paneles).

    El Excel real de BoxMagic trae correos truncados/mal escritos; esto permite
    arreglarlos sin tocar la base a mano. Reglas:

      * el correo se valida con `EmailStr` y se guarda normalizado (sin espacios,
        minúsculas), igual que el importador;
      * si el correo nuevo ya pertenece a otro candidato del box -> 400 (respeta
        `uq_candidatos_boxmagic_tenant_correo`);
      * si el candidato YA tiene una cuenta real (`usuarios` por correo), cambiar el
        correo rompería el LEFT JOIN que los vincula -> 400; el nombre sí se puede
        corregir.
    """
    tenant_id = current_user["tenant_id"]
    candidato = _candidato_del_box(db, tenant_id, candidato_id)

    correo_nuevo = normalizar_correo(str(body.correo))
    cambia_correo = correo_nuevo != normalizar_correo(candidato.correo)

    if cambia_correo:
        cuenta = _cuenta_del_candidato(db, tenant_id, candidato)
        if cuenta is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=("Este candidato ya tiene una cuenta real: no se puede "
                        "cambiar el correo. Solo puedes editar el nombre."),
            )
        repetido = (
            db.query(CandidatoBoxmagic)
            .filter(
                CandidatoBoxmagic.tenant_id == tenant_id,
                CandidatoBoxmagic.correo == correo_nuevo,
                CandidatoBoxmagic.id != candidato.id,
            )
            .first()
        )
        if repetido is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ya existe un candidato con ese correo",
            )

    candidato.nombre = body.nombre
    candidato.correo = correo_nuevo
    try:
        db.commit()
    except IntegrityError:
        # Carrera con otra alta/edición: el UNIQUE (tenant_id, correo) es la última
        # palabra. Se devuelve el mismo 400 claro que la pre-consulta.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ya existe un candidato con ese correo",
        )
    db.refresh(candidato)

    return {
        "candidato_id": candidato.id,
        "nombre": candidato.nombre,
        "correo": candidato.correo,
    }


def _rango_cantidad(tipo_beneficio: str) -> tuple:
    """Máximo (y la unidad, en palabras) que acepta ese `tipo_beneficio`.

    Las clases gratis salen del MISMO rango que valida Fidelización
    (`beneficios_service.CLASES_MIN/MAX`): así el panel de Recuperación no puede ofrecer
    una cantidad que después el Beneficio real rechace. El % tiene su propio techo físico
    (100) porque un descuento mayor al precio no existe.
    """
    if tipo_beneficio == TIPO_BENEFICIO_DIAS_GRATIS:
        return beneficios_service.CLASES_MAX, "clases"
    return 100, "porcentaje"


class PromocionRecuperacionIn(BaseModel):
    """Oferta que el admin configura para un alumno inactivo.

    `cantidad` es la unidad de `tipo_beneficio`: CLASES gratis (`dias_gratis`, entre
    `CLASES_MIN` y `CLASES_MAX` — el nombre del campo es viejo, son clases, no días de
    calendario) o porcentaje (`descuento_porcentaje`, 1-100). El tipo se valida acá para
    que la tabla no acumule valores que ningún correo sabe contar, y `descuento_monto`
    ya no se acepta: no tiene equivalente en el sistema de cobro.
    """

    tipo_beneficio: str = Field(
        ..., description="dias_gratis | descuento_porcentaje")
    cantidad: int = Field(..., ge=1, description="Clases (1-15) o % de descuento")
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

    @model_validator(mode="after")
    def _cantidad_del_tipo(self):
        """La cantidad tiene que caber en su unidad (un % de 120 o 20 clases no existen)."""
        maximo, que = _rango_cantidad(self.tipo_beneficio)
        if self.cantidad > maximo:
            raise ValueError(
                f"La cantidad de {que} tiene que estar entre 1 y {maximo} "
                f"(llegó {self.cantidad}).")
        return self


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

    Un candidato SIN cuenta real también puede tener oferta: se cuelga de
    `candidato_id` (migración 080) y el correo sale con el nombre/correo del padrón.
    `id` sigue siendo la cuenta REAL (None mientras no exista).
    """
    tenant_id = current_user["tenant_id"]
    candidatos = _candidatos(db, tenant_id, GRUPO_RECUPERACION)
    usuarios = _usuarios_por_correo(
        db, tenant_id, [candidato.correo for candidato in candidatos])

    # UNA sola consulta de ofertas para todo el listado, de la más reciente a la más
    # vieja: la primera fila de cada candidato es la que define su estado. Se buscan
    # las ofertas nuevas (por `candidato_id`) y las históricas (por `usuario_id`,
    # anteriores a la migración 080); el resultado se indexa SIEMPRE por candidato
    # para que el panel no dependa de cuál de los dos ids traiga la fila.
    candidato_ids = [candidato.id for candidato in candidatos]
    candidato_por_usuario_id: dict = {}
    for candidato in candidatos:
        cuenta = usuarios.get(candidato.correo)
        if cuenta is not None:
            candidato_por_usuario_id[cuenta.id] = candidato.id

    promociones: dict = {}
    filtros_destinatario = []
    if candidato_ids:
        filtros_destinatario.append(
            PromocionRecuperacion.candidato_id.in_(candidato_ids))
    if candidato_por_usuario_id:
        filtros_destinatario.append(
            PromocionRecuperacion.usuario_id.in_(list(candidato_por_usuario_id)))

    if filtros_destinatario:
        filas = (
            db.query(PromocionRecuperacion)
            .filter(
                PromocionRecuperacion.tenant_id == tenant_id,
                or_(*filtros_destinatario),
            )
            .order_by(PromocionRecuperacion.creado_en.desc(),
                      PromocionRecuperacion.id.desc())
            .all()
        )
        for promo in filas:
            candidato_id = promo.candidato_id
            if candidato_id is None:
                candidato_id = candidato_por_usuario_id.get(promo.usuario_id)
            if candidato_id is not None:
                promociones.setdefault(candidato_id, promo)

    # Última asistencia REAL de las cuentas que existen (una sola consulta, sin N+1).
    # Los días se cuentan con el "hoy" de Chile, igual que `fidelizacion.py`: con la TZ
    # del servidor (UTC) el conteo se corre un día de noche.
    ids = list(candidato_por_usuario_id)
    ultimas = ultima_asistencia_por_alumno(db, tenant_id, ids) if ids else {}
    hoy = hoy_santiago()

    ahora = datetime.now(timezone.utc)
    listado = []
    por_estado = {estado: 0 for estado in ESTADOS_RECUPERACION}

    for candidato in candidatos:
        alumno = usuarios.get(candidato.correo)
        promo = promociones.get(candidato.id)
        estado = _estado_recuperacion(promo, ahora)
        por_estado[estado] += 1

        ultima = ultimas.get(alumno.id) if alumno is not None else None
        listado.append({
            # Id de la cuenta REAL (None mientras no exista) y del padrón: la fila del
            # panel se identifica por `candidato_id`, y las acciones (oferta / marcar
            # recuperado) operan sobre él. `id` solo se usa para mostrar datos que
            # requieren cuenta (asistencia, teléfono).
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


@router.get("/recuperacion/{candidato_id}/promocion/preview")
def preview_promocion_recuperacion(
    candidato_id: int,
    tipo_beneficio: str = Query(
        ..., description="dias_gratis | descuento_porcentaje"),
    cantidad: int = Query(..., ge=1, description="Clases (1-15) o % de descuento"),
    vence_en: datetime = Query(
        ..., description="Fecha hasta la que vale la oferta (ISO 8601). Igual que en el "
                         "POST, se toma el FIN DE ESE DÍA en hora de Chile."),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Vista previa (asunto + HTML) del correo de la oferta, SIN guardar ni enviar nada.

    Funciona para CUALQUIER candidato del padrón, tenga o no cuenta real: el nombre
    del correo sale de `candidatos_boxmagic`, que es el destinatario de la oferta
    (migración 080). Antes exigía una cuenta y los 459 desertores no podían ni ver
    el correo que se les iba a mandar.

    Es un GET sin efectos secundarios: NO crea la fila de `promociones_recuperacion`, NO
    registra el envío en `notificaciones_enviadas` y NO llama a ningún método de envío de
    `email_service`. Sólo lee al candidato (para su nombre) y la configuración del box
    (para el pie de contacto).

    El copy lo arma la MISMA función que usa el envío real
    (`email_service.render_email_promocion_recuperacion`, documentada como fuente única
    del texto) y el `{{CONTACTO_BOX}}` se resuelve con `render_con_contacto` igual que en
    `_enviar`: así lo que el admin lee antes de confirmar es exactamente el correo que
    recibiría el alumno, con su WhatsApp real y no un placeholder.

    `vence_en` se normaliza con `_vence_en_chile` por el mismo motivo: el correo real
    muestra el FIN DEL DÍA en Chile, así que la vista previa tiene que mostrar esa fecha
    y no la del payload.

    Un tipo de beneficio fuera de `TIPOS_BENEFICIO_PROMOCION` responde 422 (igual que el
    body del POST) — y lo mismo una `cantidad` fuera de su rango (clases 1-15, % 1-100):
    el preview no puede prometer una oferta que el POST rechazaría. Un `candidato_id` de
    otro box 404. La fecha pasada NO se rechaza: acá no se crea nada, y el formulario ya
    la bloquea antes de llegar al POST.
    """
    tipo = str(tipo_beneficio or "").strip().lower()
    if tipo not in TIPOS_BENEFICIO_PROMOCION:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Tipo de beneficio inválido: usa "
                   + " | ".join(TIPOS_BENEFICIO_PROMOCION),
        )
    maximo, que = _rango_cantidad(tipo)
    if cantidad > maximo:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"La cantidad de {que} tiene que estar entre 1 y {maximo} "
                   f"(llegó {cantidad}).",
        )

    tenant_id = current_user["tenant_id"]
    candidato = _candidato_del_tenant(db, tenant_id, candidato_id)

    asunto, html = email_service.render_email_promocion_recuperacion(
        candidato.nombre, tipo, cantidad, _vence_en_chile(vence_en))
    # El template deja el contacto como placeholder y el envío real lo resuelve en
    # `_enviar`: acá se resuelve igual (con la MISMA sesión del request, ver
    # `contacto_del_box`) para que la vista previa no muestre `{{CONTACTO_BOX}}`.
    html = email_service.render_con_contacto(html, tenant_id, db=db)
    return {"asunto": asunto, "html": html}


@router.post("/recuperacion/{candidato_id}/promocion",
             status_code=status.HTTP_201_CREATED)
def crear_promocion_recuperacion(
    candidato_id: int,
    body: PromocionRecuperacionIn,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Configura la oferta de un CANDIDATO del padrón y le manda el correo dedicado.

    El destinatario es `candidato_id` (migración 080): los desertores de BoxMagic NO
    tienen cuenta real todavía, así que la oferta se cuelga del padrón y el correo
    sale con su nombre/correo. Si ese correo YA existe en `usuarios`, la fila se liga
    también a `usuario_id` (las dos puertas) para que la oferta siga asociada a la
    cuenta cuando el alumno vuelva.

    La fila se guarda ANTES de mandar el correo: si el envío falla, la oferta existe
    igual (el admin la ve en el panel y puede contactar al alumno a mano) y el
    response lo dice con `correo_enviado: false`. Es el mismo criterio best-effort
    del resto del proyecto: una promesa registrada no se pierde porque el SMTP esté
    caído. `notificacion_id` queda en NULL si no hubo envío (o si no se pudo registrar
    la fila del envío) y liga la oferta a su correo cuando sí lo hubo.
    """
    tenant_id = current_user["tenant_id"]
    candidato = _candidato_del_tenant(db, tenant_id, candidato_id)
    cuenta = _cuenta_del_candidato(db, tenant_id, candidato)

    vence_en = _vence_en_chile(body.vence_en)
    if vence_en <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La oferta no puede vencer en el pasado",
        )

    promo = PromocionRecuperacion(
        tenant_id=tenant_id,
        candidato_id=candidato.id,
        usuario_id=cuenta.id if cuenta is not None else None,
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
                # `id` es la cuenta REAL (None si no existe): `notificaciones_enviadas`
                # tiene FK a `usuarios` y el envío se registra igual con el correo del
                # padrón en `destinatario_correo`.
                {"id": cuenta.id if cuenta is not None else None,
                 "nombre": candidato.nombre,
                 "correo": candidato.correo,
                 "tenant_id": tenant_id},
                body.tipo_beneficio, body.cantidad, vence_en)
        )
    except Exception as e:  # noqa: BLE001 — best-effort: la oferta YA está guardada
        logger.warning(
            f"[migracion_promocion] no se pudo enviar el correo al candidato "
            f"{candidato.id}: {e}")
        notificacion_id = None

    if notificacion_id:
        promo.notificacion_id = notificacion_id
        db.commit()

    return {
        **_promocion_json(promo),
        "candidato_id": candidato.id,
        "usuario_id": cuenta.id if cuenta is not None else None,
        "correo_enviado": bool(correo_enviado),
    }


@router.put("/recuperacion/{candidato_id}/marcar-recuperado")
def marcar_promocion_recuperado(
    candidato_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Marca como 'recuperado' la promoción VIGENTE del candidato del padrón.

    "Vigente" = la que todavía puede usar (`estado='enviada'` y `vence_en` futuro); una
    oferta vencida no se marca como recuperada porque no se puede canjear. Sin oferta
    vigente -> 404 (no es un error del cliente, es el estado real del dato).

    Busca la oferta por `candidato_id` (nuevas) o por `usuario_id` (históricas, cuando
    el candidato ya tiene cuenta real). No requiere que exista la cuenta.
    """
    tenant_id = current_user["tenant_id"]
    candidato = _candidato_del_tenant(db, tenant_id, candidato_id)
    cuenta = _cuenta_del_candidato(db, tenant_id, candidato)
    ahora = datetime.now(timezone.utc)

    filtros_destinatario = [PromocionRecuperacion.candidato_id == candidato.id]
    if cuenta is not None:
        filtros_destinatario.append(
            PromocionRecuperacion.usuario_id == cuenta.id)

    promo = (
        db.query(PromocionRecuperacion)
        .filter(
            PromocionRecuperacion.tenant_id == tenant_id,
            or_(*filtros_destinatario),
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
        "candidato_id": candidato.id,
        "usuario_id": promo.usuario_id,
    }

