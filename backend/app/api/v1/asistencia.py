"""
Router del sistema de Asistencia + Hitos (Fase 1 y 2).

Coach (marcado de asistencia):
  GET  /clases-hoy                 — TODAS las clases de hoy (Santiago) que son del coach
                                     (pasadas, en curso y por venir), con los contadores de
                                     cada una; el admin ve el día completo del box
  GET  /clases/{clase_id}/alumnos  — reservas de la clase con datos del alumno
  POST /clases/{clase_id}/confirmar— confirmación BATCH (1 click) con auditoría
  GET  /historial?anio=&mes=       — el MES completo de SÓLO LECTURA (pantalla "Historial de
                                     Asistencia"): contadores por clase y alumnos de cada una.
                                     El coach ve lo suyo; el admin, el mes completo del box.
                                     No escribe nada: marcar sigue siendo el POST de arriba.

Alumno:
  GET  /mi-resumen                 — racha actual + % del mes en curso + próximo hito
  GET  /mis-hitos                  — logros alcanzados

El cierre de mes que hacía el webhook de n8n (POST /n8n/evaluar-mes,
eliminado en 2026-10) ahora lo dispara APScheduler
(app/services/scheduler.py).

Seguridad: tenant_id SIEMPRE del token JWT (patrón del resto de la API).
"""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.core.rate_limit import limiter
from app.core.dependencies import (
    get_current_user, get_current_coach, verificar_coach_disciplina,
)
from app.core.estados import da_acceso_hoy, no_cancelada   # "viva" = NOT IN (cancelled, cancelada)
from app.services import churn_service
from app.services.auditoria_service import registrar_auditoria
from app.models.clase import Clase
from app.models.reserva import Reserva, es_reserva_duplicada
from app.models.suscripcion import Suscripcion
from app.models.tenant import Tenant
from app.models.usuario import Usuario, RolUsuario
from app.models.disciplina import Disciplina
from app.utils.santiago import ahora_santiago, hoy_santiago, SANTIAGO
from app.schemas.asistencia import (ConfirmarAsistenciaRequest,
                                    PresenteSinReservaRequest)
from app.services import asistencia_service as svc
# `estado_clase` = estado de la clase (realizada/en curso/…) y `condicion_mis_clases` = la
# definición ÚNICA de "esta clase es del coach" (las 3 vías), compartida con /clases?coach_id=.
from app.services.clases_service import (
    condicion_mis_clases, es_mi_clase, estado_clase,
)

router = APIRouter()


def _exigir_alcance_coach(db, current_user: dict, clase, modo_emergencia: bool,
                          accion: str, tenant_id: int) -> None:
    """Candado del coach en la pestaña Asistencia: sólo SUS clases (o cobertura de emergencia).

    "Suya" es la MISMA definición que le arma la lista del día
    (`clases_service.es_mi_clase` = asignada a él, de su horario vigente o de una disciplina
    que dicta): si el panel le muestra la clase, tiene que poder abrirla y marcarla. Sin
    esto, la clase que le asignaron de otra disciplina aparecería en su pantalla y el clic
    caería en un 403.

    Cuando la clase NO es suya, se aplica el candado histórico por disciplina
    (`verificar_coach_disciplina`), que además es el que registra la cobertura de emergencia.
    El admin/administrador y las clases sin disciplina pasan sin chequeo (como antes).
    """
    if current_user.get("rol") != "coach" or not clase.disciplina_id:
        return
    if es_mi_clase(db, tenant_id, current_user["usuario_id"], clase.id):
        return
    verificar_coach_disciplina(
        coach_id=current_user["usuario_id"],
        disciplina_id=clase.disciplina_id,
        db=db,
        modo_emergencia=modo_emergencia,
        clase_id=clase.id,
        accion=accion,
        tenant_id=tenant_id,
    )


