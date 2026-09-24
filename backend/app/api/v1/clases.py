import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
from datetime import datetime, date, time, timedelta

from app.db.database import get_db
from app.models.clase import Clase
from app.models.coach_disciplina import CoachDisciplina
from app.services.auditoria_service import registrar_auditoria
from app.schemas import clase as schemas
from app.core.dependencies import (
    verificar_coach_disciplina, get_current_coach, get_current_user,
)

logger = logging.getLogger("uvicorn.clases")

router = APIRouter(tags=["Clases"])


@router.get("/", response_model=List[schemas.ClaseListItem])
def listar_clases(
    db: Session = Depends(get_db),
    tenant_id: Optional[int] = Query(None),
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
    generar: bool = Query(
        False,
        description="Generar las clases faltantes del rango desde horarios_base. "
                    "OPT-IN (default false): un GET no debe escribir. Para forzar la "
                    "generacion usar POST /horarios/generar-clases-dia."),
    skip: int = Query(0),
    limit: int = Query(100),
    current_user: dict = Depends(get_current_user),
):
    # 🔒 SEGURIDAD: tenant_id SIEMPRE del token JWT (nunca del query).
    tenant_id = current_user["tenant_id"]

    # ── RESPALDO AUTOMÁTICO: Si se consulta un rango y faltan clases,
    #    se generan automáticamente desde horarios_base ──
    try:
        if generar:
            from datetime import timedelta
            from app.services.generar_clases import DIAS_ANTICIPACION
            hoy = date.today()
            # ¿Qué rango se está consultando?
            rango_desde = fecha_desde if fecha_desde is not None else (
                fecha if fecha is not None else hoy)
            rango_hasta = fecha_hasta if fecha_hasta is not None else (
                fecha if fecha is not None else hoy)

            # Determinar si debemos auto-generar:
            #  - Si el rango consultado es futuro (rango_desde > hoy), generar para ESE rango.
            #  - Si el rango incluye hoy o días cercanos, generar hasta hoy+28 (4 semanas).
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
                # (no solo [hoy, hoy+28]) para que navegar a semanas futuras funcione.
                debe_generar = True
                gen_desde = rango_desde
                gen_hasta = rango_hasta
                # Si el rango empieza antes/igual que hoy, aseguramos también hasta hoy+28
                if gen_desde <= hoy:
                    gen_hasta = max(gen_hasta, hoy + timedelta(days=DIAS_ANTICIPACION))

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
               c.cupo_maximo, c.cupo_original, c.asistentes_confirmados, c.cancelada,
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
            "cupo_original": row.cupo_original,
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
    tenant_id: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    # 🔒 SEGURIDAD: tenant_id del token; el query param se ignora.
    tenant_id = current_user["tenant_id"]

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
    tenant_id: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_coach),
):
    # 🔒 SEGURIDAD: tenant_id SIEMPRE del token JWT.
    tenant_id = current_user["tenant_id"]
    rol = current_user.get("rol", "")
    es_admin = rol in ("admin", "administrador")

    # ── H-02: un coach solo crea clases de SUS disciplinas y a SU nombre ──
    # Antes se aceptaban tal cual el disciplina_id y el coach_id del body: un coach
    # podia crear clases de otra disciplina y asignarlas a otro coach.
    if not es_admin:
        if clase.disciplina_id:
            verificar_coach_disciplina(
                current_user["usuario_id"], clase.disciplina_id, db,
                accion="crear_clase", tenant_id=tenant_id)
        coach_id = current_user["usuario_id"]
    else:
        coach_id = clase.coach_id or current_user["usuario_id"]

    nueva_clase = Clase(
        tenant_id=tenant_id,
        horario_base_id=clase.horario_base_id,
        coach_id=coach_id,
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
    tenant_id: Optional[int] = Query(None),
    modo_emergencia: bool = Query(
        False, description="Si true, permite asignar coach de otra disciplina con auditoria"),
    current_user: dict = Depends(get_current_coach),
):
    # 🔒 SEGURIDAD: tenant_id SIEMPRE del token JWT.
    tenant_id = current_user["tenant_id"]

    clase = db.query(Clase).filter(
        Clase.id == clase_id,
        Clase.tenant_id == tenant_id
    ).first()

    if not clase:
        raise HTTPException(status_code=404, detail="Clase no encontrada")

    # ── FIX S11 (seguridad): solo admin reasigna un TERCER coach ──
    # Un coach puede auto-asignarse (cobertura de emergencia propia, intencional)
    # pero NO puede asignar a otro coach: eso es exclusivo de admin (Supervisión).
    # La auditoría distingue quién lo hizo (asignar_coach_admin vs _self).
    rol = current_user.get("rol", "")
    es_admin = rol in ("admin", "administrador")

    # Si se actualiza coach_id, verificar relación coach-disciplina (con emergencia)
    if clase_update.coach_id is not None:
        if not es_admin and clase_update.coach_id != current_user["usuario_id"]:
            raise HTTPException(
                status_code=403,
                detail="Solo un administrador puede asignar otro coach a una clase",
            )
        accion = "asignar_coach_admin" if es_admin else "asignar_coach_self"
        try:
            verificar_coach_disciplina(
                coach_id=clase_update.coach_id,
                disciplina_id=clase.disciplina_id,
                db=db,
                modo_emergencia=modo_emergencia,
                clase_id=clase_id,
                accion=accion,
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
                accion=accion,
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
    tenant_id: Optional[int] = Query(None),
    current_user: dict = Depends(get_current_coach),
):
    # 🔒 SEGURIDAD: tenant_id SIEMPRE del token JWT.
    tenant_id = current_user["tenant_id"]

    clase = db.query(Clase).filter(
        Clase.id == clase_id,
        Clase.tenant_id == tenant_id
    ).first()

    if not clase:
        raise HTTPException(status_code=404, detail="Clase no encontrada")

    db.delete(clase)
    db.commit()

    return {"mensaje": "Clase eliminada"}


