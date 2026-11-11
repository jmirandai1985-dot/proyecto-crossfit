"""
Router de Suspensión de plan (self-service del alumno + supervisión del admin).

La suspensión la pide el alumno SIN aprobación del admin: el admin sólo supervisa
(pantalla de sólo lectura). Por eso hay DOS familias acá:

  * `/alumnos/me/suspension*` — el alumno consulta su elegibilidad y confirma.
  * `/admin/suspensiones*` — el admin lista y ve los KPIs.

Las reglas viven en `services/suspensiones_service.py`; este router sólo resuelve
quién es el usuario, busca su plan vigente y traduce las excepciones del servicio
a HTTP.
"""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_current_admin
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
from app.utils.santiago import fecha_chile, hoy_santiago

# Mismo prefijo que `wods.py`/`kpis.py`: el router define su prefijo y `main.py` lo
# monta SIN prefijo extra. Las rutas llevan el path completo para poder mezclar
# `/alumnos/me/...` y `/admin/...` en un solo router sin chocar con path params.
router = APIRouter(prefix="/api/v1", tags=["Suspensiones"])


class SuspensionCreate(BaseModel):
    fecha_inicio: date
    dias: int


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

    Se usa DESPUÉS de `crear_suspension`: en ese momento las reservas del rango ya
    están con el estado nuevo, así que se filtran por el literal exacto (la
    previsualización de antes de confirmar usa `_reservas_en_rango`, que mira las
    VIVAS).
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


def _suspensiones_del_ciclo(db: Session, usuario: Usuario) -> list:
    """Suspensiones del ciclo vigente (por `fecha_inicio`), para saldo y cupo."""
    hoy = hoy_santiago()
    ciclo_inicio, ciclo_fin = suspensiones_service.ciclo_vigente(usuario.created_at, hoy)
    suspensiones = (
        db.query(SuspensionPlan)
        .filter(SuspensionPlan.usuario_id == usuario.id,
                SuspensionPlan.tenant_id == usuario.tenant_id,
                SuspensionPlan.origen == suspensiones_service.ORIGEN_ALUMNO)
        .all()
    )
    return [s for s in suspensiones if ciclo_inicio <= s.fecha_inicio < ciclo_fin]


def _suspension_activa_hoy(db: Session, tenant_id: int, usuario_id: int):
    """La suspensión no cancelada cuyo rango cubre HOY (o None).

    Incluye AMBOS orígenes (`alumno` y `admin_salud`): el alumno debe VER la de
    salud como su suspensión activa (aunque no pueda cancelarla). El filtro por
    `origen='alumno'` para el CUPO vive en el servicio, no acá.
    """
    hoy = hoy_santiago()
    suspensiones = (
        db.query(SuspensionPlan)
        .filter(SuspensionPlan.usuario_id == usuario_id,
                SuspensionPlan.tenant_id == tenant_id,
                SuspensionPlan.cancelada == False)  # noqa: E712
        .all()
    )
    for s in suspensiones:
        if fecha_chile(s.fecha_inicio) <= hoy <= fecha_chile(s.fecha_fin):
            return s
    return None


def _elegibilidad_para(db: Session, usuario: Usuario, suscripcion) -> dict:
    """Elegibilidad + saldo del ciclo vigente para `usuario`/`suscripcion`."""
    del_ciclo = _suspensiones_del_ciclo(db, usuario)
    return suspensiones_service.calcular_elegibilidad(suscripcion, usuario, del_ciclo,
                                                      hoy_santiago())