def _contadores_de_clases(db: Session, ids):
    """Contadores por clase de la pestaña Asistencia (UNA sola definición).

    Lo usan las dos pantallas que muestran lo mismo —`/clases-hoy` (el día) y `/historial`
    (el mes)— para que sus números no puedan discrepar:

      · `reservas_count` — reservas VIGENTES de la clase (las canceladas no cuentan);
      · `marcados_count` — las que YA están PRESENTES (`asistio = True`: el mismo dato con el
        que la tarjeta ancha del Resumen del coach cuenta el "ya marcaron");
      · `marcadas` — el set de clases con la asistencia CERRADA (TODAS sus reservas vigentes
        ya tienen su registro). La marca la escribe el Confirmar del panel (batch) y también
        el check-in por QR del alumno: ambos setean `reservas.asistencia_marcada_at`
        (`asistencia_via` distingue la vía). Se exige al menos una reserva vigente para que
        una clase vacía NO cuente como marcada por vacuidad (0 reservas = "no aplica", lo
        resuelve el front).

    "Faltan" NO viaja: es una resta (reservas menos marcados, o cupo menos marcados) y la
    hace el front con UNA sola cuenta en `utils/franjasAsistencia` / `utils/historialAsistencia`.
    """
    if not ids:
        return {}, {}, set()
    reservas_count = dict(db.query(Reserva.clase_id, func.count(Reserva.id)).filter(
        Reserva.clase_id.in_(ids),
        no_cancelada(Reserva.estado),
    ).group_by(Reserva.clase_id).all())
    marcados_count = dict(db.query(Reserva.clase_id, func.count(Reserva.id)).filter(
        Reserva.clase_id.in_(ids),
        no_cancelada(Reserva.estado),
        Reserva.asistio.is_(True),
    ).group_by(Reserva.clase_id).all())
    ESTADOS_VIGENTES = ("confirmada", "completada")
    con_reservas = {
        cid for (cid,) in db.query(Reserva.clase_id).filter(
            Reserva.clase_id.in_(ids),
            Reserva.estado.in_(ESTADOS_VIGENTES),
        ).distinct().all()
    }
    con_pendientes = {
        cid for (cid,) in db.query(Reserva.clase_id).filter(
            Reserva.clase_id.in_(ids),
            Reserva.estado.in_(ESTADOS_VIGENTES),
            Reserva.asistencia_marcada_at.is_(None),
        ).distinct().all()
    }
    return reservas_count, marcados_count, con_reservas - con_pendientes


# ── Coach: TODO su día (pasadas, en curso y por venir) ───────────────────────
@router.get("/clases-hoy")
def clases_hoy(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_coach),
):
    """Clases del día actual (America/Santiago) para el coach/admin.

    El COACH ve TODAS las clases de HOY que son suyas —pasadas, en curso y por venir—:
    es la misma pantalla con la que después marca la asistencia, así que recortar por
    hora escondía trabajo real (una clase de la mañana sin marcar desaparecía al mediodía)
    y una clase de las primeras horas nunca aparece si el coach entra más tarde.

    "Suya" son las TRES vías de `GET /clases/?coach_id=` (definición única en
    `clases_service.condicion_mis_clases`): asignada a él, de su horario vigente o de una
    disciplina que dicta. ANTES miraba sólo sus disciplinas y, con la lista vacía,
    devolvía [] — el coach con clases asignadas veía su pestaña Asistencia vacía.

    El admin/administrador ve el día completo del box (no cambia).
    """
    tenant_id = current_user["tenant_id"]
    rol = current_user.get("rol", "")
    hoy = hoy_santiago()

    query = db.query(Clase).filter(
        Clase.tenant_id == tenant_id,
        Clase.fecha == hoy,
        Clase.cancelada == False,
    )

    if rol == "coach":
        query = query.filter(condicion_mis_clases(current_user["usuario_id"]))

    clases = query.order_by(Clase.hora_inicio.asc()).all()

    ids = [c.id for c in clases]
    # Los contadores de la fila (reservas vigentes / ya presentes) y el set de clases con la
    # asistencia CERRADA salen del MISMO helper que usa `/historial` (una sola definición:
    # las dos pantallas muestran lo mismo y no pueden discrepar).
    counts, marcados_count, marcadas = _contadores_de_clases(db, ids)

    disc_ids_set = {c.disciplina_id for c in clases if c.disciplina_id}
    disc_map, disc_req = {}, {}
    if disc_ids_set:
        for d in db.query(Disciplina).filter(Disciplina.id.in_(disc_ids_set)).all():
            disc_map[d.id] = d.nombre
            disc_req[d.id] = bool(d.requiere_coach)

    # Nombre del coach de cada clase (None = "sin coach asignado": lo pinta el frontend).
    coach_ids = {c.coach_id for c in clases if c.coach_id}
    coach_map = {}
    if coach_ids:
        coach_map = {u.id: u.nombre for u in db.query(Usuario).filter(
            Usuario.id.in_(coach_ids)).all()}

    # El estado ("realizada" / "en_curso" / "proxima" / "cancelada") se evalúa con el MISMO
    # instante para todas las filas (definición única de `clases_service`).
    ahora_dt = ahora_santiago()

    return [
        {
            "id": c.id,
            "fecha": str(c.fecha),
            "hora_inicio": str(c.hora_inicio),
            "hora_fin": str(c.hora_fin),
            "disciplina_id": c.disciplina_id,
            "disciplina_nombre": disc_map.get(c.disciplina_id, "Clase"),
            "requiere_coach": disc_req.get(c.disciplina_id, False),
            "coach": coach_map.get(c.coach_id) if c.coach_id else None,
            "cupo_maximo": c.cupo_maximo,
            "cupo_original": c.cupo_original,
            "asistentes_confirmados": c.asistentes_confirmados,
            "reservas_count": counts.get(c.id, 0),
            "marcados_count": marcados_count.get(c.id, 0),
            "marcada": c.id in marcadas,
            "estado": estado_clase(c.fecha, c.hora_inicio, c.hora_fin, c.cancelada, ahora_dt),
        }
        for c in clases
    ]


