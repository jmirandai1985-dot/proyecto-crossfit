"""
Asignación de coach a clases y horarios (Supervisión + panel del coach).

Reglas de negocio que vive este módulo (ver `docs/SUPERVISION_CLASES.md`):

  * la fuente de verdad del coach de una clase es `clases.coach_id`;
  * `clases.asignacion_origen` distingue **quién** la puso: `'coach'` (el coach la tomó
    desde su panel) o `'admin'` (el admin la asignó en emergencia desde Supervisión);
  * un coach NO pisa a otro: si la clase (o el horario recurrente) ya tienen otro coach,
    la operación se rechaza con **409** y el nombre de quien la tiene;
  * `horarios_coach` guarda la **vigencia** del coach de un horario recurrente
    (aplica a las clases futuras y a las que se generen después).

Este módulo arranca (B1) con la parte PURA: las marcas de la grilla de Supervisión.
B2 agrega las operaciones contra la BD (tomar / soltar / backfill / vigencia) y B6 la
liberación al dar de baja a un coach o sacarlo de una disciplina.

Nada de acá commitea: las funciones dejan los cambios en la transacción del llamador
(el endpoint commitea una sola vez, con su auditoría).
"""
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.models.clase import Clase
from app.models.horario_coach import HorarioCoach

# Marcas de la grilla (B5 las pinta así):
#   ✅ tomada por el coach · 🟦 asignada por el admin · ⚠️ cobertura de emergencia · 🔴 sin coach
MARCA_SIN_COACH = "sin_coach"
MARCA_COACH = "coach"
MARCA_ADMIN = "admin"
MARCA_EMERGENCIA = "emergencia"

MARCAS_VALIDAS = (MARCA_SIN_COACH, MARCA_COACH, MARCA_ADMIN, MARCA_EMERGENCIA)

# Celda del resumen de cobertura → estado por clase (mismo criterio que la marca).
ORIGEN_COACH = "coach"
ORIGEN_ADMIN = "admin"


def marca_cobertura(coach_id: Optional[int],
                    origen: Optional[str] = None,
                    emergencia: bool = False) -> str:
    """Marca de UNA clase en la grilla de Supervisión.

    Prioridad: la cobertura de emergencia gana siempre (es lo que hay que ver primero),
    después "sin coach", y si hay coach se distingue cómo llegó (`admin` vs `coach`).
    Sin `coach_id` la marca es `sin_coach` aunque `origen` venga seteado (dato sucio).
    """
    if emergencia:
        return MARCA_EMERGENCIA
    if not coach_id:
        return MARCA_SIN_COACH
    if origen == ORIGEN_ADMIN:
        return MARCA_ADMIN
    return MARCA_COACH


def porcentaje_cobertura(con_coach: int, total: int) -> float:
    """% de clases con coach (0.0 si no hay clases). Redondeado a 1 decimal."""
    if not total:
        return 0.0
    return round(100.0 * con_coach / total, 1)


# ─────────────────────────────────────────────────────────────────────────────
# B6: cuándo hay que liberar a un coach
# ─────────────────────────────────────────────────────────────────────────────

def hay_que_liberar_coach(era_coach: bool, es_coach: bool,
                          estado_antes: Optional[str],
                          estado_despues: Optional[str]) -> bool:
    """True si al actualizar un usuario hay que soltarle horarios y clases futuras.

    Dos casos (B6): dejó de ser coach (cambio de rol) o pasó de activo a cualquier
    otro estado. Un usuario que NO era coach nunca libera nada (no tiene clases).
    """
    if not era_coach:
        return False
    if not es_coach:
        return True
    return (estado_antes or "").strip().lower() == "activo" and \
        (estado_despues or "").strip().lower() != "activo"


# ─────────────────────────────────────────────────────────────────────────────
# B3: avisos al coach (tabla `notificaciones`, la de la campana; sin correo)
#   Los `tipo` tienen que entrar en `notificaciones.tipo` (VARCHAR(20)).
# ─────────────────────────────────────────────────────────────────────────────

TIPO_CLASE_ASIGNADA = "clase_asignada"      # 14
TIPO_CLASE_REASIGNADA = "clase_reasignada"  # 16
TIPO_CLASE_LIBERADA = "clase_liberada"      # 14


def descripcion_clase(disciplina: Optional[str], fecha, hora_inicio) -> str:
    """Texto corto de la clase para los avisos: 'clase de CrossFit del 2026-04-14 19:00'."""
    partes = ["clase"]
    if disciplina:
        partes.append(f"de {disciplina}")
    partes.append(f"del {fecha}")
    if hora_inicio:
        partes.append(str(hora_inicio)[:5])
    return " ".join(partes)


def mensaje_clase_asignada(descripcion: str, admin_nombre: str,
                           emergencia: bool = False) -> str:
    """Aviso al coach que RECIBE la clase (🟦 o ⚠️ si es cobertura)."""
    if emergencia:
        return (f"⚠️ Cobertura de emergencia: {admin_nombre} te asignó la "
                f"{descripcion}.")
    return f"🟦 {admin_nombre} te asignó la {descripcion}."


