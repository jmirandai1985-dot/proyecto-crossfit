"""
Router de endpoints para Supervision de Clases (admin).
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text
from datetime import datetime, timedelta, date

from app.db.database import get_db
from typing import List
from pydantic import BaseModel

router = APIRouter()


class CoachConPertenencia(BaseModel):
    id: int
    nombre: str
    pertenece: bool
    disciplinas: List[str] = []


@router.get("/grid-semanal")
def supervision_grid_semanal(
    fecha: str = Query(..., description="Fecha en formato YYYY-MM-DD"),
    tenant_id: int = Query(1),
    db: Session = Depends(get_db)
):
    """
    Devuelve el estado REAL de todas las clases de la semana que contiene la fecha dada.
    Agrupado por (dia_semana, hora_inicio, hora_fin) con datos por clase:
    coach, ocupacion/cupo, WOD publicado, cobertura de emergencia.
    """
    try:
        fecha_date = datetime.strptime(fecha, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Formato de fecha invalido. Use YYYY-MM-DD")

    # Calcular lunes de la semana
    dia_semana_py = fecha_date.weekday()  # 0=Lunes, 6=Domingo
    lunes = fecha_date - timedelta(days=dia_semana_py)
    domingo = lunes + timedelta(days=6)

    rows = db.execute(sql_text("""
        SELECT
            EXTRACT(DOW FROM c.fecha)::int AS dia_semana,
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


@router.get("/coaches-todos")
def listar_coaches_con_pertenencia(
    disciplina_id: int = Query(...,
                               description="ID de la disciplina para verificar pertenencia"),
    tenant_id: int = Query(1),
    db: Session = Depends(get_db)
):
    """
    Lista TODOS los coaches activos del tenant, indicando si pertenecen a la disciplina especificada.
    Usado desde Supervisión para asignación de coaches con/sin cobertura de emergencia.
    """
    # Todos los usuarios con rol=coach activos
    coaches = db.execute(sql_text("""
        SELECT u.id, u.nombre
        FROM usuarios u
        WHERE u.tenant_id = :tid AND u.rol = 'coach' AND u.activo = true
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
