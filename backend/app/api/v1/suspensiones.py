"""
Router de Suspensión de plan (supervisión y suspensión por salud, ambas del admin).

El alumno YA NO puede pedir/cancelar su propia suspensión: los endpoints
`/alumnos/me/suspension*` se retiraron. Quedan dos familias, ambas de admin:

  * `/admin/suspensiones*` — el admin lista, ve los KPIs y (con `usuario_id`) el
    historial de un alumno (sólo lectura).
  * `/admin/alumnos/{id}/suspension-salud*` — el admin crea/cancela una suspensión
    por salud (sin tope ni cupo).

Las reglas viven en `services/suspensiones_service.py`; este router sólo resuelve
quién es el usuario, busca su plan vigente y traduce las excepciones del servicio
a HTTP.
"""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_admin
from app.core.estados import no_cancelada, vigente_hoy
from app.core.rate_limit import limiter, LIMIT_CRITICO
from app.db.database import get_db
from app.models.clase import Clase
from app.models.disciplina import Disciplina
from app.models.reserva import Reserva
from app.models.suscripcion import Suscripcion
from app.models.suspension_plan import SuspensionPlan
from app.models.usuario import Usuario
from app.services import suspensiones_service
from app.services.reservas_service import ReembolsoTransitorio
from app.utils.busqueda import columna_normalizada, normalizar
from app.utils.santiago import fecha_chile, hoy_santiago

# Mismo prefijo que `wods.py`/`kpis.py`: el router define su prefijo y `main.py` lo
# monta SIN prefijo extra. Las rutas llevan el path completo (`/admin/suspensiones*`
# y `/admin/alumnos/{id}/suspension-salud*`) en un solo router.
router = APIRouter(prefix="/api/v1", tags=["Suspensiones"])


class SuspensionSaludCreate(BaseModel):
    fecha_inicio: date
    fecha_fin: date
    motivo: Optional[str] = None


# ── Helpers ──────────────────────────────────────────────────────────────────
def _suscripcion_activa(db: Session, tenant_id: int, usuario_id: int):
    """La membresía vigente del alumno (misma regla que `/planes/membresia-activa`)."""
    return (
        db.query(Suscripcion)
        .filter(
            Suscripcion.tenant_id == tenant_id,
            Suscripcion.usuario_id == usuario_id,
            Suscripcion.estado == "activo",
            vigente_hoy(Suscripcion.fecha_expiracion),
        )
        .order_by(
            Suscripcion.creditos_disponibles.desc().nulls_last(),
            Suscripcion.fecha_expiracion.desc(),
        )
        .first()
    )


def _reservas_en_rango(db: Session, tenant_id: int, usuario_id: int,
                       fecha_inicio: date, dias: int):
    """Reservas vivas del alumno con `clase.fecha` en [fecha_inicio, fecha_fin]."""
    filas = (
        db.query(Reserva, Clase, Disciplina)
        .join(Clase, Reserva.clase_id == Clase.id)
        .join(Disciplina, Clase.disciplina_id == Disciplina.id)
        .filter(
            Reserva.tenant_id == tenant_id,
            Reserva.alumno_id == usuario_id,
            no_cancelada(Reserva.estado),
            Clase.fecha >= fecha_inicio,
            Clase.fecha <= fecha_inicio + timedelta(days=dias - 1),
        )
        .order_by(Clase.fecha, Clase.hora_inicio)
        .all()
    )
    return [
        {
            "reserva_id": r.id,
            "clase_id": c.id,
            "fecha": str(c.fecha),
            "hora_inicio": str(c.hora_inicio),
            "disciplina": d.nombre,
        }
        for r, c, d in filas
    ]


def _reservas_canceladas_por_suspension(db: Session, tenant_id: int, usuario_id: int,
                                        fecha_inicio: date, dias: int):
    """Las reservas que acabaron en `cancelada_por_suspension` en el rango pedido.

    Se usa DESPUÉS de `crear_suspension_salud`: en ese momento las reservas del
    rango ya están con el estado nuevo, así que se filtran por el literal exacto
    (la previsualización de antes de confirmar usa `_reservas_en_rango`, que mira
    las VIVAS).
    """
    filas = (
        db.query(Reserva, Clase, Disciplina)
        .join(Clase, Reserva.clase_id == Clase.id)
        .join(Disciplina, Clase.disciplina_id == Disciplina.id)
        .filter(
            Reserva.tenant_id == tenant_id,
            Reserva.alumno_id == usuario_id,
            Reserva.estado == "cancelada_por_suspension",
            Clase.fecha >= fecha_inicio,
            Clase.fecha <= fecha_inicio + timedelta(days=dias - 1),
        )
        .order_by(Clase.fecha, Clase.hora_inicio)
        .all()
    )
    return [
        {
            "reserva_id": r.id,
            "clase_id": c.id,
            "fecha": str(c.fecha),
            "hora_inicio": str(c.hora_inicio),
            "disciplina": d.nombre,
        }
        for r, c, d in filas
    ]