# ── Coach + admin: HISTORIAL de un mes (sólo lectura) ────────────────────────
@router.get("/historial")
def historial_mes(
    anio: int = Query(..., ge=2000, le=2100, description="Año calendario (Chile)"),
    mes: int = Query(..., ge=1, le=12, description="Mes 1-12 del año pedido"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_coach),
):
    """Historial de asistencia de un MES completo (pantalla "Historial de Asistencia").

    Responde el mes entero en UNA llamada: el donut de cada día de la semana, la grilla del
    calendario y el detalle por bloque horario se dibujan con esto — abrir un día (o una
    franja de un día) NO vuelve a pegarle a la API. Cada clase viaja con su lista de alumnos
    (`asistio` incluido), que es lo único que el detalle diario necesita.

    Alcance por rol (mismo criterio que `/clases-hoy`, para que las dos pantallas del coach
    no puedan mostrar cosas distintas):
      · el COACH ve las clases del mes que son SUYAS —las TRES vías de
        `clases_service.condicion_mis_clases`: asignadas a él, de su horario vigente o de una
        disciplina que dicta—;
      · el admin/administrador ve el mes completo del box (sin filtro de coach).

    Sólo lectura: NO escribe ni marca nada (es el espejo de lo que ya pasó). Las clases
    CANCELADAS quedan fuera de los totales (igual que en `/clases-hoy`): una clase que no
    ocurrió no puede bajar el porcentaje de asistencia de su día.

    Los PORCENTAJES no viajan: salen de `presentes / cupos` con UNA sola cuenta en el front
    (`utils/historialAsistencia.js`, puro y con test propio), para no tener dos definiciones
    del mismo número. `fecha`, `hora_inicio` y `hora_fin` son los del backend, ya en hora de
    Chile: el front no convierte nada.
    """
    tenant_id = current_user["tenant_id"]
    rol = current_user.get("rol", "")

    # Rango del mes pedido en fechas de calendario (Chile). El último día se calcula sin
    # `calendar`: el día anterior al 1 del mes siguiente (o el 31 de diciembre).
    primer_dia = date(anio, mes, 1)
    ultimo_dia = (date(anio, 12, 31) if mes == 12
                  else date(anio, mes + 1, 1) - timedelta(days=1))

    query = db.query(Clase).filter(
        Clase.tenant_id == tenant_id,
        Clase.fecha >= primer_dia,
        Clase.fecha <= ultimo_dia,
        Clase.cancelada == False,
    )
    if rol == "coach":
        query = query.filter(condicion_mis_clases(current_user["usuario_id"]))

    clases = query.order_by(Clase.fecha.asc(), Clase.hora_inicio.asc()).all()

    ids = [c.id for c in clases]
    # Mismo helper que `/clases-hoy`: reservas vigentes, ya presentes y asistencia cerrada.
    reservas_count, marcados_count, marcadas = _contadores_de_clases(db, ids)

    # Las reservas del mes (sólo las vigentes) con el nombre del alumno: UNA consulta para
    # todas las clases y UNA para los nombres, en vez de una por clase al abrir un día.
    alumnos_por_clase = {}
    if ids:
        reservas = db.query(Reserva).filter(
            Reserva.clase_id.in_(ids),
            Reserva.tenant_id == tenant_id,
            no_cancelada(Reserva.estado),
        ).order_by(Reserva.created_at.asc()).all()
        alumno_ids = {r.alumno_id for r in reservas}
        nombres = {}
        if alumno_ids:
            for u in db.query(Usuario).filter(Usuario.id.in_(alumno_ids)).all():
                nombres[u.id] = u.nombre
        for r in reservas:
            alumnos_por_clase.setdefault(r.clase_id, []).append({
                "reserva_id": r.id,
                "alumno_id": r.alumno_id,
                "nombre": nombres.get(r.alumno_id, f"Alumno #{r.alumno_id}"),
                "asistio": bool(r.asistio),
            })

    disc_ids = {c.disciplina_id for c in clases if c.disciplina_id}
    disc_map = {}
    if disc_ids:
        disc_map = {d.id: d.nombre for d in db.query(Disciplina).filter(
            Disciplina.id.in_(disc_ids)).all()}

    coach_ids = {c.coach_id for c in clases if c.coach_id}
    coach_map = {}
    if coach_ids:
        coach_map = {u.id: u.nombre for u in db.query(Usuario).filter(
            Usuario.id.in_(coach_ids)).all()}

    # El estado (realizada / en_curso / próxima) se evalúa con el MISMO instante para todas
    # las filas, como en `/clases-hoy` (definición única de `clases_service`).
    ahora_dt = ahora_santiago()

    return {
        "anio": anio,
        "mes": mes,
        "desde": str(primer_dia),
        "hasta": str(ultimo_dia),
        # "coach" = sólo sus clases; "box" = el mes completo (admin/administrador).
        "alcance": "coach" if rol == "coach" else "box",
        "clases": [
            {
                "id": c.id,
                "fecha": str(c.fecha),
                "hora_inicio": str(c.hora_inicio),
                "hora_fin": str(c.hora_fin),
                "disciplina_id": c.disciplina_id,
                "disciplina_nombre": disc_map.get(c.disciplina_id, "Clase"),
                "coach": coach_map.get(c.coach_id) if c.coach_id else None,
                "cupo_maximo": c.cupo_maximo,
                "cupo_original": c.cupo_original,
                "reservas_count": reservas_count.get(c.id, 0),
                "marcados_count": marcados_count.get(c.id, 0),
                "marcada": c.id in marcadas,
                "estado": estado_clase(c.fecha, c.hora_inicio, c.hora_fin, c.cancelada, ahora_dt),
                "alumnos": alumnos_por_clase.get(c.id, []),
            }
            for c in clases
        ],
    }


