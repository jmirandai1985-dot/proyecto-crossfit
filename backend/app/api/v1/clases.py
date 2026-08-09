import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
from datetime import datetime, date, time, timedelta

from app.db.database import get_db
from app.models.clase import Clase
from app.schemas import clase as schemas
from app.core.dependencies import verificar_coach_disciplina

logger = logging.getLogger("uvicorn.clases")

router = APIRouter(tags=["Clases"])


@router.get("/", response_model=List[schemas.ClaseListItem])
def listar_clases(
    db: Session = Depends(get_db),
    tenant_id: int = Query(1),
    disciplina_id: Optional[int] = Query(
        None, description="Filtrar por disciplina"),
    coach_id: Optional[int] = Query(None),
    fecha: Optional[date] = Query(
        None, description="Filtrar por fecha unica (YYYY-MM-DD)"),
    fecha_desde: Optional[date] = Query(
        None, description="Filtrar desde fecha (YYYY-MM-DD)"),
    fecha_hasta: Optional[date] = Query(
        None, description="Filtrar hasta fecha (YYYY-MM-DD)"),
    solo_con_cupo: Optional[bool] = Query(
        None, description="Solo clases con cupos disponibles"),
    skip: int = Query(0),
    limit: int = Query(100)
):
    # ── RESPALDO AUTOMÁTICO: Si se consulta un rango y faltan clases,
    #    se generan automáticamente desde horarios_base ──
    try:
        from datetime import timedelta
        hoy = date.today()
        # ¿Qué rango se está consultando?
        rango_desde = fecha_desde if fecha_desde is not None else (
            fecha if fecha is not None else hoy)
        rango_hasta = fecha_hasta if fecha_hasta is not None else (
            fecha if fecha is not None else hoy)

        # Determinar si debemos auto-generar:
        #  - Si el rango consultado es futuro (rango_desde > hoy), generar para ESE rango.
        #  - Si el rango incluye hoy o días cercanos, generar hasta hoy+6 (vista 7 días).
        debe_generar = False
        gen_desde = None
        gen_hasta = None

        if fecha is not None:
            # Consulta de un solo día: generar solo ese día si faltan clases
            debe_generar = True
            gen_desde = fecha
            gen_hasta = fecha
        elif rango_desde is not None and rango_hasta is not None:
            # Consulta de rango: generamos SIEMPRE el rango consultado
            # (no solo [hoy, hoy+6]) para que navegar a semanas futuras funcione.
            debe_generar = True
            gen_desde = rango_desde
            gen_hasta = rango_hasta
            # Si el rango empieza antes/igual que hoy, aseguramos también hasta hoy+6
            if gen_desde <= hoy:
                gen_hasta = max(gen_hasta, hoy + timedelta(days=6))

        if debe_generar and gen_desde is not None and gen_hasta is not None:
            from app.services.generar_clases import generar_clases_para_rango

            # Verificar si ALGUNA fecha del rango [gen_desde, gen_hasta] está incompleta
            faltan_clases = False
            f = gen_desde
            while f <= gen_hasta:
                if f.weekday() == 6:  # domingo, skip
                    f += timedelta(days=1)
                    continue
                # Contar clases existentes para esta fecha
                count_clases = db.execute(
                    text(
                        "SELECT COUNT(*) FROM clases WHERE tenant_id = :tenant_id AND fecha = :fecha"),
                    {"tenant_id": tenant_id, "fecha": f}
                ).scalar()
                # Contar horarios_base activos para este día de semana
                count_horarios = db.execute(
                    text(
                        "SELECT COUNT(*) FROM horarios WHERE tenant_id = :tenant_id AND dia_semana = :ds AND activo = true"),
                    {"tenant_id": tenant_id, "ds": f.weekday()}
                ).scalar()
                if count_clases < count_horarios:
                    faltan_clases = True
                    logger.info(
                        f"🔍 [Auto-generación] {f} tiene {count_clases}/{count_horarios} clases (faltan {count_horarios - count_clases})")
                    break
                f += timedelta(days=1)

            if faltan_clases:
                logger.info(
                    f"🔄 [Auto-generación] Faltan clases en el rango [{gen_desde} -> {gen_hasta}], generando desde horarios_base...")
                resultado = generar_clases_para_rango(
                    db, tenant_id, fecha_desde=gen_desde, fecha_hasta=gen_hasta)
                if resultado["creadas"] > 0:
                    logger.info(
                        f"✅ [Auto-generación] Creadas {resultado['creadas']} clases (tenant={tenant_id})")
                else:
                    logger.info(
                        f"ℹ️ [Auto-generación] {resultado['message']}")
            else:
                logger.info(
                    f"✅ [Auto-generación] Rango completo, no es necesario generar")
    except Exception as e:
        logger.error(
            f"❌ [Auto-generación] Error al generar clases automáticamente: {e}", exc_info=True)

    conditions = ["c.tenant_id = :tenant_id"]
    query_params = {"tenant_id": tenant_id, "limit": limit, "skip": skip}
    if disciplina_id is not None:
        conditions.append("c.disciplina_id = :disciplina_id")
        query_params["disciplina_id"] = disciplina_id
    if coach_id is not None:
        conditions.append(
            "c.disciplina_id IN (SELECT disciplina_id FROM coach_disciplinas WHERE coach_id = :coach_id AND activo = true)")
        query_params["coach_id"] = coach_id
    if fecha is not None:
        conditions.append("c.fecha = :fecha")
        query_params["fecha"] = fecha
    if fecha_desde is not None:
        conditions.append("c.fecha >= :fecha_desde")
        query_params["fecha_desde"] = fecha_desde
    if fecha_hasta is not None:
        conditions.append("c.fecha <= :fecha_hasta")
        query_params["fecha_hasta"] = fecha_hasta
    if solo_con_cupo:
        conditions.append("c.asistentes_confirmados < c.cupo_maximo")
    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    query = text(f"""
        SELECT c.id, c.fecha, c.hora_inicio, c.hora_fin, c.disciplina_id, c.coach_id,
               c.wod_id,
               c.cupo_maximo, c.asistentes_confirmados, c.cancelada,
               c.horario_base_id, c.tenant_id, c.created_at, c.updated_at,
               d.nombre AS disciplina_nombre,
               u.nombre AS coach_nombre,
               CASE WHEN EXISTS (
                   SELECT 1 FROM cobertura_emergencia ce
                   WHERE ce.clase_id = c.id AND ce.tenant_id = c.tenant_id
               ) THEN true ELSE false END AS cobertura_emergencia
        FROM clases c
        LEFT JOIN disciplinas d ON c.disciplina_id = d.id
        LEFT JOIN usuarios u ON c.coach_id = u.id
        {where_clause}
        ORDER BY c.fecha DESC, c.hora_inicio ASC
        LIMIT :limit OFFSET :skip
    """)
    rows = db.execute(query, query_params).fetchall()

    # ── Fix N+1: precomputar en UNA sola query el coach unico activo por
    #    disciplina (fallback para clases sin coach_id asignado), evitando
    #    una query dentro del loop por cada clase. ──
    if rows:
        coach_fallback_por_disciplina = {}
        filas_fallback = db.execute(
            text("""
                SELECT cd.disciplina_id, u.nombre
                FROM coach_disciplinas cd
                JOIN usuarios u ON u.id = cd.coach_id
                WHERE cd.tenant_id = :tenant_id
                  AND cd.activo = true
                  AND u.activo = true
                GROUP BY cd.disciplina_id, u.nombre
            """),
            {"tenant_id": tenant_id}
        ).fetchall()
        from collections import defaultdict
        nombres_por_disc = defaultdict(list)
        for fdisc, fnombre in filas_fallback:
            nombres_por_disc[fdisc].append(fnombre)
        for disc_id, nombres in nombres_por_disc.items():
            if len(nombres) == 1:
                coach_fallback_por_disciplina[disc_id] = nombres[0]

    result = []
    for row in rows:
        coach_nombre = row.coach_nombre
        # Fallback: si la clase NO tiene coach, usar el UNICO coach activo
        # de esa disciplina (visible en el dict precomputado = 1 sola query).
        if row.coach_id is None and row.disciplina_id is not None:
            coach_nombre = coach_fallback_por_disciplina.get(
                row.disciplina_id, None)
        result.append({
            "id": row.id,
            "fecha": row.fecha,
            "hora_inicio": row.hora_inicio,
            "hora_fin": row.hora_fin,
            "disciplina_id": row.disciplina_id,
            "coach_id": row.coach_id,
            "wod_id": row.wod_id,
            "cupo_maximo": row.cupo_maximo,
            "asistentes_confirmados": row.asistentes_confirmados,
            "cancelada": row.cancelada,
            "disciplina_nombre": row.disciplina_nombre,
            "coach_nombre": coach_nombre,
            "cobertura_emergencia": bool(row.cobertura_emergencia),
        })
    return result