# ── Admin: listado (sólo lectura) + resumen de KPIs ─────────────────────────
def _estado_suspension(s, hoy: date) -> str:
    """'activa' | 'futura' | 'pasada' | 'cancelada' calculado en el momento
    (no se persiste). Una suspensión cancelada nunca es 'activa' ni
    'futura', aunque su rango de fechas original siga vigente."""
    if bool(getattr(s, "cancelada", False)):
        return "cancelada"
    inicio = fecha_chile(s.fecha_inicio)
    fin = fecha_chile(s.fecha_fin)
    if inicio <= hoy <= fin:
        return "activa"
    if inicio > hoy:
        return "futura"
    return "pasada"


@router.get("/admin/suspensiones")
def listar_suspensiones(
    buscar: Optional[str] = Query(None),
    estado: Optional[str] = Query(None),
    desde: Optional[date] = Query(None),
    hasta: Optional[date] = Query(None),
    usuario_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Listado de suspensiones del box (el admin sólo supervisa, no actúa).

    Filtros: búsqueda por nombre/email de alumno (sin mayúsculas ni tildes), estado calculado
    en el momento (activa/futura/pasada/cancelada), rango de `fecha_inicio` y, opcionalmente,
    UN alumno (`usuario_id`, lo usa la ficha para el resumen de solo lectura).
    """
    tid = current_user["tenant_id"]
    query = (
        db.query(SuspensionPlan, Usuario)
        .join(Usuario, SuspensionPlan.usuario_id == Usuario.id)
        .filter(SuspensionPlan.tenant_id == tid,
                SuspensionPlan.origen == suspensiones_service.ORIGEN_ALUMNO)
    )
    if buscar and buscar.strip():
        # Sin mayúsculas NI tildes: el patrón y la columna se normalizan igual (kpis.py).
        patron = f"%{normalizar(buscar.strip())}%"
        query = query.filter(or_(
            columna_normalizada(Usuario.nombre).like(patron),
            columna_normalizada(Usuario.correo).like(patron),
        ))
    if desde:
        query = query.filter(SuspensionPlan.fecha_inicio >= desde)
    if hasta:
        query = query.filter(SuspensionPlan.fecha_inicio <= hasta)
    if usuario_id:
        query = query.filter(SuspensionPlan.usuario_id == usuario_id)

    filas = query.order_by(SuspensionPlan.fecha_inicio.desc()).all()
    hoy = hoy_santiago()
    items = []
    for s, u in filas:
        estado_calc = _estado_suspension(s, hoy)
        if estado and estado_calc != estado:
            continue
        items.append({
            "id": s.id,
            "origen": s.origen,
            "alumno_id": s.usuario_id,
            "alumno_nombre": u.nombre,
            "alumno_email": u.correo,
            "fecha_inicio": str(s.fecha_inicio),
            "fecha_fin": str(s.fecha_fin),
            "dias": s.dias,
            "reservas_canceladas": s.reservas_canceladas,
            "estado": estado_calc,
            "cancelada": bool(s.cancelada),
            # CUÁNDO se canceló (auditoría, migración 074): lo muestra la ficha del
            # alumno. Mismo formato que el resto de las fechas de este dict (`str`).
            "cancelada_en": str(s.cancelada_en) if s.cancelada_en else None,
            "created_at": str(s.created_at),
        })
    return items


@router.get("/admin/suspensiones/resumen")
def resumen_suspensiones(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Los 4 KPIs del mockup: activas hoy, del mes y días totales del mes (mes
    calendario de Chile), y reservas canceladas como TOTAL HISTÓRICO (todas las
    suspensiones de siempre, no sólo las del mes)."""
    tid = current_user["tenant_id"]
    suspensiones = (
        db.query(SuspensionPlan)
        .filter(SuspensionPlan.tenant_id == tid,
                SuspensionPlan.origen == suspensiones_service.ORIGEN_ALUMNO)
        .all()
    )
    hoy = hoy_santiago()
    mes = hoy.month
    anio = hoy.year

    activas_hoy = 0
    del_mes = 0
    dias_totales_mes = 0
    reservas_canceladas_totales = 0

    for s in suspensiones:
        inicio = fecha_chile(s.fecha_inicio)
        fin = fecha_chile(s.fecha_fin)
        if inicio <= hoy <= fin:
            activas_hoy += 1
        if inicio.year == anio and inicio.month == mes:
            del_mes += 1
            dias_totales_mes += s.dias or 0
        # TOTAL HISTÓRICO acumulado: TODAS las suspensiones de siempre (no el mes).
        reservas_canceladas_totales += s.reservas_canceladas or 0

    return {
        "activas_hoy": activas_hoy,
        "del_mes": del_mes,
        "dias_totales_mes": dias_totales_mes,
        "reservas_canceladas_totales": reservas_canceladas_totales,
    }


# ── Admin: suspensión por salud (la crea/cancela el admin desde la ficha) ─────
@router.post("/admin/alumnos/{usuario_id}/suspension-salud")
@limiter.limit(LIMIT_CRITICO)
def crear_suspension_salud(
    usuario_id: int,
    request: Request,
    data: SuspensionSaludCreate,
    preview: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Suspensión por salud (admin): `?preview=true` devuelve el aviso previo
    (días calculados + nueva fecha de vencimiento + reservas a cancelar) sin
    escribir; sin `preview`, confirma y ejecuta.

    El admin define `fecha_inicio`/`fecha_fin` (no días): `dias` lo calcula el
    backend (`dias_entre`). Sin tope de días, sin mínimo de créditos y sin mínimo
    de días hasta el vencimiento (esas reglas son de la self-service del alumno).
    """
    tid = current_user["tenant_id"]
    admin_id = current_user["usuario_id"]

    usuario = db.query(Usuario).filter(
        Usuario.id == usuario_id, Usuario.tenant_id == tid).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")

    if data.fecha_fin <= data.fecha_inicio:
        raise HTTPException(status_code=400,
                            detail="La fecha de vuelta debe ser posterior a la de inicio.")

    dias = suspensiones_service.dias_entre(data.fecha_inicio, data.fecha_fin)

    suscripcion = _suscripcion_activa(db, tid, usuario_id)
    if not suscripcion:
        raise HTTPException(status_code=400,
                            detail=suspensiones_service.MOTIVO_SIN_PLAN)

    if preview:
        reservas = _reservas_en_rango(db, tid, usuario_id, data.fecha_inicio, dias)
        nueva_fecha = suscripcion.fecha_expiracion + timedelta(days=dias)
        return {
            "dias": dias,
            "fecha_inicio": str(data.fecha_inicio),
            "fecha_fin": str(data.fecha_fin),
            "fecha_expiracion_actual": str(suscripcion.fecha_expiracion),
            "fecha_expiracion_nueva": str(nueva_fecha),
            "reservas_a_cancelar": reservas,
        }

    try:
        suspension = suspensiones_service.crear_suspension_salud(
            db, usuario_id, admin_id, data.fecha_inicio, data.fecha_fin,
            data.motivo)
    except ReembolsoTransitorio:
        raise HTTPException(status_code=503, detail="Alta demanda, intenta de nuevo")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    reservas_canceladas = _reservas_canceladas_por_suspension(
        db, tid, usuario_id, data.fecha_inicio, dias)
    return {
        "suspension": {
            "id": suspension.id,
            "fecha_inicio": str(suspension.fecha_inicio),
            "fecha_fin": str(suspension.fecha_fin),
            "dias": suspension.dias,
            "motivo": suspension.motivo,
            "reservas_canceladas": suspension.reservas_canceladas,
        },
        "fecha_expiracion": str(suscripcion.fecha_expiracion),
        "reservas_canceladas": reservas_canceladas,
    }


@router.post("/admin/suspensiones/{suspension_id}/cancelar-salud")
@limiter.limit(LIMIT_CRITICO)
def cancelar_suspension_salud(
    suspension_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Cancela una suspensión por salud y revierte `fecha_expiracion` exacta.

    Sin cupo anual: el admin cancela cuando quiera, las veces que quiera.
    """
    tid = current_user["tenant_id"]

    suspension = db.query(SuspensionPlan).filter(
        SuspensionPlan.id == suspension_id,
        SuspensionPlan.tenant_id == tid,
    ).first()
    if not suspension:
        raise HTTPException(status_code=404, detail="Suspensión no encontrada")

    try:
        suscripcion = suspensiones_service.cancelar_suspension_salud(
            db, suspension_id, current_user["usuario_id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "suspension_id": suspension.id,
        "fecha_expiracion": str(suscripcion.fecha_expiracion),
    }


@router.get("/admin/alumnos/{usuario_id}/suspensiones-salud")
def suspensiones_salud(
    usuario_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Historial de suspensiones por salud de un alumno (tabla del panel)."""
    tid = current_user["tenant_id"]

    usuario = db.query(Usuario).filter(
        Usuario.id == usuario_id, Usuario.tenant_id == tid).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")

    suspensiones = (
        db.query(SuspensionPlan)
        .filter(SuspensionPlan.usuario_id == usuario_id,
                SuspensionPlan.tenant_id == tid,
                SuspensionPlan.origen == suspensiones_service.ORIGEN_ADMIN_SALUD)
        .order_by(SuspensionPlan.fecha_inicio.desc())
        .all()
    )
    hoy = hoy_santiago()
    items = []
    for s in suspensiones:
        estado = "cancelada" if s.cancelada else _estado_suspension(s, hoy)
        items.append({
            "id": s.id,
            "fecha_inicio": str(s.fecha_inicio),
            "fecha_fin": str(s.fecha_fin),
            "dias": s.dias,
            "motivo": s.motivo,
            "estado": estado,
            "cancelada": bool(s.cancelada),
            "created_at": str(s.created_at),
        })
    return items