def mensaje_clase_reasignada(descripcion: str, admin_nombre: str,
                             coach_nuevo: str) -> str:
    """Aviso al coach que PIERDE la clase: se la pasaron a otro."""
    return (f"🔁 {admin_nombre} reasignó la {descripcion} a {coach_nuevo}. "
            f"Ya no está en tu panel.")


def mensaje_clase_liberada(descripcion: str, admin_nombre: str) -> str:
    """Aviso al coach al que le QUITARON la clase (queda 🔴 sin coach)."""
    return f"🔴 {admin_nombre} te quitó la {descripcion}."



# ─────────────────────────────────────────────────────────────────────────────
# Marcar / liberar UNA clase (en memoria; el llamador commitea)
# ─────────────────────────────────────────────────────────────────────────────

def marcar_clase(clase: Clase, coach_id: int, origen: str,
                 quien_id: Optional[int] = None,
                 cuando: Optional[datetime] = None) -> Clase:
    """Deja la clase asignada a `coach_id` con su marca de origen (✅ o 🟦)."""
    clase.coach_id = coach_id
    clase.asignacion_origen = origen
    clase.asignada_por = coach_id if quien_id is None else quien_id
    clase.asignada_en = cuando or datetime.now(timezone.utc)
    return clase


def liberar_clase(clase: Clase) -> Clase:
    """Suelta la clase: sin coach y sin marca de asignación."""
    clase.coach_id = None
    clase.asignacion_origen = None
    clase.asignada_por = None
    clase.asignada_en = None
    return clase


# ─────────────────────────────────────────────────────────────────────────────
# Vigencia del coach de un horario recurrente (`horarios_coach`)
# ─────────────────────────────────────────────────────────────────────────────

def vigencias_por_horario(db: Session, tenant_id: int, horario_ids: Iterable[int],
                          fecha: date) -> Dict[int, HorarioCoach]:
    """Vigencia que cubre `fecha`, por horario (1 query para todos los horarios).

    La usa el generador de clases: las clases nuevas heredan al coach vigente.
    """
    ids = [i for i in horario_ids if i]
    if not ids:
        return {}
    filas = db.query(HorarioCoach).filter(
        HorarioCoach.tenant_id == tenant_id,
        HorarioCoach.horario_id.in_(ids),
        HorarioCoach.vigente_desde <= fecha,
        or_(HorarioCoach.vigente_hasta.is_(None),
            HorarioCoach.vigente_hasta >= fecha),
    ).all()
    return {f.horario_id: f for f in filas}


def vigencia_para_fecha(db: Session, tenant_id: int, horario_id: int,
                        fecha: date) -> Optional[HorarioCoach]:
    """Vigencia de UN horario que cubre `fecha` (o None)."""
    return vigencias_por_horario(
        db, tenant_id, [horario_id], fecha).get(horario_id)


def coach_vigente(db: Session, tenant_id: int,
                  horario_id: int) -> Optional[HorarioCoach]:
    """Fila vigente de un horario (`vigente_hasta IS NULL`), o None."""
    return db.query(HorarioCoach).filter(
        HorarioCoach.tenant_id == tenant_id,
        HorarioCoach.horario_id == horario_id,
        HorarioCoach.vigente_hasta.is_(None),
    ).order_by(HorarioCoach.vigente_desde.desc(),
               HorarioCoach.id.desc()).first()


def vigencias_vigentes_de_coach(db: Session, tenant_id: int,
                                coach_id: int) -> List[HorarioCoach]:
    """Todas las vigencias ABIERTAS de un coach (para liberarlo de una vez)."""
    return db.query(HorarioCoach).filter(
        HorarioCoach.tenant_id == tenant_id,
        HorarioCoach.coach_id == coach_id,
        HorarioCoach.vigente_hasta.is_(None),
    ).all()


# ─────────────────────────────────────────────────────────────────────────────
# Conflictos ("nunca se pisa a otro coach") y vigencia
# ─────────────────────────────────────────────────────────────────────────────

def conflicto_futuro_en_horario(db: Session, tenant_id: int, horario_id: int,
                                desde: date,
                                coach_id: Optional[int] = None) -> Optional[dict]:
    """Primer choque en las clases FUTURAS del horario (otro coach), o None.

    `coach_id=None` = cualquier coach cuenta (para "liberar el horario completo").
    Devuelve `{clase_id, fecha, coach_id, coach_nombre}` para poder responder 409
    con el nombre de quien la tiene (regla de negocio del plan de Supervisión).
    """
    params = {"hid": horario_id, "tid": tenant_id, "desde": desde}
    excluir = ""
    if coach_id is not None:
        params["cid"] = coach_id
        excluir = "AND c.coach_id <> :cid"
    fila = db.execute(text(f"""
        SELECT c.id AS clase_id, c.fecha::text AS fecha, c.coach_id,
               u.nombre AS coach_nombre
        FROM clases c
        LEFT JOIN usuarios u ON u.id = c.coach_id
        WHERE c.horario_base_id = :hid
          AND c.tenant_id = :tid
          AND c.fecha >= :desde
          AND c.cancelada = false
          AND c.coach_id IS NOT NULL
          {excluir}
        ORDER BY c.fecha, c.id
        LIMIT 1
    """), params).first()
    if not fila:
        return None
    return {
        "clase_id": fila.clase_id,
        "fecha": fila.fecha,
        "coach_id": fila.coach_id,
        "coach_nombre": fila.coach_nombre or f"Coach #{fila.coach_id}",
    }