@router.get("/{clase_id}", response_model=schemas.ClaseResponse)
def obtener_clase(
    clase_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Query(1)
):
    clase = db.query(Clase).filter(
        Clase.id == clase_id,
        Clase.tenant_id == tenant_id
    ).first()

    if not clase:
        raise HTTPException(status_code=404, detail="Clase no encontrada")

    return clase


@router.post("/", response_model=schemas.ClaseResponse)
def crear_clase(
    clase: schemas.ClaseCreate,
    db: Session = Depends(get_db),
    tenant_id: int = Query(1)
):
    nueva_clase = Clase(
        tenant_id=tenant_id,
        horario_base_id=clase.horario_base_id,
        coach_id=clase.coach_id,
        disciplina_id=clase.disciplina_id,
        fecha=clase.fecha,
        hora_inicio=clase.hora_inicio,
        hora_fin=clase.hora_fin,
        cupo_maximo=clase.cupo_maximo,
        asistentes_confirmados=0,
        cancelada=False
    )

    db.add(nueva_clase)
    db.commit()
    db.refresh(nueva_clase)

    return nueva_clase


@router.put("/{clase_id}", response_model=schemas.ClaseResponse)
def actualizar_clase(
    clase_id: int,
    clase_update: schemas.ClaseUpdate,
    db: Session = Depends(get_db),
    tenant_id: int = Query(1),
    modo_emergencia: bool = Query(
        False, description="Si true, permite asignar coach de otra disciplina con auditoria")
):
    clase = db.query(Clase).filter(
        Clase.id == clase_id,
        Clase.tenant_id == tenant_id
    ).first()

    if not clase:
        raise HTTPException(status_code=404, detail="Clase no encontrada")

    # Si se actualiza coach_id, verificar relación coach-disciplina (con emergencia)
    if clase_update.coach_id is not None:
        try:
            verificar_coach_disciplina(
                coach_id=clase_update.coach_id,
                disciplina_id=clase.disciplina_id,
                db=db,
                modo_emergencia=modo_emergencia,
                clase_id=clase_id,
                accion="asignar_coach_admin",
                tenant_id=tenant_id
            )
        except HTTPException as e:
            if not modo_emergencia:
                raise e
            verificar_coach_disciplina(
                coach_id=clase_update.coach_id,
                disciplina_id=clase.disciplina_id,
                db=db,
                modo_emergencia=True,
                clase_id=clase_id,
                accion="asignar_coach_admin",
                tenant_id=tenant_id
            )
        clase.coach_id = clase_update.coach_id

    if clase_update.hora_inicio is not None:
        clase.hora_inicio = clase_update.hora_inicio
    if clase_update.hora_fin is not None:
        clase.hora_fin = clase_update.hora_fin
    if clase_update.cupo_maximo is not None:
        clase.cupo_maximo = clase_update.cupo_maximo

    db.commit()
    db.refresh(clase)

    return clase


@router.delete("/{clase_id}")
def eliminar_clase(
    clase_id: int,
    db: Session = Depends(get_db),
    tenant_id: int = Query(1)
):
    clase = db.query(Clase).filter(
        Clase.id == clase_id,
        Clase.tenant_id == tenant_id
    ).first()

    if not clase:
        raise HTTPException(status_code=404, detail="Clase no encontrada")

    db.delete(clase)
    db.commit()

    return {"mensaje": "Clase eliminada"}