# ── Coach: reservas de una clase para marcar ─────────────────────────────────
@router.get("/clases/{clase_id}/alumnos")
def alumnos_clase(
    clase_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_coach),
    modo_emergencia: bool = Query(
        False, description="Modo cobertura de emergencia"),
):
    """Reservas activas de la clase con nombre del alumno y asistio actual.

    El frontend muestra los checks marcados por defecto si la clase aún no
    fue marcada (marcada=False); si ya fue marcada, muestra los valores
    guardados."""
    tenant_id = current_user["tenant_id"]

    clase = db.query(Clase).filter(
        Clase.id == clase_id, Clase.tenant_id == tenant_id).first()
    if not clase:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clase no encontrada")

    # 🔒 FIX 2: el coach sólo abre reservas de SUS clases (las 3 vías de "mis clases").
    _exigir_alcance_coach(db, current_user, clase, modo_emergencia,
                          "ver_asistencia", tenant_id)

    reservas = db.query(Reserva).filter(
        Reserva.clase_id == clase_id,
        Reserva.tenant_id == tenant_id,
        no_cancelada(Reserva.estado),
    ).order_by(Reserva.created_at.asc()).all()

    alumno_ids = {r.alumno_id for r in reservas}
    nombres = {}
    if alumno_ids:
        for u in db.query(Usuario).filter(Usuario.id.in_(alumno_ids)).all():
            nombres[u.id] = u.nombre

    return {
        "clase_id": clase_id,
        "fecha": str(clase.fecha),
        "hora_inicio": str(clase.hora_inicio),
        "marcada": any(r.asistencia_marcada_at is not None for r in reservas),
        "reservas": [
            {
                "reserva_id": r.id,
                "alumno_id": r.alumno_id,
                "nombre": nombres.get(r.alumno_id, f"Alumno #{r.alumno_id}"),
                "asistio": bool(r.asistio),
            }
            for r in reservas
        ],
    }



