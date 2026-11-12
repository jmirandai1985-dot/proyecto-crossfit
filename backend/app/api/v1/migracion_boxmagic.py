"""Panel de control de la ACTIVACIÓN de los alumnos migrados desde BoxMagic.

⚠️ No confundir con `api/v1/migracion.py` (prefijo `/api/v1/migracion`), que es un
utillaje viejo para correr ALTER TABLE ad-hoc por HTTP. Este router es de sólo
lectura y responde bajo `/api/v1/migracion-boxmagic`.

QUÉ HACE
--------
`GET /activacion` responde en qué etapa del embudo está cada alumno del box:

    sin_invitar -> correo_enviado -> password_cambiada -> registro_completo
                                                          -> plan_comprado

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
* Alcance: sólo alumnos (`rol = 'alumno'`) del box del token. Es un panel de
  administración, así que nunca se puede ver otra tenant.
* `activado_hoy` = el hito de la etapa alcanzada cayó en las últimas 24 h (ventana
  móvil, no día calendario: el panel se mira a cualquier hora). `sin_invitar` no
  tiene hito, así que siempre es False.
* En `password_cambiada` no hay columna propia del cambio de contraseña: se usa
  `correo_migracion_enviado_en`, el único instante de ese tramo que está en la fila.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_admin
from app.db.database import get_db
from app.models.plan import Plan
from app.models.suscripcion import Suscripcion
from app.models.usuario import RolUsuario, Usuario

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


@router.get("/activacion")
def get_activacion(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Estado de activación de CADA alumno del box + resumen del embudo.

    Sólo lectura: no escribe nada ni envía correos (el envío es Fase 2). Sirve para
    el panel que, antes de cargar a los ~712 alumnos reales de BoxMagic, muestra qué
    falta hacer con cada uno.
    """
    tenant_id = current_user["tenant_id"]

    alumnos = (
        db.query(Usuario)
        .filter(
            Usuario.tenant_id == tenant_id,
            Usuario.rol == RolUsuario.alumno,
        )
        .order_by(Usuario.nombre.asc(), Usuario.id.asc())
        .all()
    )

    # UNA sola consulta de planes para todo el listado (no una por alumno: son
    # cientos de filas). Ordenada de la suscripción MÁS RECIENTE a la más vieja, así
    # la primera fila de cada alumno es el plan que se muestra y la fecha del hito.
    planes: dict = {}
    ids = [alumno.id for alumno in alumnos]
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

    for alumno in alumnos:
        plan_nombre, fecha_plan = planes.get(alumno.id, (None, None))
        etapa = _etapa(alumno, plan_nombre)
        hito = _hito(alumno, etapa, fecha_plan)
        # Sin hito (sin_invitar) no puede estar "activado hoy": no pasó nada.
        activado_hoy = hito is not None and hito >= desde_ventana

        por_etapa[etapa] += 1
        if activado_hoy:
            total_activados_hoy += 1

        listado.append({
            "id": alumno.id,
            "nombre": alumno.nombre,
            "correo": alumno.correo,
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

