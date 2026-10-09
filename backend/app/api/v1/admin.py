"""Router de endpoints de administración (tarjetas/notificaciones del panel admin)."""
from datetime import datetime, time

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.core.dependencies import get_current_admin
from app.core.estados import da_acceso_hoy, plan_comercial
from app.models.notificacion_enviada import NotificacionEnviada
from app.models.usuario import Usuario, RolUsuario
from app.models.suscripcion import Suscripcion
from app.models.plan import Plan
from app.models.reserva import Reserva
from app.models.clase import Clase
from app.models.disciplina import Disciplina
from app.utils.santiago import SANTIAGO, fecha_chile, hoy_santiago
# Bordes del mes del KPI "alumnos nuevos": UNA sola definición (la de reportes).
from app.api.v1.reportes import _inicio_fin_mes
# Dedupe ATÓMICO del envío manual: la misma pieza que usan las alertas del scheduler
# (índice único parcial por alumno + tipo + día chileno), pero REABRIENDO la fila si
# el intento del mismo día falló (si no, el admin no podría reintentar hasta mañana).
# Se importan las privadas a propósito: duplicar el INSERT ... ON CONFLICT sería la
# forma de que las dos copias se desincronicen.
from app.services.alertas_email_service import (
    _marcar_fallido, reclamar_envio_manual,
)
from app.services.auditoria_service import registrar_auditoria
from app.services import email_service
from app.services.email_service import (
    render_con_contacto, render_email_clase_prueba, render_email_contratar_plan,
    send_clase_prueba, send_contratar_plan,
)

router = APIRouter()

# Correos MANUALES del panel para los alumnos en prueba: un tipo por ESTADO, para
# que el registro de envíos no se mezcle con las alertas del scheduler. La clave es
# el `estado` de `estado_prueba()`.
TIPOS_PRUEBA_MANUAL = {
    "sin_clase": "prueba_clase_manual",
    "sin_plan": "prueba_plan_manual",
}