# ── Coach: confirmación BATCH (1 click) ──────────────────────────────────────
@router.post("/clases/{clase_id}/confirmar")
def confirmar_asistencia(
    clase_id: int,
    body: ConfirmarAsistenciaRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_coach),
    modo_emergencia: bool = Query(
        False, description="Modo cobertura de emergencia"),
):
    """Confirma la asistencia de TODA la clase en una sola transacción.

    Valida la ventana de corrección (mismo día calendario en Chile, hasta las
    23:59:59) en el BACKEND — no solo ocultando botones en el frontend.
    Escribe reservas.asistio + columnas de auditoría (marcada_por/at/via='batch').
    Idempotente: repetir el mismo body es un no-op."""
    tenant_id = current_user["tenant_id"]

    clase = db.query(Clase).filter(
        Clase.id == clase_id, Clase.tenant_id == tenant_id).first()
    if not clase:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clase no encontrada")

    # ── VENTANA DE CORRECCIÓN (backend): mismo día calendario en Chile ──
    if clase.fecha != hoy_santiago():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La asistencia solo se puede marcar o corregir el mismo día de la clase "
                   "(hasta las 23:59 hora de Chile).")

    # 🔒 El coach sólo marca SUS clases (admin/administrador bypass).
    _exigir_alcance_coach(db, current_user, clase, modo_emergencia,
                          "confirmar_asistencia", tenant_id)

    if not body.asistencias:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se enviaron reservas para confirmar")

    reserva_ids = [i.reserva_id for i in body.asistencias]
    if len(set(reserva_ids)) != len(reserva_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reservas duplicadas en el request")

    reservas = db.query(Reserva).filter(
        Reserva.id.in_(reserva_ids),
        Reserva.clase_id == clase_id,
        Reserva.tenant_id == tenant_id,
        no_cancelada(Reserva.estado),
    ).all()

    if len(reservas) != len(set(reserva_ids)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Alguna reserva no pertenece a esta clase o fue cancelada")

    rol = current_user.get("rol", "")
    marcada_por = current_user["usuario_id"]
    via = "coach" if rol == "coach" else "admin"
    ahora = ahora_santiago()

    mapa = {r.id: r for r in reservas}
    for item in body.asistencias:
        r = mapa[item.reserva_id]
        r.asistio = item.asistio
        r.asistencia_marcada_por = marcada_por
        r.asistencia_marcada_at = ahora
        r.asistencia_via = "batch"

    db.commit()

    # ── Asistencias marcadas -> recalc del churn de cada alumno (segundo plano). ──
    for alumno_id in {r.alumno_id for r in reservas}:
        churn_service.programar_recalculo(background_tasks, tenant_id, alumno_id)

    return {
        "status": "ok",
        "clase_id": clase_id,
        "confirmados": len(body.asistencias),
        "via": via,
    }


# ── Staff: walk-in ("+ Agregar alumno sin reserva") ──────────────────────────
# El Resumen del coach agrega a alguien que NO reservó y lo deja presente. Hay DOS
# caminos y cada uno tiene UNA sola fuente de verdad:
#
#   * el alumno TIENE plan vigente con créditos → la pantalla usa lo que YA existe
#     (`POST /reservas` del staff —descuenta 1 crédito y lo audita— y
#     `PUT /reservas/{id}/asistencia` para dejarlo presente). Acá no se reimplementa
#     nada de dinero.
#   * el alumno NO tiene plan/créditos → `POST /clases/{id}/sin-reserva` registra la
#     PRESENCIA SIN CARGO (`tokens_gastados = 0`): no se le cobra y su historial lo
#     muestra con 0 créditos, que es la verdad (`historial_alumno_service`).
#
# `GET /clases/{id}/elegibles` existe para que el modal NO adivine la rama: entrega
# `puede_reservar` con el MISMO predicado que aplica `POST /reservas` (plan que da
# acceso hoy + créditos), así el coach ve de antemano si le va a descontar el crédito.
VIA_SIN_CARGO = "sin_cargo"   # `asistencia_via` (String(10)) del camino sin cobro


def _planes_que_dan_acceso(db: Session, tenant_id: int, alumno_ids) -> dict:
    """El mejor plan vigente de cada alumno, en UNA consulta (sin N+1).

    "Mejor" es el MISMO orden que usa `POST /reservas` para elegir la membresía que va
    a consumir: más créditos primero y, a igualdad, el que vence más tarde
    (`creditos_disponibles.desc().nulls_last()`, `fecha_expiracion DESC`).
    """
    mejores = {}
    if not alumno_ids:
        return mejores
    filas = db.query(Suscripcion).filter(
        Suscripcion.tenant_id == tenant_id,
        Suscripcion.usuario_id.in_(list(alumno_ids)),
        da_acceso_hoy(Suscripcion.estado, Suscripcion.fecha_expiracion),
    ).order_by(
        Suscripcion.creditos_disponibles.desc().nulls_last(),
        Suscripcion.fecha_expiracion.desc(),
    ).all()
    for s in filas:
        mejores.setdefault(s.usuario_id, s)   # el primero ya es el mejor
    return mejores


def _puede_reservar(plan) -> bool:
    """¿`POST /reservas` aceptaría a este alumno? (el predicado, no una copia).

    Plan que da acceso hoy + créditos. `creditos_disponibles = NULL` es un plan
    ILIMITADO (no un 0): la reserva sólo corta con `<= 0` cuando el número existe.
    """
    if plan is None:
        return False
    return plan.creditos_disponibles is None or plan.creditos_disponibles > 0


@router.get("/clases/{clase_id}/elegibles")
def alumnos_elegibles_clase(
    clase_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_coach),
    modo_emergencia: bool = Query(
        False, description="Modo cobertura de emergencia"),
):
    """Alumnos activos del box para el modal "Agregar alumno sin reserva".

    Lista a TODOS los alumnos activos del box, no sólo a los que ya entrenaron con
    este coach: el caso de uso es justamente alguien que NO está en la clase (la otra
    lista, `GET /fidelizacion/coach/{id}/alumnos`, sale de las reservas del coach y por
    eso nunca incluiría a quien nunca ha reservado). El candado de más abajo es el mismo
    que usa `/clases/{id}/alumnos`: un coach sólo abre esta lista para SUS clases.

    La búsqueda por nombre la hace la pantalla (el box tiene decenas de alumnos y la
    lista viaja completa una sola vez); si algún día crece, el lugar para filtrar es
    acá.
    """
    tenant_id = current_user["tenant_id"]

    clase = db.query(Clase).filter(
        Clase.id == clase_id, Clase.tenant_id == tenant_id).first()
    if not clase:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clase no encontrada")

    # 🔒 El coach sólo agrega gente a SUS clases (mismo candado de la pestaña Asistencia).
    _exigir_alcance_coach(db, current_user, clase, modo_emergencia,
                          "ver_alumnos_elegibles", tenant_id)

    alumnos = db.query(Usuario.id, Usuario.nombre).filter(
        Usuario.tenant_id == tenant_id,
        Usuario.rol == RolUsuario.alumno,
        Usuario.activo.is_(True),
        Usuario.estado == "activo",
    ).order_by(Usuario.nombre.asc()).all()

    planes = _planes_que_dan_acceso(db, tenant_id, [a.id for a in alumnos])
    presentes = {
        fila[0] for fila in db.query(Reserva.alumno_id).filter(
            Reserva.clase_id == clase_id,
            Reserva.tenant_id == tenant_id,
            no_cancelada(Reserva.estado),
        ).all()
    }

    def _fila(a) -> dict:
        plan = planes.get(a.id)
        return {
            "alumno_id": a.id,
            "nombre": a.nombre,
            "plan_vigente": plan is not None,
            "creditos": plan.creditos_disponibles if plan is not None else None,
            "ilimitado": plan is not None and plan.creditos_disponibles is None,
            "puede_reservar": _puede_reservar(plan),
            "ya_presente": a.id in presentes,
        }

    return {
        "clase_id": clase_id,
        "alumnos": [_fila(a) for a in alumnos],
    }


@router.post("/clases/{clase_id}/sin-reserva", status_code=status.HTTP_201_CREATED)
def registrar_presente_sin_reserva(
    clase_id: int,
    body: PresenteSinReservaRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_coach),
    modo_emergencia: bool = Query(
        False, description="Modo cobertura de emergencia"),
):
    """Deja PRESENTE a un alumno que no reservó, SIN cobrarle crédito (walk-in).

    Reglas, y por qué cada una:

      * MISMO DÍA de la clase (hasta las 23:59 de Chile): idéntico a `confirmar` y a
        `PUT /reservas/{id}/asistencia`. La asistencia es del día; el pasado no se
        reescribe ni con este atajo.
      * el alumno no puede tener ya una reserva VIVA en esa clase (400, el mismo texto
        que `POST /reservas`): su presencia se marca sobre esa reserva, no se duplica.
      * el alumno NO puede tener plan vigente con créditos (409): en ese caso el camino
        correcto es la reserva normal, que SÍ descuenta el crédito. Sin este candado,
        un clic de más le regalaría la clase al box.
      * el aforo se toma con el MISMO `UPDATE ... WHERE asistentes < cupo_maximo` de
        `POST /reservas` (atómico: sin overbooking ni carrera) y cuenta para
        `asistentes_confirmados`, igual que una reserva.
      * `tokens_gastados = 0`: no se le cobra nada. Es la verdad que muestra su
        historial ("0 créditos"), no un descuento escondido.
    """
    tenant_id = current_user["tenant_id"]

    clase = db.query(Clase).filter(
        Clase.id == clase_id, Clase.tenant_id == tenant_id).first()
    if not clase:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Clase no encontrada")
    if clase.cancelada:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La clase fue cancelada por el box")
    if clase.fecha != hoy_santiago():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La asistencia solo se puede marcar o corregir el mismo día de la clase "
                   "(hasta las 23:59 hora de Chile).")

    # 🔒 El coach sólo agrega gente a SUS clases (mismo candado de la pestaña Asistencia).
    _exigir_alcance_coach(db, current_user, clase, modo_emergencia,
                          "asistencia_sin_reserva", tenant_id)
    # El rol va a la auditoría de más abajo (`creada_por_rol`): coach = agregó a alguien sin
    # cargo, admin = lo hizo el box.
    rol = current_user.get("rol", "")

    alumno = db.query(Usuario).filter(
        Usuario.id == body.alumno_id,
        Usuario.tenant_id == tenant_id,
        Usuario.rol == RolUsuario.alumno,
    ).first()
    if not alumno:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Alumno no encontrado")

    ya_esta = db.query(Reserva).filter(
        Reserva.clase_id == clase_id,
        Reserva.alumno_id == alumno.id,
        no_cancelada(Reserva.estado),
    ).first()
    if ya_esta:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El alumno ya tiene una reserva activa para esta clase")

    plan = _planes_que_dan_acceso(db, tenant_id, [alumno.id]).get(alumno.id)
    if _puede_reservar(plan):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=("Este alumno tiene plan vigente con créditos: agrégalo como reserva "
                    "normal (se le descuenta 1 crédito) en vez de presencia sin cargo."))

    # Aforo ATÓMICO (mismo patrón que POST /reservas): si la clase se llenó entre la
    # lectura y este UPDATE, rowcount=0 -> 400 y NO se escribe la presencia.
    # Migración 066: `cupo_maximo IS NULL` = sin tope (Musculación / Open Box); el
    # `OR` deja entrar siempre y el contador igual sube.
    try:
        resultado = db.execute(
            update(Clase)
            .where(Clase.id == clase.id)
            .where(or_(
                Clase.cupo_maximo.is_(None),
                Clase.asistentes_confirmados < Clase.cupo_maximo,
            ))
            .values(asistentes_confirmados=Clase.asistentes_confirmados + 1)
        )
    except DBAPIError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Alta demanda, intenta de nuevo")
    if resultado.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Clase sin cupos disponibles")

    reserva = Reserva(
        tenant_id=tenant_id,
        clase_id=clase_id,
        alumno_id=alumno.id,
        asistio=True,              # el punto del walk-in: entra PRESENTE
        tokens_gastados=0,         # sin cargo
        estado="confirmada",
        asistencia_marcada_por=current_user["usuario_id"],
        asistencia_marcada_at=ahora_santiago(),
        asistencia_via=VIA_SIN_CARGO,
    )
    db.add(reserva)
    try:
        db.commit()
    except IntegrityError as error:
        # Misma carrera que POST /reservas: dos marcados simultáneos del mismo
        # alumno (dos coaches, o el coach y el admin) pasan el SELECT de
        # duplicados a la vez; el índice único parcial de la migración 057
        # rechaza el segundo. El rollback devuelve el aforo de ESTE request.
        db.rollback()
        if not es_reserva_duplicada(error):
            raise
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El alumno ya tiene una reserva activa para esta clase")
    db.refresh(reserva)

    # ── Presencia marcada -> su situación de churn cambió -> recalc (segundo plano). ──
    churn_service.programar_recalculo(background_tasks, tenant_id, alumno.id)

    # Trazabilidad: dar por presente a alguien que no reservó es una acción sensible del
    # box (mueve el aforo y la asistencia sin cobro): mismo criterio que la reserva "en
    # nombre de" de N-9.
    registrar_auditoria(
        db,
        tenant_id=tenant_id,
        usuario_id=current_user["usuario_id"],
        accion="CREATE",
        entidad="reserva",
        entidad_id=reserva.id,
        detalle={
            "alumno_id": alumno.id,
            "clase_id": clase_id,
            "origen": "sin_reserva",
            "tokens_gastados": 0,
            "creada_por_rol": rol,
        },
    )

    return {
        "reserva_id": reserva.id,
        "alumno_id": alumno.id,
        "nombre": alumno.nombre,
        "asistio": True,
        "cargo": "sin_cargo",
    }