@router.post("/{clase_id}/ampliar-cupo")
def ampliar_cupo_clase(
    clase_id: int,
    body: schemas.AmpliarCupoRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_coach),
):
    """Amplia el cupo de UNA clase puntual (max +10 sobre el cupo original).

    Coach: solo sus clases asignadas (coach_id == usuario_id) o de sus disciplinas
    asignadas. Admin/administrador: cualquier clase de su tenant.
    No toca horarios (config general) ni el PUT /clases/{id}.
    """
    # SEGURIDAD: tenant_id SIEMPRE del token JWT.
    tenant_id = current_user["tenant_id"]
    rol = current_user.get("rol", "")
    es_admin = rol in ("admin", "administrador")

    clase = db.query(Clase).filter(
        Clase.id == clase_id,
        Clase.tenant_id == tenant_id,
    ).first()
    if not clase:
        raise HTTPException(status_code=404, detail="Clase no encontrada")

    if not es_admin:
        es_suya = clase.coach_id == current_user["usuario_id"]
        if not es_suya and clase.disciplina_id:
            es_suya = db.query(CoachDisciplina).filter(
                CoachDisciplina.coach_id == current_user["usuario_id"],
                CoachDisciplina.disciplina_id == clase.disciplina_id,
                CoachDisciplina.tenant_id == tenant_id,
                CoachDisciplina.activo == True,  # noqa: E712
            ).first() is not None
        if not es_suya:
            raise HTTPException(
                status_code=403,
                detail="Solo podes ampliar el cupo de tus clases o de tus disciplinas asignadas",
            )

    original = clase.cupo_original or clase.cupo_maximo
    tope = original + 10
    if clase.cupo_maximo + body.cupos_extra > tope:
        raise HTTPException(
            status_code=409,
            detail="Tope alcanzado: cupo original %s, maximo permitido %s" % (original, tope),
        )

    cupo_antes = clase.cupo_maximo
    # UPDATE atomico (evita perder una ampliacion si dos coinciden).
    result = db.execute(
        text(
            "UPDATE clases SET cupo_maximo = cupo_maximo + :n, updated_at = now() "
            "WHERE id = :cid AND tenant_id = :tid AND cupo_maximo + :n <= :tope"
        ),
        {"n": body.cupos_extra, "cid": clase_id, "tid": tenant_id, "tope": tope},
    )
    if result.rowcount == 0:
        db.rollback()
        raise HTTPException(status_code=409, detail="No se pudo ampliar: tope alcanzado")

    db.commit()
    db.refresh(clase)

    # Auditoria DESPUES del commit del UPDATE: si el UPDATE fallo, no queda fila falsa.
    registrar_auditoria(
        db=db,
        tenant_id=tenant_id,
        usuario_id=current_user["usuario_id"],
        accion="ampliar_cupo_clase",
        entidad="clase",
        entidad_id=clase_id,
        detalle={
            "cupos_extra": body.cupos_extra,
            "cupo_antes": cupo_antes,
            "cupo_despues": clase.cupo_maximo,
            "cupo_original": original,
            "rol": rol or "desconocido",
        },
    )
    return {
        "ok": True,
        "clase_id": clase.id,
        "cupo_maximo": clase.cupo_maximo,
        "cupo_original": original,
        "tope": tope,
        "extra_disponible": tope - clase.cupo_maximo,
    }