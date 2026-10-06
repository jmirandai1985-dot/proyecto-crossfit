"""
Router de endpoints para Supervision de Clases (admin).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text
from datetime import date, datetime, timedelta

from app.db.database import get_db
from typing import List, Optional
from pydantic import BaseModel
from app.core.dependencies import get_current_admin, verificar_coach_disciplina
from app.core.estados import es_cancelada   # 'cancelada' tampoco es una reserva activa
from app.models.clase import Clase
from app.models.coach_disciplina import CoachDisciplina
from app.models.usuario import RolUsuario, Usuario
from app.services import asignaciones_clases as asignaciones
from app.services import notificaciones_panel
from app.services.asignaciones_clases import (
    ORIGEN_ADMIN,
    TIPO_CLASE_ASIGNADA,
    TIPO_CLASE_LIBERADA,
    TIPO_CLASE_REASIGNADA,
    descripcion_clase,
    marca_cobertura,
    mensaje_clase_asignada,
    mensaje_clase_liberada,
    mensaje_clase_reasignada,
    porcentaje_cobertura,
)
from app.services.auditoria_service import registrar_auditoria
from app.utils.santiago import hoy_santiago   # HOY en Chile (la TZ del proceso es UTC)
from app.utils.semana import (
    MAX_DIAS_RANGO,
    fechas_del_rango,
    nombre_dia,
    sql_dow_lunes_cero,
)

router = APIRouter()


class CoachConPertenencia(BaseModel):
    id: int
    nombre: str
    pertenece: bool
    disciplinas: List[str] = []


@router.get("/proxima-clase-reservas")
def proxima_clase_reservas(
    horario_base_id: int = Query(..., description="ID del horario base"),
    tenant_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """
    Dado un horario_base_id, devuelve la PRÓXIMA clase futura de ese horario
    base y sus reservas (alumno_nombre, asistio, activa).
    Para disciplinas self-service (Open Box, Musculación). Solo admin.
    """
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]
    # HOY en Chile: `date.today()` usaba el reloj del proceso (UTC) y de noche saltaba de dia.
    hoy = hoy_santiago()

    clase = db.execute(sql_text("""
        SELECT c.id, c.fecha::text, c.hora_inicio::text, c.hora_fin::text,
               c.cupo_maximo, c.asistentes_confirmados, c.disciplina_id
        FROM clases c
        WHERE c.horario_base_id = :hid
          AND c.tenant_id = :tid
          AND c.fecha >= :hoy
          AND c.cancelada = false
        ORDER BY c.fecha, c.hora_inicio
        LIMIT 1
    """), {"hid": horario_base_id, "tid": tenant_id, "hoy": hoy}).first()

    if not clase:
        return {
            "status": "success",
            "hay_clase": False,
            "mensaje": "No hay próxima clase generada para este horario",
            "clase": None,
            "reservas": [],
        }

    reservas = db.execute(sql_text("""
        SELECT r.id, r.alumno_id, r.estado, r.asistio, r.fecha_reserva::text,
               u.nombre AS alumno_nombre
        FROM reservas r
        LEFT JOIN usuarios u ON u.id = r.alumno_id
        WHERE r.clase_id = :cid AND r.tenant_id = :tid
        ORDER BY r.created_at ASC
    """), {"cid": clase.id, "tid": tenant_id}).fetchall()

    return {
        "status": "success",
        "hay_clase": True,
        "clase": {
            "id": clase.id,
            "fecha": clase.fecha,
            "hora_inicio": clase.hora_inicio[:5] if clase.hora_inicio else None,
            "hora_fin": clase.hora_fin[:5] if clase.hora_fin else None,
            "cupo_maximo": clase.cupo_maximo,
            "asistentes_confirmados": clase.asistentes_confirmados,
            "disciplina_id": clase.disciplina_id,
        },
        "reservas": [
            {
                "id": r.id,
                "alumno_id": r.alumno_id,
                "alumno_nombre": r.alumno_nombre or f"Alumno #{r.alumno_id}",
                "asistio": r.asistio,
                "activa": not es_cancelada(r.estado),
            }
            for r in reservas
        ],
    }


@router.get("/horarios-base")
def horarios_base_por_disciplina(
    disciplina_id: int = Query(..., description="ID de la disciplina"),
    tenant_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """
    Devuelve las PLANTILLAS de horario (tabla `horarios`, la REAL: `horarios_base` es una
    tabla legado/zombie sin uso — ver docs/SUPERVISION_CLASES.md) de una disciplina, con
    el coach de la clase generada más reciente de cada horario (patrón semanal real).
    Fuente: `horarios` (plantilla), NO la tabla `clases` (instancias generadas).
    Solo admin.
    """
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]
    rows = db.execute(sql_text("""
        SELECT h.id, h.dia_semana, h.hora_inicio::text, h.hora_fin::text,
               h.cupo_maximo, h.activo,
               c.coach_id, u.nombre AS coach_nombre,
               c.clase_id AS clase_reciente_id
        FROM horarios h
        LEFT JOIN LATERAL (
            SELECT c2.coach_id, c2.id AS clase_id
            FROM clases c2
            WHERE c2.horario_base_id = h.id
              AND c2.tenant_id = :tid
            ORDER BY c2.fecha DESC, c2.id DESC
            LIMIT 1
        ) c ON true
        LEFT JOIN usuarios u ON u.id = c.coach_id
        WHERE h.tenant_id = :tid
          AND h.disciplina_id = :did
          AND h.activo = true
        ORDER BY h.dia_semana, h.hora_inicio
    """), {"tid": tenant_id, "did": disciplina_id}).fetchall()

    return {
        "disciplina_id": disciplina_id,
        "total_horarios": len(rows),
        "horarios": [
            {
                "id": r.id,
                "dia_semana": r.dia_semana,
                "hora_inicio": r.hora_inicio[:5] if r.hora_inicio else None,
                "hora_fin": r.hora_fin[:5] if r.hora_fin else None,
                "cupo_maximo": r.cupo_maximo,
                "activo": r.activo,
                "coach_id": r.coach_id,
                "coach_nombre": r.coach_nombre or None,
                "clase_reciente_id": r.clase_reciente_id,
            }
            for r in rows
        ],
    }


@router.get("/grid-semanal")
def supervision_grid_semanal(
    fecha: str = Query(..., description="Fecha en formato YYYY-MM-DD"),
    tenant_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """
    Devuelve el estado REAL de todas las clases de la semana que contiene la fecha dada.
    Agrupado por (dia_semana, hora_inicio, hora_fin) con datos por clase:
    coach, ocupacion/cupo, WOD publicado, cobertura de emergencia.
    Solo admin.
    """
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]
    try:
        fecha_date = datetime.strptime(fecha, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Formato de fecha invalido. Use YYYY-MM-DD")

    # Calcular lunes de la semana
    dia_semana_py = fecha_date.weekday()  # 0=Lunes, 6=Domingo
    lunes = fecha_date - timedelta(days=dia_semana_py)
    domingo = lunes + timedelta(days=6)

    # B1 · DOW CONSISTENTE: `EXTRACT(DOW …)` de Postgres es 0=Domingo..6=Sábado; el
    # resto del proyecto (y el frontend) usa 0=Lunes..6=Domingo. Sin esta conversión
    # la grilla se mostraba corrida un día. Ver app/utils/semana.py.
    _dow_lunes_cero = sql_dow_lunes_cero("c.fecha")

    rows = db.execute(sql_text(f"""
        SELECT
            {_dow_lunes_cero} AS dia_semana,
            c.hora_inicio::text,
            c.hora_fin::text,
            c.fecha::text,
            c.id AS clase_id,
            c.disciplina_id,
            d.nombre AS disciplina_nombre,
            c.cupo_maximo,
            c.asistentes_confirmados,
            COALESCE(u.nombre, 'Sin asignar') AS coach_nombre,
            c.coach_id,
            c.wod_id,
            COALESCE(w.titulo, '') AS wod_titulo,
            CASE WHEN ce.id IS NOT NULL THEN true ELSE false END AS cobertura_emergencia
        FROM clases c
        JOIN disciplinas d ON c.disciplina_id = d.id
        LEFT JOIN usuarios u ON c.coach_id = u.id
        LEFT JOIN wods w ON c.wod_id = w.id
        LEFT JOIN cobertura_emergencia ce ON ce.clase_id = c.id
        WHERE c.tenant_id = :tid
          AND c.fecha >= :lunes
          AND c.fecha <= :domingo
        ORDER BY c.fecha, c.hora_inicio, d.nombre
    """), {
        "tid": tenant_id,
        "lunes": lunes,
        "domingo": domingo
    }).fetchall()

    # Agrupar por (dia_semana, hora_inicio, hora_fin)
    from collections import defaultdict
    grid = defaultdict(list)
    dias_con_clases = set()

    for r in rows:
        d = dict(r._mapping)
        dias_con_clases.add(d["fecha"])
        key = (d["dia_semana"], d["hora_inicio"], d["hora_fin"])
        grid[key].append({
            "clase_id": d["clase_id"],
            "fecha": d["fecha"],
            "disciplina_id": d["disciplina_id"],
            "disciplina_nombre": d["disciplina_nombre"],
            "cupo_maximo": d["cupo_maximo"],
            "asistentes_confirmados": d["asistentes_confirmados"],
            "coach_nombre": d["coach_nombre"],
            "coach_id": d["coach_id"],
            "wod_id": d["wod_id"],
            "wod_titulo": d["wod_titulo"],
            "cobertura_emergencia": d["cobertura_emergencia"],
        })

    return {
        "lunes": str(lunes),
        "domingo": str(domingo),
        "dias_con_clases": sorted(list(dias_con_clases)),
        "celdas": [
            {
                "dia_semana": dia,
                "hora_inicio": h_ini,
                "hora_fin": h_fin,
                "clases": clases
            }
            for (dia, h_ini, h_fin), clases in sorted(grid.items())
        ]
    }


@router.get("/grilla")
def supervision_grilla(
    desde: date = Query(..., description="Primer día del rango (YYYY-MM-DD)"),
    hasta: date = Query(..., description="Último día del rango (YYYY-MM-DD)"),
    disciplina_id: Optional[int] = Query(
        None, description="Filtra una sola disciplina (opcional)"),
    tenant_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """Grilla de Supervisión por RANGO + resumen de cobertura. Solo admin.

    Qué devuelve (contrato para el frontend de Supervisión):

      * `dias`: cada fecha del rango que NO es domingo (`dia_semana` 0=Lunes..6=Domingo,
        consistente con `date.weekday()` — ver `app/utils/semana.py`);
      * `plantillas`: las celdas de la tabla `horarios` (activas) de las disciplinas
        `requiere_coach=true`, para pintar la semana completa aunque falten clases
        generadas; `marca` dice si esa plantilla tiene coach o no;
      * `celdas`: las clases REALES del rango agrupadas por (fecha, hora_inicio, hora_fin),
        cada una con su `marca` (sin_coach / coach / admin / emergencia);
      * `resumen`: cobertura del rango (total, con/sin coach, por marca, por disciplina).

    Qué NO hace: no genera clases (`POST /horarios/generar-clases-dia`), no escribe nada
    y no incluye días fuera del rango. `disciplina_id` es opcional.

    B1: el coach de cada `plantilla` sale de la última clase generada de ese horario
    (igual que `/horarios-base`); B2 lo pasa a leer de `horarios_coach` (el recurrente).
    """
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]

    if desde > hasta:
        raise HTTPException(
            status_code=400, detail="'desde' no puede ser posterior a 'hasta'")
    if (hasta - desde).days + 1 > MAX_DIAS_RANGO:
        raise HTTPException(
            status_code=400,
            detail=f"Rango máximo {MAX_DIAS_RANGO} días (se pidió "
                   f"{(hasta - desde).days + 1})",
        )

    dias_rango = fechas_del_rango(desde, hasta)
    if not dias_rango:
        raise HTTPException(
            status_code=400,
            detail="El rango no tiene días hábiles: la grilla es lunes-sábado "
                   "(los domingos no hay clases)",
        )

    params = {"tid": tenant_id, "desde": desde, "hasta": hasta}
    filtro_disc_clases = ""
    filtro_disc_plantillas = ""
    if disciplina_id is not None:
        params["did"] = disciplina_id
        filtro_disc_clases = "AND c.disciplina_id = :did"
        filtro_disc_plantillas = "AND h.disciplina_id = :did"

    # ── 1) PLANTILLAS: tabla `horarios` (activa) de disciplinas que requieren coach ──
    # `horarios_base` NO se usa: es una tabla legado/zombie (docs/SUPERVISION_CLASES.md).
    plantillas_rows = db.execute(sql_text(f"""
        SELECT h.id AS horario_id, h.disciplina_id, d.nombre AS disciplina_nombre,
               h.dia_semana, h.hora_inicio::text AS hora_inicio,
               h.hora_fin::text AS hora_fin, h.cupo_maximo,
               ult.coach_id, u.nombre AS coach_nombre
        FROM horarios h
        JOIN disciplinas d ON d.id = h.disciplina_id
        LEFT JOIN LATERAL (
            SELECT c2.coach_id
            FROM clases c2
            WHERE c2.horario_base_id = h.id
              AND c2.tenant_id = :tid
              AND c2.cancelada = false
            ORDER BY c2.fecha DESC, c2.id DESC
            LIMIT 1
        ) ult ON true
        LEFT JOIN usuarios u ON u.id = ult.coach_id
        WHERE h.tenant_id = :tid
          AND h.activo = true
          AND d.activo = true
          AND d.requiere_coach = true
          {filtro_disc_plantillas}
        ORDER BY h.dia_semana, h.hora_inicio, d.nombre
    """), params).fetchall()

    plantillas = []
    for r in plantillas_rows:
        plantillas.append({
            "horario_id": r.horario_id,
            "disciplina_id": r.disciplina_id,
            "disciplina_nombre": r.disciplina_nombre,
            "dia_semana": r.dia_semana,   # ya viene 0=Lunes (columna de `horarios`)
            "hora_inicio": r.hora_inicio[:5] if r.hora_inicio else None,
            "hora_fin": r.hora_fin[:5] if r.hora_fin else None,
            "cupo_maximo": r.cupo_maximo,
            "coach_id": r.coach_id,
            "coach_nombre": r.coach_nombre or None,
            "marca": marca_cobertura(r.coach_id),
        })

    # ── 2) CLASES REALES del rango ──
    _dow_lunes_cero = sql_dow_lunes_cero("c.fecha")
    clases_rows = db.execute(sql_text(f"""
        SELECT c.id AS clase_id, c.fecha::text AS fecha,
               {_dow_lunes_cero} AS dia_semana,
               c.hora_inicio::text AS hora_inicio, c.hora_fin::text AS hora_fin,
               c.horario_base_id, c.disciplina_id,
               d.nombre AS disciplina_nombre,
               c.coach_id, u.nombre AS coach_nombre,
               c.cupo_maximo, c.asistentes_confirmados,
               c.wod_id, COALESCE(w.titulo, '') AS wod_titulo,
               CASE WHEN ce.id IS NOT NULL THEN true ELSE false END AS cobertura_emergencia
        FROM clases c
        JOIN disciplinas d ON c.disciplina_id = d.id
        LEFT JOIN usuarios u ON u.id = c.coach_id
        LEFT JOIN wods w ON w.id = c.wod_id
        LEFT JOIN cobertura_emergencia ce ON ce.clase_id = c.id
        WHERE c.tenant_id = :tid
          AND c.fecha >= :desde
          AND c.fecha <= :hasta
          AND c.cancelada = false
          AND d.activo = true
          AND d.requiere_coach = true
          AND EXISTS (
              SELECT 1 FROM horarios h2
              WHERE h2.disciplina_id = d.id
                AND h2.tenant_id = :tid
                AND h2.activo = true
          )
          {filtro_disc_clases}
        ORDER BY c.fecha, c.hora_inicio, d.nombre, c.id
    """), params).fetchall()

    from collections import defaultdict

    celdas = defaultdict(list)
    contadores = {
        "total_clases": 0,
        "con_coach": 0,
        "sin_coach": 0,
        "tomadas_por_coach": 0,    # marca 'coach' (✅)
        "asignadas_por_admin": 0,  # marca 'admin' (🟦)
        "cobertura_emergencia": 0,  # marca 'emergencia' (⚠️)
    }
    por_disciplina = {}
    disciplinas_vistas = {}

    for r in clases_rows:
        fila = {
            "clase_id": r.clase_id,
            "fecha": r.fecha,
            "dia_semana": r.dia_semana,
            "hora_inicio": r.hora_inicio[:5] if r.hora_inicio else None,
            "hora_fin": r.hora_fin[:5] if r.hora_fin else None,
            "horario_base_id": r.horario_base_id,
            "disciplina_id": r.disciplina_id,
            "disciplina_nombre": r.disciplina_nombre,
            "coach_id": r.coach_id,
            "coach_nombre": r.coach_nombre or None,
            "marca": marca_cobertura(r.coach_id, None, bool(r.cobertura_emergencia)),
            "cupo_maximo": r.cupo_maximo,
            "asistentes_confirmados": r.asistentes_confirmados,
            "wod_id": r.wod_id,
            "wod_titulo": r.wod_titulo,
            "cobertura_emergencia": bool(r.cobertura_emergencia),
        }
        celdas[(r.fecha, fila["hora_inicio"], fila["hora_fin"])].append(fila)

        contadores["total_clases"] += 1
        if r.coach_id:
            contadores["con_coach"] += 1
        else:
            contadores["sin_coach"] += 1
        if fila["marca"] == "coach":
            contadores["tomadas_por_coach"] += 1
        elif fila["marca"] == "admin":
            contadores["asignadas_por_admin"] += 1
        elif fila["marca"] == "emergencia":
            contadores["cobertura_emergencia"] += 1

        disciplinas_vistas[r.disciplina_id] = r.disciplina_nombre
        acum = por_disciplina.setdefault(r.disciplina_id, {
            "disciplina_id": r.disciplina_id,
            "nombre": r.disciplina_nombre,
            "total": 0,
            "con_coach": 0,
            "sin_coach": 0,
        })
        acum["total"] += 1
        if r.coach_id:
            acum["con_coach"] += 1
        else:
            acum["sin_coach"] += 1

    hoy = hoy_santiago()
    dias = [
        {
            "fecha": d.isoformat(),
            "dia_semana": d.weekday(),
            "nombre_dia": nombre_dia(d.weekday()),
            "es_hoy": d == hoy,
            "es_pasado": d < hoy,
        }
        for d in dias_rango
    ]

    resumen_disc = [
        {**v, "cobertura_pct": porcentaje_cobertura(v["con_coach"], v["total"])}
        for v in sorted(por_disciplina.values(), key=lambda x: x["nombre"] or "")
    ]

    return {
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "dias": dias,
        "disciplinas": [
            {"id": did, "nombre": nombre}
            for did, nombre in sorted(disciplinas_vistas.items(),
                                      key=lambda x: x[1] or "")
        ],
        "plantillas": plantillas,
        "celdas": [
            {
                "fecha": fecha,
                "dia_semana": clases[0]["dia_semana"],
                "hora_inicio": h_ini,
                "hora_fin": h_fin,
                "clases": clases,
            }
            for (fecha, h_ini, h_fin), clases in sorted(celdas.items())
        ],
        "resumen": {
            **contadores,
            "cobertura_pct": porcentaje_cobertura(
                contadores["con_coach"], contadores["total_clases"]),
            "plantillas_activas": len(plantillas),
            "plantillas_sin_coach": sum(
                1 for p in plantillas if p["marca"] == "sin_coach"),
            "por_disciplina": resumen_disc,
        },
    }


@router.get("/coaches-todos")
def listar_coaches_con_pertenencia(
    disciplina_id: int = Query(...,
                               description="ID de la disciplina para verificar pertenencia"),
    tenant_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """
    Lista TODOS los coaches activos del tenant, indicando si pertenecen a la disciplina especificada.
    Usado desde Supervisión para asignación de coaches con/sin cobertura de emergencia.
    Solo admin.
    """
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]
    # Todos los usuarios con rol=coach activos
    coaches = db.execute(sql_text("""
        SELECT u.id, u.nombre
        FROM usuarios u
        WHERE u.tenant_id = :tid AND u.rol = 'coach' AND u.estado = 'activo'
        ORDER BY u.nombre
    """), {"tid": tenant_id}).fetchall()

    # IDs de coaches que pertenecen a la disciplina
    pertenecen = set()
    rels = db.execute(sql_text("""
        SELECT cd.coach_id
        FROM coach_disciplinas cd
        WHERE cd.tenant_id = :tid AND cd.disciplina_id = :did AND cd.activo = true
    """), {"tid": tenant_id, "did": disciplina_id}).fetchall()
    for r in rels:
        pertenecen.add(r.coach_id)

    # Disciplinas de cada coach (para mostrar detalle)
    coach_disciplinas_map = {}
    all_rels = db.execute(sql_text("""
        SELECT cd.coach_id, d.nombre
        FROM coach_disciplinas cd
        JOIN disciplinas d ON cd.disciplina_id = d.id
        WHERE cd.tenant_id = :tid AND cd.activo = true
    """), {"tid": tenant_id}).fetchall()
    for r in all_rels:
        coach_disciplinas_map.setdefault(r.coach_id, []).append(r.nombre)

    result = []
    for c in coaches:
        result.append({
            "id": c.id,
            "nombre": c.nombre,
            "pertenece": c.id in pertenecen,
            "disciplinas": coach_disciplinas_map.get(c.id, [])
        })

    return result


@router.patch("/cupo-disciplina")
def actualizar_cupo_disciplina(
    disciplina_id: int = Query(..., description="ID de la disciplina"),
    cupo_maximo: int = Query(..., ge=1, le=200,
                             description="Nuevo cupo máximo (1-200)"),
    tenant_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """
    Actualiza el cupo_maximo en TODOS los horario_base de una disciplina.
    Afecta las próximas clases generadas, no reescribe clases ya creadas.
    Solo admin.
    """
    # 🔒 SEGURIDAD: tenant_id SIEMPRE del token JWT.
    tenant_id = current_user["tenant_id"]
    # Verificar que la disciplina existe
    disc = db.execute(
        sql_text("SELECT id FROM disciplinas WHERE id = :did AND tenant_id = :tid"),
        {"did": disciplina_id, "tid": tenant_id}
    ).first()
    if not disc:
        raise HTTPException(status_code=404, detail="Disciplina no encontrada")

    # Actualizar cupo en todos los horario_base de esa disciplina
    result = db.execute(
        sql_text("""
            UPDATE horarios
            SET cupo_maximo = :cupo
            WHERE disciplina_id = :did AND tenant_id = :tid
        """),
        {"cupo": cupo_maximo, "did": disciplina_id, "tid": tenant_id}
    )
    filas_afectadas = result.rowcount
    db.commit()

    return {
        "ok": True,
        "disciplina_id": disciplina_id,
        "cupo_maximo": cupo_maximo,
        "horarios_actualizados": filas_afectadas
    }


@router.get("/cupos-disciplinas")
def listar_cupos_disciplinas(
    tenant_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """
    Lista TODAS las disciplinas con su cupo actual (tomado del horario_base más reciente/representativo).
    Solo admin.
    """
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]
    rows = db.execute(sql_text("""
        SELECT
            d.id,
            d.nombre,
            d.activo,
            COALESCE(
                (SELECT h.cupo_maximo FROM horarios h WHERE h.disciplina_id = d.id AND h.tenant_id = :tid ORDER BY h.id DESC LIMIT 1),
                16
            ) AS cupo_actual,
            (SELECT COUNT(*) FROM horarios h2 WHERE h2.disciplina_id = d.id AND h2.tenant_id = :tid) AS horarios_count
        FROM disciplinas d
        WHERE d.tenant_id = :tid
        ORDER BY d.id
    """), {"tid": tenant_id}).fetchall()

    return [
        {
            "id": r.id,
            "nombre": r.nombre.strip() if r.nombre else r.nombre,
            "activo": r.activo,
            "cupo_actual": r.cupo_actual,
            "horarios_count": r.horarios_count
        }
        for r in rows
    ]


# ─────────────────────────────────────────────────────────────────────────────
# ASIGNACIÓN DE EMERGENCIA DEL ADMIN (B3)
#   🟦 el admin asigna UNA clase; si el coach no dicta esa disciplina queda
#   registrada la ⚠️ cobertura de emergencia. El coach SIEMPRE se entera por la
#   campana de su panel (tabla `notificaciones`, sin correo).
# ─────────────────────────────────────────────────────────────────────────────

class AsignacionEmergenciaRequest(BaseModel):
    """Body de `POST /supervision/clases/{id}/asignar`."""
    coach_id: int
    motivo: Optional[str] = None
    # Si el coach no dicta la disciplina de la clase: true = se registra la
    # cobertura de emergencia (⚠️ + aviso a los admins); false = 409.
    forzar_emergencia: bool = True


def _nombre_de_usuario(db: Session, usuario_id) -> str:
    if not usuario_id:
        return "otro coach"
    nombre = db.execute(
        sql_text("SELECT nombre FROM usuarios WHERE id = :id"), {"id": usuario_id}
    ).scalar()
    return nombre or f"Coach #{usuario_id}"


def _descripcion_de_clase(db: Session, clase: Clase) -> str:
    """'clase de CrossFit del 2026-04-14 19:00' para los mensajes de la campana."""
    disc_nombre = None
    if clase.disciplina_id:
        disc_nombre = db.execute(
            sql_text("SELECT nombre FROM disciplinas WHERE id = :id"),
            {"id": clase.disciplina_id}).scalar()
    return descripcion_clase(disc_nombre, clase.fecha, clase.hora_inicio)

@router.post("/clases/{clase_id}/asignar")
def asignar_coach_emergencia(
    clase_id: int,
    body: AsignacionEmergenciaRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """El admin ASIGNA un coach a UNA clase (🟦). Es el camino de **emergencia**.

    - el coach tiene que ser del box y estar activo;
    - si no dicta esa disciplina: con `forzar_emergencia=true` se registra la
      cobertura de emergencia (⚠️ + aviso a los admins por el flujo existente) y la
      marca resultante es `emergencia`; con `false` responde 409;
    - **avisa al coach** en su campana (sin correo) y, si la clase era de otro coach,
      también avisa a ese (se la reasignaron);
    - no toca las demás clases del horario (eso es `POST /clases/{id}/tomar?alcance=horario`).
    """
    tenant_id = current_user["tenant_id"]
    admin_id = current_user["usuario_id"]
    admin_nombre = current_user.get("nombre") or f"Admin #{admin_id}"

    clase = db.query(Clase).filter(
        Clase.id == clase_id, Clase.tenant_id == tenant_id).first()
    if not clase:
        raise HTTPException(status_code=404, detail="Clase no encontrada")
    if clase.cancelada:
        raise HTTPException(status_code=409, detail="Esa clase está cancelada")
    hoy = hoy_santiago()
    if clase.fecha < hoy:
        raise HTTPException(
            status_code=409, detail="No puedes asignar una clase que ya pasó")

    coach = db.query(Usuario).filter(
        Usuario.id == body.coach_id,
        Usuario.tenant_id == tenant_id,
    ).first()
    if not coach:
        raise HTTPException(
            status_code=404, detail="Ese coach no existe en este box")
    if coach.rol != RolUsuario.coach:
        raise HTTPException(
            status_code=409, detail=f"{coach.nombre} no tiene rol de coach")
    if coach.estado != "activo":
        raise HTTPException(
            status_code=409, detail=f"{coach.nombre} no está activo")
    coach_nombre = coach.nombre or f"Coach #{coach.id}"
    if clase.coach_id == coach.id:
        raise HTTPException(
            status_code=409, detail=f"Esa clase ya es de {coach_nombre}")

    previo_id = clase.coach_id
    previo_nombre = _nombre_de_usuario(db, previo_id) if previo_id else None

    # ── ¿Hay que registrar cobertura de emergencia? ──
    es_emergencia = False
    if clase.disciplina_id:
        pertenece = db.query(CoachDisciplina).filter(
            CoachDisciplina.coach_id == coach.id,
            CoachDisciplina.disciplina_id == clase.disciplina_id,
            CoachDisciplina.activo == True,  # noqa: E712
        ).first() is not None
        if not pertenece:
            if not body.forzar_emergencia:
                raise HTTPException(
                    status_code=409,
                    detail=f"{coach_nombre} no dicta esa disciplina: confirma la "
                           f"cobertura de emergencia (forzar_emergencia=true)",
                )
            verificar_coach_disciplina(
                coach.id, clase.disciplina_id, db, modo_emergencia=True,
                clase_id=clase_id, accion="asignar_coach_admin",
                tenant_id=tenant_id)
            es_emergencia = True

    # ── Marca 🟦 + avisos, todo en la misma transacción ──
    asignaciones.marcar_clase(clase, coach.id, ORIGEN_ADMIN, quien_id=admin_id)
    descripcion = _descripcion_de_clase(db, clase)

    avisados = []
    if notificaciones_panel.notificar_usuario(
        db, coach.id, TIPO_CLASE_ASIGNADA,
        mensaje_clase_asignada(descripcion, admin_nombre, es_emergencia),
        commit=False,
    ):
        avisados.append(coach.id)
    if previo_id and previo_id != coach.id:
        if notificaciones_panel.notificar_usuario(
            db, previo_id, TIPO_CLASE_REASIGNADA,
            mensaje_clase_reasignada(descripcion, admin_nombre, coach_nombre),
            commit=False,
        ):
            avisados.append(previo_id)

    db.commit()
    db.refresh(clase)

    registrar_auditoria(
        db, tenant_id=tenant_id, usuario_id=admin_id,
        accion="asignar_coach_admin", entidad="clase", entidad_id=clase_id,
        detalle={
            "coach_id": coach.id,
            "coach_anterior_id": previo_id,
            "emergencia": es_emergencia,
            "motivo": body.motivo,
            "avisados": avisados,
        },
    )
    return {
        "ok": True,
        "clase_id": clase.id,
        "coach_id": coach.id,
        "coach_nombre": coach_nombre,
        "coach_anterior_id": previo_id,
        "coach_anterior_nombre": previo_nombre,
        "origen": ORIGEN_ADMIN,
        "emergencia": es_emergencia,
        "marca": marca_cobertura(clase.coach_id, clase.asignacion_origen,
                                 es_emergencia),
        "avisados": avisados,
    }

@router.delete("/clases/{clase_id}/asignar")
def quitar_coach_de_clase(
    clase_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_admin),
):
    """El admin QUITA el coach de una clase (queda 🔴 sin coach) y avisa al coach."""
    tenant_id = current_user["tenant_id"]
    admin_id = current_user["usuario_id"]
    admin_nombre = current_user.get("nombre") or f"Admin #{admin_id}"

    clase = db.query(Clase).filter(
        Clase.id == clase_id, Clase.tenant_id == tenant_id).first()
    if not clase:
        raise HTTPException(status_code=404, detail="Clase no encontrada")
    if clase.coach_id is None:
        raise HTTPException(
            status_code=409, detail="Esa clase no tiene coach asignado")
    hoy = hoy_santiago()
    if clase.fecha < hoy:
        raise HTTPException(
            status_code=409,
            detail="No puedes quitar el coach de una clase que ya pasó")

    previo_id = clase.coach_id
    descripcion = _descripcion_de_clase(db, clase)
    asignaciones.liberar_clase(clase)
    notificado = notificaciones_panel.notificar_usuario(
        db, previo_id, TIPO_CLASE_LIBERADA,
        mensaje_clase_liberada(descripcion, admin_nombre), commit=False)

    db.commit()
    db.refresh(clase)

    registrar_auditoria(
        db, tenant_id=tenant_id, usuario_id=admin_id,
        accion="quitar_coach_admin", entidad="clase", entidad_id=clase_id,
        detalle={"coach_anterior_id": previo_id,
                 "notificado": bool(notificado)},
    )
    return {
        "ok": True,
        "clase_id": clase.id,
        "coach_anterior_id": previo_id,
        "marca": marca_cobertura(clase.coach_id),
        "notificado": bool(notificado),
    }