# ── Alumno: elegibilidad + previsualización de cancelaciones ─────────────────
@router.get("/alumnos/me/suspension/elegibilidad")
def elegibilidad_suspension(
    fecha_inicio: Optional[date] = Query(None),
    dias: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Elegibilidad del alumno y (opcional) las reservas que se cancelarían.

    Sin `fecha_inicio`/`dias` sólo devuelve la elegibilidad; con ambos, agrega la
    lista de reservas vivas que caen en el rango (para el aviso previo del modal).
    """
    uid = current_user["usuario_id"]
    tid = current_user["tenant_id"]
    usuario = db.query(Usuario).filter(
        Usuario.id == uid, Usuario.tenant_id == tid).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    suscripcion = _suscripcion_activa(db, tid, uid)
    if not suscripcion:
        return {
            "elegible": False,
            "motivo": suspensiones_service.MOTIVO_SIN_PLAN,
            "saldo_disponible": 0,
            "dias_para_vencimiento": 0,
            "periodos_usados": 0,
            "reservas_a_cancelar": [],
            "suspension_activa": None,
            "puede_cancelar": False,
        }

    resultado = _elegibilidad_para(db, usuario, suscripcion)
    resultado["reservas_a_cancelar"] = []
    if fecha_inicio is not None and dias is not None and dias > 0:
        resultado["reservas_a_cancelar"] = _reservas_en_rango(
            db, tid, uid, fecha_inicio, dias)

    # ── Cancelación anticipada: suspensión activa hoy + cupo anual ───────────
    suspension_activa = _suspension_activa_hoy(db, tid, uid)
    del_ciclo = _suspensiones_del_ciclo(db, usuario)
    resultado["suspension_activa"] = (
        {"id": suspension_activa.id,
         "origen": suspension_activa.origen,
         "fecha_inicio": str(suspension_activa.fecha_inicio),
         "fecha_fin": str(suspension_activa.fecha_fin),
         "dias": suspension_activa.dias}
        if suspension_activa else None
    )
    resultado["puede_cancelar"] = (
        suspension_activa is not None
        and suspensiones_service.puede_cancelar(del_ciclo)
    )
    return resultado


# ── Alumno: confirmar la suspensión ──────────────────────────────────────────
@router.post("/alumnos/me/suspension", status_code=201)
@limiter.limit(LIMIT_CRITICO)
def crear_suspension(
    request: Request,
    data: SuspensionCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Confirma la suspensión: crea el registro, extiende la expiración y cancela.

    Toca dinero/fechas de vencimiento, por eso va con `LIMIT_CRITICO` y toda la
    lógica dentro de UNA transacción (ver `services/suspensiones_service.py`).
    """
    uid = current_user["usuario_id"]
    tid = current_user["tenant_id"]
    usuario = db.query(Usuario).filter(
        Usuario.id == uid, Usuario.tenant_id == tid).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    suscripcion = _suscripcion_activa(db, tid, uid)
    if not suscripcion:
        raise HTTPException(status_code=400,
                            detail=suspensiones_service.MOTIVO_SIN_PLAN)

    try:
        suspension = suspensiones_service.crear_suspension(
            db, suscripcion, usuario, data.fecha_inicio, data.dias)
    except ReembolsoTransitorio:
        raise HTTPException(status_code=503, detail="Alta demanda, intenta de nuevo")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    reservas_canceladas = _reservas_canceladas_por_suspension(
        db, tid, uid, data.fecha_inicio, data.dias)
    return {
        "suspension": {
            "id": suspension.id,
            "fecha_inicio": str(suspension.fecha_inicio),
            "fecha_fin": str(suspension.fecha_fin),
            "dias": suspension.dias,
            "reservas_canceladas": suspension.reservas_canceladas,
        },
        "fecha_expiracion": str(suscripcion.fecha_expiracion),
        "reservas_canceladas": reservas_canceladas,
    }


# ── Alumno: cancelar una suspensión activa (fix del abuso en plan ilimitado) ──
@router.post("/alumnos/me/suspension/{suspension_id}/cancelar")
@limiter.limit(LIMIT_CRITICO)
def cancelar_suspension(
    suspension_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Cancela una suspensión activa y revierte `fecha_expiracion` a la original.

    Toca `fecha_expiracion` (dinero/duración del plan), por eso `LIMIT_CRITICO`.
    Sólo el dueño de la suspensión puede cancelarla (validado por `usuario_id` del
    token + `tenant_id`).
    """
    uid = current_user["usuario_id"]
    tid = current_user["tenant_id"]

    suspension = db.query(SuspensionPlan).filter(
        SuspensionPlan.id == suspension_id,
        SuspensionPlan.usuario_id == uid,
        SuspensionPlan.tenant_id == tid,
    ).first()
    if not suspension:
        raise HTTPException(status_code=404, detail="Suspensión no encontrada")

    suscripcion = db.query(Suscripcion).filter(
        Suscripcion.id == suspension.suscripcion_id,
        Suscripcion.usuario_id == uid,
        Suscripcion.tenant_id == tid,
    ).first()
    if not suscripcion:
        raise HTTPException(status_code=404, detail="Suscripción no encontrada")

    try:
        suscripcion = suspensiones_service.cancelar_suspension(db, suspension, suscripcion)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "suspension_id": suspension.id,
        "fecha_expiracion": str(suscripcion.fecha_expiracion),
    }


# ── Alumno: historial de SUS propias suspensiones ────────────────────────────
@router.get("/alumnos/me/suspensiones")
def mis_suspensiones(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Historial del alumno autenticado: período, días, fechas y estado.

    Reusa `_estado_suspension` (misma regla activa/futura/pasada que el admin) y le
    suma el caso `cancelada` (cuando `suspension.cancelada` es True), para que el
    alumno vea cuáles canceló sin duplicar la lógica de fechas.
    """
    uid = current_user["usuario_id"]
    tid = current_user["tenant_id"]
    suspensiones = (
        db.query(SuspensionPlan)
        .filter(SuspensionPlan.usuario_id == uid,
                SuspensionPlan.tenant_id == tid)
        .order_by(SuspensionPlan.fecha_inicio.desc())
        .all()
    )
    hoy = hoy_santiago()
    items = []
    for s in suspensiones:
        estado = "cancelada" if s.cancelada else _estado_suspension(s, hoy)
        items.append({
            "id": s.id,
            "origen": s.origen,
            "fecha_inicio": str(s.fecha_inicio),
            "fecha_fin": str(s.fecha_fin),
            "dias": s.dias,
            "estado": estado,
            "cancelada": bool(s.cancelada),
        })
    return items


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

    Filtros: búsqueda por nombre/email de alumno, estado calculado en el momento
    (activa/futura/pasada/cancelada), rango de `fecha_inicio` y, opcionalmente, UN alumno
    (`usuario_id`, lo usa la ficha para el resumen de solo lectura).
    """
    tid = current_user["tenant_id"]
    query = (
        db.query(SuspensionPlan, Usuario)
        .join(Usuario, SuspensionPlan.usuario_id == Usuario.id)
        .filter(SuspensionPlan.tenant_id == tid,
                SuspensionPlan.origen == suspensiones_service.ORIGEN_ALUMNO)
    )
    if buscar:
        like = f"%{buscar}%"
        query = query.filter(
            Usuario.nombre.ilike(like) | Usuario.correo.ilike(like))
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