@router.get("/alumnos-prueba-hoy")
def get_alumnos_prueba_hoy(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Alumnos con plan "Prueba" registrados HOY. Solo admins.

    - `get_current_admin` ya restringe a rol administrador (403 si no lo es).
    - "Hoy" se calcula en hora de Chile (America/Santiago) y se compara contra
      `usuarios.created_at` (TIMESTAMPTZ), por lo que es correcto aunque el
      servidor corra en UTC.

    Retorna: {total, alumnos: [{id, nombre, correo, hora_registro, plan,
    estado_suscripcion, creditos_disponibles, clase_tomada}]}.

    `clase_tomada` = última reserva con estado 'confirmada' del alumno:
    {disciplina, fecha, horario, coach} o None si aún no reservó clase.
    """
    tenant_id = current_user["tenant_id"]

    # Inicio del día de HOY en hora de Chile (tz-aware) → comparable con created_at.
    inicio_hoy = datetime.combine(hoy_santiago(), time.min, tzinfo=SANTIAGO)

    filas = (
        db.query(Usuario, Suscripcion)
        .join(Suscripcion, Suscripcion.usuario_id == Usuario.id)
        .join(Plan, Plan.id == Suscripcion.plan_id)
        .filter(
            Usuario.tenant_id == tenant_id,
            Usuario.rol == RolUsuario.alumno,
            Plan.tenant_id == tenant_id,
            Plan.nombre == "Prueba",
            Usuario.created_at >= inicio_hoy,
        )
        .order_by(Usuario.created_at.desc())
        .all()
    )

    # Deduplicar por alumno (por si hubiera >1 suscripción "Prueba"): la más reciente.
    vistos = set()
    alumnos = []
    for usuario, sus in filas:
        if usuario.id in vistos:
            continue
        vistos.add(usuario.id)
        alumnos.append({
            "id": usuario.id,
            "nombre": usuario.nombre,
            "correo": usuario.correo,
            "hora_registro": usuario.created_at.isoformat() if usuario.created_at else None,
            "plan": "Prueba",
            "estado_suscripcion": sus.estado,
            "creditos_disponibles": sus.creditos_disponibles,
        })

    # ── Última clase reservada (estado 'confirmada') de cada alumno ──────────
    # Sin relaciones ORM: JOIN manual Reserva→Clase→(Disciplina, Usuario coach).
    ids = [a["id"] for a in alumnos]
    ultima_clase = {}
    if ids:
        filas_res = (
            db.query(Reserva.alumno_id, Clase.fecha, Clase.hora_inicio,
                     Disciplina.nombre, Usuario.nombre)
            .join(Clase, Clase.id == Reserva.clase_id)
            .outerjoin(Disciplina, Disciplina.id == Clase.disciplina_id)
            .outerjoin(Usuario, Usuario.id == Clase.coach_id)
            .filter(
                Reserva.tenant_id == tenant_id,
                Reserva.alumno_id.in_(ids),
                Reserva.estado == "confirmada",
            )
            .order_by(Reserva.alumno_id, Clase.fecha.desc(),
                      Clase.hora_inicio.desc())
            .all()
        )
        for alumno_id, fecha, hora_inicio, disc_nombre, coach_nombre in filas_res:
            if alumno_id in ultima_clase:
                continue  # ya se guardó la más reciente (ordenado desc)
            ultima_clase[alumno_id] = {
                "disciplina": disc_nombre or "Sin disciplina",
                "fecha": fecha.isoformat() if fecha else None,
                "horario": hora_inicio.strftime("%H:%M") if hora_inicio else None,
                "coach": coach_nombre or "Sin asignar",
            }

    for a in alumnos:
        a["clase_tomada"] = ultima_clase.get(a["id"])

    return {"total": len(alumnos), "alumnos": alumnos}


# ═══════════════════════════════════════════════════════════════════════════════
#  TARJETA "ALUMNOS NUEVOS Y EN PRUEBA" (dashboard admin móvil <768px)
#
#  Dos listados para la misma tarjeta:
#    * "En prueba"  -> alumnos con el crédito de PRUEBA vigente: los que todavía no
#      tomaron la clase (🟡) y los que ya la tomaron sin contratar plan (🔵);
#    * "Nuevos del mes" -> los dados de alta en el mes en curso, con la MISMA
#      definición que el KPI del Dashboard ≥768px.
#
#  OJO: `get_alumnos_prueba_hoy` (arriba) NO se toca. Es el banner del panel de
#  escritorio ("X alumnos de prueba hoy") y su criterio es el de HOY: cambiarlo
#  alteraría una pantalla ≥768px, que queda igual que siempre.
# ═══════════════════════════════════════════════════════════════════════════════

def dias_desde_inscripcion(created_at, hoy=None) -> int:
    """Días (de CHILE) desde el alta del alumno: 0 = se inscribió hoy.

    Se cuentan DÍAS CHILENOS, no horas: un alta de las 21:30 CLT es "hoy" aunque en
    UTC ya sea mañana (mismo criterio que el resto del panel). Sin fecha -> 0, que es
    el lado honesto: nunca un número inventado.
    """
    dia_alta = fecha_chile(created_at)
    if dia_alta is None:
        return 0
    return max(0, ((hoy or hoy_santiago()) - dia_alta).days)


def estado_prueba(asistio_prueba: bool, tiene_plan_vigente: bool) -> str:
    """Estado del alumno en prueba (lo que pinta el panel móvil):

      'sin_clase'  -> 🟡 se inscribió y AÚN no tiene asistencia marcada con su crédito;
      'sin_plan'   -> 🔵 ya tomó la clase de prueba y sigue sin plan vigente;
      'convertido' -> ya tiene un plan vigente: contrató, así que la pantalla no lo
                      lista (sólo invita a los dos casos de arriba).
    """
    if tiene_plan_vigente:
        return "convertido"
    return "sin_plan" if asistio_prueba else "sin_clase"




def _suscripciones_prueba(db: Session, tenant_id: int):
    """`(Usuario, Suscripcion)` del plan "Prueba" con el crédito VIGENTE hoy.

    Se ordena para que la primera fila de cada alumno sea la de prueba que está
    corriendo (puede haber más de una suscripción "Prueba" histórica). La vigencia
    usa `da_acceso_hoy` (día de Chile: el día de vencimiento vale completo), igual
    que el resto del sistema.
    """
    return (
        db.query(Usuario, Suscripcion)
        .join(Suscripcion, Suscripcion.usuario_id == Usuario.id)
        .join(Plan, Plan.id == Suscripcion.plan_id)
        .filter(
            Usuario.tenant_id == tenant_id,
            Usuario.rol == RolUsuario.alumno,
            Plan.tenant_id == tenant_id,
            Plan.nombre == "Prueba",
            da_acceso_hoy(Suscripcion.estado, Suscripcion.fecha_expiracion,
                          Suscripcion.fecha_inicio),
        )
        .order_by(Usuario.id, Suscripcion.fecha_inicio.desc(), Suscripcion.id.desc())
        .all()
    )


def _alumnos_con_asistencia_de_prueba(db: Session, tenant_id: int, alumno_ids: list,
                                      inicio_prueba: dict) -> set:
    """Ids de los alumnos que YA tienen asistencia marcada con su crédito de prueba.

    La marca es `reservas.asistio = true` (la MISMA que usa todo el panel: reservar
    NO es asistir; `asistencias` es el histórico agregado) sobre una clase que cae
    DENTRO del período de la prueba (desde su `fecha_inicio`).
    """
    if not alumno_ids:
        return set()
    filas = (
        db.query(Reserva.alumno_id, Clase.fecha)
        .join(Clase, Clase.id == Reserva.clase_id)
        .filter(
            Reserva.tenant_id == tenant_id,
            Reserva.alumno_id.in_(alumno_ids),
            Reserva.asistio.is_(True),
        )
        .all()
    )
    asistieron = set()
    for alumno_id, fecha_clase in filas:
        if fecha_clase is None:
            continue
        inicio = inicio_prueba.get(alumno_id)
        # Sin `fecha_inicio` cargada (la columna es NULL-able en la BD real) cualquier
        # asistencia vale: es preferible clasificarlo como "ya fue" que afirmar que no
        # tomó una clase que sí tomó.
        if inicio is None or fecha_clase >= inicio:
            asistieron.add(alumno_id)
    return asistieron


def _alumnos_con_plan_vigente(db: Session, tenant_id: int, alumno_ids: list) -> set:
    """Ids con un plan COMERCIAL vigente hoy: ya se convirtieron en clientes.

    `plan_comercial` deja fuera el "Pase de regreso" y el propio plan "Prueba" (un
    regalo no es una membresía de cliente). La vigencia es el día de Chile.
    """
    if not alumno_ids:
        return set()
    filas = (
        db.query(Suscripcion.usuario_id)
        .join(Plan, Plan.id == Suscripcion.plan_id)
        .filter(
            Suscripcion.tenant_id == tenant_id,
            Suscripcion.usuario_id.in_(alumno_ids),
            Plan.nombre != "Prueba",
            plan_comercial(Plan.es_comercial),
            da_acceso_hoy(Suscripcion.estado, Suscripcion.fecha_expiracion,
                          Suscripcion.fecha_inicio),
        )
        .all()
    )
    return {fila[0] for fila in filas}


def _ultimos_envios_manuales(db: Session, alumno_ids: list, tipos=None) -> dict:
    """`{alumno_id: 'YYYY-MM-DDTHH:MM:SS'}` del ÚLTIMO correo MANUAL enviado.

    Una sola consulta (GROUP BY) para toda la lista: alimenta el "Correo enviado
    hace X" de cada fila. Sólo cuenta `estado = 'enviado'`: una fila `fallido` NO es
    un envío (el correo no salió).
    """
    if not alumno_ids:
        return {}
    tipos = tipos or tuple(TIPOS_PRUEBA_MANUAL.values())
    filas = (
        db.query(NotificacionEnviada.alumno_id,
                 func.max(NotificacionEnviada.fecha_envio))
        .filter(
            NotificacionEnviada.alumno_id.in_(alumno_ids),
            NotificacionEnviada.tipo.in_(tipos),
            NotificacionEnviada.estado == "enviado",
        )
        .group_by(NotificacionEnviada.alumno_id)
        .all()
    )
    return {alumno_id: (fecha.isoformat() if fecha else None)
            for alumno_id, fecha in filas}


@router.get("/alumnos-prueba")
def get_alumnos_en_prueba(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Alumnos con el crédito de PRUEBA vigente, con su estado (panel móvil <768px).

    - `estado` = `estado_prueba()`: `sin_clase` (🟡 todavía no tomó la clase) o
      `sin_plan` (🔵 la tomó y sigue sin plan). Los `convertido` no se listan.
    - `dias_inscrito` = días de CHILE desde el alta (`dias_desde_inscripcion`).
    - `ultimo_envio` = fecha del último correo MANUAL de prueba (o None): es el
      "Correo enviado hace X" de la fila.
    - `total` / `sin_clase` / `sin_plan` cuentan lo MISMO que `alumnos` (el panel no
      suma a los convertidos).

    Tres consultas con IN para toda la página (asistencia, plan vigente y envíos
    manuales): nunca una por alumno.
    """
    tenant_id = current_user["tenant_id"]
    filas = _suscripciones_prueba(db, tenant_id)

    alumnos, ids, inicio_prueba = [], [], {}
    for usuario, sus in filas:
        if usuario.id in inicio_prueba:
            continue  # ya quedó la suscripción de prueba más reciente
        inicio_prueba[usuario.id] = fecha_chile(sus.fecha_inicio)
        ids.append(usuario.id)
        alumnos.append({
            "id": usuario.id,
            "nombre": usuario.nombre,
            "correo": usuario.correo,
            "fecha_alta": usuario.created_at.isoformat() if usuario.created_at else None,
            "dias_inscrito": dias_desde_inscripcion(usuario.created_at),
            "creditos_disponibles": sus.creditos_disponibles,
        })

    asistieron = _alumnos_con_asistencia_de_prueba(db, tenant_id, ids, inicio_prueba)
    convertidos = _alumnos_con_plan_vigente(db, tenant_id, ids)
    ultimos = _ultimos_envios_manuales(db, ids)

    listados = []
    for alumno in alumnos:
        alumno["asistio_prueba"] = alumno["id"] in asistieron
        alumno["estado"] = estado_prueba(alumno["asistio_prueba"],
                                        alumno["id"] in convertidos)
        alumno["ultimo_envio"] = ultimos.get(alumno["id"])
        if alumno["estado"] != "convertido":
            listados.append(alumno)

    return {
        "total": len(listados),
        "sin_clase": sum(1 for a in listados if a["estado"] == "sin_clase"),
        "sin_plan": sum(1 for a in listados if a["estado"] == "sin_plan"),
        "alumnos": listados,
    }


@router.get("/alumnos-nuevos")
def get_alumnos_nuevos(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Alumnos dados de alta en el MES EN CURSO, con su fecha de alta.

    Reutiliza `_inicio_fin_mes()` de `reportes`: son los MISMOS bordes de mes que
    cuenta `nuevosAlumnosMes` (el "+N nuevos este mes" del KPI "Alumnos activos"),
    así el listado y el número no pueden decir cosas distintas.
    """
    tenant_id = current_user["tenant_id"]
    inicio, fin = _inicio_fin_mes()

    filas = (
        db.query(Usuario.id, Usuario.nombre, Usuario.correo, Usuario.created_at)
        .filter(
            Usuario.tenant_id == tenant_id,
            Usuario.rol == RolUsuario.alumno,
            Usuario.created_at >= inicio,
            Usuario.created_at <= fin,
        )
        .order_by(Usuario.created_at.desc(), Usuario.id.desc())
        .all()
    )

    return {
        "total": len(filas),
        "desde": inicio.isoformat(),
        "hasta": fin.isoformat(),
        "alumnos": [{
            "id": fila.id,
            "nombre": fila.nombre,
            "correo": fila.correo,
            "fecha_alta": fila.created_at.isoformat() if fila.created_at else None,
        } for fila in filas],
    }



# ── Invitación MANUAL por correo (preview + envío) ───────────────────────────
def _alumno_prueba_para_invitar(db: Session, current_user: dict, alumno_id: int):
    """Guards comunes del preview y del envío: `(alumno, estado, dias_inscrito)`.

    El alumno tiene que ser del box del token y tener el crédito de prueba VIGENTE.
    Si ya contrató ('convertido') se corta acá: la invitación de prueba no
    corresponde y el panel no debe poder mandarla (mismo espíritu que el candado de
    las plantillas de Fidelización, que no mandan un correo que los datos no
    respaldan).
    """
    tenant_id = current_user["tenant_id"]
    alumno = (
        db.query(Usuario)
        .filter(Usuario.id == alumno_id, Usuario.tenant_id == tenant_id,
                Usuario.rol == RolUsuario.alumno)
        .first()
    )
    if not alumno:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alumno {alumno_id} no encontrado en este box",
        )
    if not alumno.correo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El alumno no tiene correo registrado: no hay a dónde mandar la invitación",
        )

    sus = (
        db.query(Suscripcion)
        .join(Plan, Plan.id == Suscripcion.plan_id)
        .filter(
            Suscripcion.usuario_id == alumno.id,
            Suscripcion.tenant_id == tenant_id,
            Plan.nombre == "Prueba",
            da_acceso_hoy(Suscripcion.estado, Suscripcion.fecha_expiracion,
                          Suscripcion.fecha_inicio),
        )
        .order_by(Suscripcion.fecha_inicio.desc(), Suscripcion.id.desc())
        .first()
    )
    if not sus:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El alumno no tiene el crédito de prueba vigente",
        )

    inicio = {alumno.id: fecha_chile(sus.fecha_inicio)}
    asistio = alumno.id in _alumnos_con_asistencia_de_prueba(db, tenant_id,
                                                            [alumno.id], inicio)
    convertido = alumno.id in _alumnos_con_plan_vigente(db, tenant_id, [alumno.id])
    estado = estado_prueba(asistio, convertido)
    if estado == "convertido":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El alumno ya tiene un plan vigente: no corresponde la invitación de prueba",
        )
    return alumno, estado, dias_desde_inscripcion(alumno.created_at)


@router.get("/alumnos-prueba/{alumno_id}/invitacion/preview")
def preview_invitacion_prueba(
    alumno_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Vista previa del correo manual: el asunto y el HTML EXACTOS que se mandan.

    GET sin efectos: no manda ni registra nada. Usa las MISMAS funciones de render
    que el envío real (como el preview del panel coach), así el modal no puede
    mostrar algo distinto de lo que sale.
    """
    alumno, estado, dias = _alumno_prueba_para_invitar(db, current_user, alumno_id)

    if estado == "sin_clase":
        asunto, html = render_email_clase_prueba(alumno.nombre, dias)
    else:
        asunto, html = render_email_contratar_plan(alumno.nombre)
    # El pie del box se resuelve con la MISMA conexión del request (ver
    # email_service.contacto_del_box): abrir otra dejaba al handler esperando el pool.
    html = render_con_contacto(html, current_user["tenant_id"], db=db)

    return {
        "alumno_id": alumno.id,
        "nombre": alumno.nombre,
        "destinatario": alumno.correo,
        "asunto": asunto,
        "html": html,
        "estado": estado,
        "tipo": TIPOS_PRUEBA_MANUAL[estado],
        "dias_inscrito": dias,
        "ultimo_envio": _ultimos_envios_manuales(db, [alumno.id]).get(alumno.id),
    }



@router.post("/alumnos-prueba/{alumno_id}/invitacion")
def enviar_invitacion_prueba(
    alumno_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Manda la invitación manual (un correo por alumno + tipo + día).

    El estado lo decide el BACKEND (el mismo `estado_prueba()` que pinta la lista):
    el correo que sale es el que corresponde al dato, sin que el cliente pueda pedir
    la plantilla equivocada.

    Dedupe: `_reclamar_envio` reclama la fila de HOY con el índice único parcial
    `(alumno_id, tipo, dia_chile)` — la MISMA pieza que usan las alertas del
    scheduler, pero con un `tipo` PROPIO (`*_manual`): no bloquea ni cuenta como
    alerta automática. Si ya se mandó hoy no se manda de nuevo y se devuelve la hora
    del envío (`ya_enviado: true`) para que la fila diga "Correo enviado hace X".
    """
    alumno, estado, dias = _alumno_prueba_para_invitar(db, current_user, alumno_id)
    tenant_id = current_user["tenant_id"]
    tipo = TIPOS_PRUEBA_MANUAL[estado]

    envio_id = reclamar_envio_manual(db, alumno.id, tipo, tenant_id=tenant_id)
    if envio_id is None:
        return {
            "exito": True,
            "ya_enviado": True,
            "estado": "enviado",
            "detalle_error": None,
            "tipo": tipo,
            "estado_prueba": estado,
            "dias_inscrito": dias,
            "enviado_en": _ultimos_envios_manuales(db, [alumno.id]).get(alumno.id),
        }

    if estado == "sin_clase":
        exito = send_clase_prueba(alumno.nombre, alumno.correo, dias, registrar=False)
    else:
        exito = send_contratar_plan(alumno.nombre, alumno.correo, registrar=False)

    detalle_error = None
    if not exito:
        detalle_error = email_service.ULTIMO_ERROR_SMTP or (
            "No se pudo enviar el correo (revisar SMTP y el correo del alumno).")
        _marcar_fallido(db, envio_id, f"{tipo} FALLIDO -> {alumno.correo}")

    registrar_auditoria(
        db,
        tenant_id=tenant_id,
        usuario_id=current_user["usuario_id"],
        accion="EMAIL_MANUAL",
        entidad="usuario",
        entidad_id=alumno.id,
        detalle={"tipo": tipo, "estado_prueba": estado, "dias_inscrito": dias,
                 "exito": exito, "origen": "panel_admin_movil"},
    )

    return {
        "exito": exito,
        "ya_enviado": False,
        "estado": "enviado" if exito else "fallido",
        "detalle_error": detalle_error,
        "tipo": tipo,
        "estado_prueba": estado,
        "dias_inscrito": dias,
        "enviado_en": (_ultimos_envios_manuales(db, [alumno.id]).get(alumno.id)
                       if exito else None),
    }