# ── Alumno: resumen y hitos ──────────────────────────────────────────────────
@router.get("/mi-resumen")
def mi_resumen(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Racha actual, % del mes en curso y próximo hito del alumno autenticado."""
    tenant_id = current_user["tenant_id"]
    usuario_id = current_user["usuario_id"]
    return svc.resumen_alumno(db, usuario_id, tenant_id)


@router.get("/mis-hitos")
def mis_hitos(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Logros (hitos) alcanzados por el alumno autenticado."""
    tenant_id = current_user["tenant_id"]
    usuario_id = current_user["usuario_id"]
    return {"hitos": svc.hitos_alumno_list(db, usuario_id, tenant_id)}


# ── Alumno: check-in por QR (autoescaneo) ────────────────────────────────────
# Ventana confirmada: el alumno puede marcar desde 60 MINUTOS ANTES del inicio
# de su clase hasta que esta termina (America/Santiago). No se crea reserva de
# emergencia si no tiene una en curso; coach/admin siguen como respaldo.
QR_VENTANA_PREVIA_MIN = 60
RESERVA_ESTADOS_CHECKIN = ("confirmada", "completada")


@router.post("/qr/{public_id}/check-in")
@limiter.limit("30/minute")
def qr_checkin_alumno(
    request: Request,
    public_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Auto check-in del alumno escaneando el QR fijo del box.

    - Requiere JWT con rol 'alumno'. El public_id debe pertenecer al tenant
      del token (403 si es de otro box). public_id inexistente → 404 genérico.
    - Busca la reserva EN CURSO del alumno (hora_inicio - 60 min <= ahora
      < hora_fin, America/Santiago).
        * Exactamente 1 sin marcar → marca con asistencia_via='qr_alumno'.
        * Más de 1 en curso → 'ambiguo' (no marca; hablar con el coach).
        * 1 ya marcada     → 'ya_marcado' (idempotente, no re-escribe).
        * 0 en curso       → 'sin_reserva' (NO crea reserva de emergencia).
    - NO toca créditos (el token ya se descontó al reservar).
    """
    rol = current_user.get("rol", "")
    if rol != "alumno":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El check-in por QR es solo para alumnos",
        )

    tenant = db.query(Tenant).filter(Tenant.public_id == public_id).first()
    if not tenant:
        # 404 genérico: no revelar si el ID "casi" existe (mismo patrón que ranking).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No encontrado",
        )
    if tenant.id != current_user.get("tenant_id"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El QR pertenece a otro box",
        )

    ahora = ahora_santiago()
    hoy = ahora.date()
    # La ventana de -60 min puede caer en el día calendario anterior a la clase,
    # así que se buscan clases del alumno desde ayer hasta mañana.
    desde = hoy - timedelta(days=1)
    hasta = hoy + timedelta(days=1)

    filas = (
        db.query(Reserva, Clase)
        .join(Clase, Reserva.clase_id == Clase.id)
        .filter(
            Reserva.tenant_id == tenant.id,
            Reserva.alumno_id == current_user["usuario_id"],
            Reserva.estado.in_(RESERVA_ESTADOS_CHECKIN),
            Clase.cancelada == False,  # noqa: E712
            Clase.fecha >= desde,
            Clase.fecha <= hasta,
        )
        .all()
    )

    def _en_ventana(r: Reserva, c: Clase) -> bool:
        ini = (datetime.combine(c.fecha, c.hora_inicio, SANTIAGO)
               - timedelta(minutes=QR_VENTANA_PREVIA_MIN))
        fin = datetime.combine(c.fecha, c.hora_fin, SANTIAGO)
        return ini <= ahora < fin

    en_curso = [(r, c) for r, c in filas if _en_ventana(r, c)]

    if len(en_curso) > 1:
        return {
            "estado": "ambiguo",
            "mensaje": "Tienes más de una clase en curso ahora. "
                       "Habla con tu coach para registrar la correcta.",
            "reserva_ids": [r.id for r, _ in en_curso],
        }

    if len(en_curso) == 1:
        r, c = en_curso[0]
        if r.asistencia_marcada_at is not None:
            return {
                "estado": "ya_marcado",
                "mensaje": "Ya registramos tu asistencia a esta clase.",
                "reserva_id": r.id,
                "disciplina": c.disciplina_id,
            }
        # Marcar asistencia con la misma auditoría que coach/admin/batch.
        r.asistio = True
        r.asistencia_marcada_por = current_user["usuario_id"]
        r.asistencia_marcada_at = ahora
        r.asistencia_via = "qr_alumno"
        db.commit()
        # ── Marcó asistencia por QR -> recalc del churn del alumno (segundo plano). ──
        churn_service.programar_recalculo(
            background_tasks, tenant.id, current_user["usuario_id"])
        return {
            "estado": "ok",
            "mensaje": "✅ Asistencia registrada. ¡Buen entrenamiento!",
            "reserva_id": r.id,
            "disciplina": c.disciplina_id,
        }

    return {
        "estado": "sin_reserva",
        "mensaje": "No tienes reserva para este horario, habla con tu coach.",
    }