def abrir_vigencia(db: Session, tenant_id: int, horario_id: int, coach_id: int,
                   desde: date, creado_por: Optional[int] = None) -> HorarioCoach:
    """Abre la vigencia del coach en el horario (no commitea)."""
    vigencia = HorarioCoach(
        tenant_id=tenant_id, horario_id=horario_id, coach_id=coach_id,
        vigente_desde=desde, vigente_hasta=None,
        creado_por=coach_id if creado_por is None else creado_por)
    db.add(vigencia)
    return vigencia


def cerrar_vigencia(vigencia: HorarioCoach, desde: date) -> HorarioCoach:
    """Cierra la vigencia en `desde - 1 día` respetando el CHECK
    (`vigente_hasta >= vigente_desde`): si la vigencia empieza hoy o después, cierra
    el mismo día de inicio.
    """
    cierre = desde - timedelta(days=1)
    if cierre < vigencia.vigente_desde:
        cierre = vigencia.vigente_desde
    vigencia.vigente_hasta = cierre
    return vigencia

# ─────────────────────────────────────────────────────────────────────────────
# Backfill y liberación de clases futuras
# ─────────────────────────────────────────────────────────────────────────────

def backfill_horario(db: Session, tenant_id: int, horario_id: int, coach_id: int,
                     quien_id: Optional[int] = None,
                     desde: Optional[date] = None,
                     origen: str = ORIGEN_COACH) -> int:
    """Asigna el coach a las clases FUTURAS del horario. Devuelve las filas tocadas.

    Sólo toca clases SIN coach o que ya eran suyas (`coach_id IS NULL OR = coach`):
    nunca pisa a otro coach (el llamador valida antes y responde 409 con el nombre).
    """
    res = db.execute(text("""
        UPDATE clases
        SET coach_id = :cid,
            asignacion_origen = :origen,
            asignada_por = :quien,
            asignada_en = now(),
            updated_at = now()
        WHERE horario_base_id = :hid
          AND tenant_id = :tid
          AND cancelada = false
          AND fecha >= COALESCE(:desde, fecha)
          AND (coach_id IS NULL OR coach_id = :cid)
    """), {
        "cid": coach_id,
        "origen": origen,
        "quien": coach_id if quien_id is None else quien_id,
        "hid": horario_id,
        "tid": tenant_id,
        "desde": desde,
    })
    return res.rowcount


def liberar_clases_futuras_de_horario(db: Session, tenant_id: int, horario_id: int,
                                      desde: date,
                                      coach_id: Optional[int] = None) -> int:
    """Suelta las clases futuras del horario (todas, o sólo las de un coach)."""
    params = {"hid": horario_id, "tid": tenant_id, "desde": desde}
    solo_suyas = ""
    if coach_id is not None:
        params["cid"] = coach_id
        solo_suyas = "AND coach_id = :cid"
    res = db.execute(text(f"""
        UPDATE clases
        SET coach_id = NULL,
            asignacion_origen = NULL,
            asignada_por = NULL,
            asignada_en = NULL,
            updated_at = now()
        WHERE horario_base_id = :hid
          AND tenant_id = :tid
          AND cancelada = false
          AND fecha >= :desde
          AND coach_id IS NOT NULL
          {solo_suyas}
    """), params)
    return res.rowcount


def liberar_coach(db: Session, tenant_id: int, coach_id: int, desde: date) -> dict:
    """B6: saca a un coach de TODO lo suyo (vigencias abiertas + clases futuras).

    Se usa cuando el admin da de baja al coach o lo saca de la disciplina de un
    horario. No commitea: el endpoint lo hace junto con su auditoría.
    """
    vigencias = vigencias_vigentes_de_coach(db, tenant_id, coach_id)
    for vigencia in vigencias:
        cerrar_vigencia(vigencia, desde)
    res = db.execute(text("""
        UPDATE clases
        SET coach_id = NULL,
            asignacion_origen = NULL,
            asignada_por = NULL,
            asignada_en = NULL,
            updated_at = now()
        WHERE tenant_id = :tid
          AND coach_id = :cid
          AND cancelada = false
          AND fecha >= :desde
    """), {"tid": tenant_id, "cid": coach_id, "desde": desde})
    return {
        "vigencias_cerradas": len(vigencias),
        "clases_liberadas": res.rowcount,
        "horarios": [v.horario_id for v in vigencias],
    }
