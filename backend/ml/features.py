"""
Extracción de features para los modelos de ML (churn / forecast).

Reusa los MISMOS criterios que `app/api/v1/kpis_populate.py`, para que lo que
aprende el modelo coincida con lo que ya calcula el backend:

  - `_dias_inactividad`  -> dias_desde_ultima_asistencia (con fallback a created_at)
  - `_ultima_asistencia` -> última fecha en la tabla `asistencias`
  - suscripción activa   -> estado == 'activo' AND fecha_expiracion >= hoy

Uso:
    import ml.features as features
    df = features.build_features(db, tenant_id=1)          # 1 fila por alumno
"""
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import func

from app.models.asistencia import Asistencia
from app.models.suscripcion import Suscripcion
from app.models.usuario import RolUsuario, Usuario

# Regla del label de abandono (idéntica a la del seed sintético ml.seed.*).
UMBRAL_ABANDONO_DIAS = 45
VENTANAS_DIAS = (30, 60, 90)

# Columnas que consume el modelo (orden estable).
FEATURE_COLS = [
    "dias_desde_ultima_asistencia",
    "asistencias_ultimos_30_dias",
    "asistencias_ultimos_60_dias",
    "asistencias_ultimos_90_dias",
    "antiguedad_dias",
    "tiene_suscripcion_activa",
    "dias_para_vencer_plan",
]
# Identificadores: NO son features (sirven para auditar/reportar).
ID_COLS = ["usuario_id", "correo"]


def dias_desde_ultima_asistencia(ultima, created_at, fecha_ref):
    """Días desde la última asistencia; si nunca asistió, desde el registro.

    Réplica exacta de `kpis_populate._dias_inactividad` (el fix del 999 fijo).
    """
    referencia = ultima or (created_at.date() if created_at else None)
    if referencia is None:
        return 0
    return max(0, (fecha_ref - referencia).days)


def label_abandonado(dias_inactivo: int, tiene_susc_activa: bool) -> bool:
    """Label real de churn: sin suscripción activa Y >45 días sin asistir.

    Misma regla que el seed `ml.seed.*` y que el ETL de churn.
    """
    return (not tiene_susc_activa) and dias_inactivo > UMBRAL_ABANDONO_DIAS


def _ultima_asistencia(db, tenant_id, usuario_id, hasta=None):
    """Última fecha de asistencia (None si nunca fue).

    `hasta` acota la búsqueda a `fecha <= hasta`: imprescindible para calcular
    features "as-of" (si no, veríamos asistencias POSTERIORES a la fecha de
    corte = fuga de información del futuro).
    """
    q = db.query(func.max(Asistencia.fecha)).filter(
        Asistencia.tenant_id == tenant_id,
        Asistencia.usuario_id == usuario_id,
    )
    if hasta is not None:
        q = q.filter(Asistencia.fecha <= hasta)
    return q.scalar()


def _asistencias_en_ventana(db, tenant_id, usuario_id, desde, hasta):
    """Cuenta de asistencias en el rango [desde, hasta]."""
    return db.query(func.count(Asistencia.id)).filter(
        Asistencia.tenant_id == tenant_id,
        Asistencia.usuario_id == usuario_id,
        Asistencia.fecha >= desde,
        Asistencia.fecha <= hasta,
    ).scalar() or 0


def _suscripcion_activa(db, tenant_id, usuario_id, fecha_ref):
    """(tiene_activa, dias_para_vencer) de la suscripción VIGENTE a `fecha_ref`.

    ⚠️ LIMITACIÓN (documentada a propósito): `suscripciones.estado` es un
    SNAPSHOT MUTABLE (no hay historial de cambios de estado), así que no sirve
    para reconstruir el pasado. Se aproxima con las FECHAS, que sí son hechos
    inmutables:

        estaba activa a fecha_ref  <=>  fecha_inicio <= fecha_ref <= fecha_expiracion

    Consecuencias de la aproximación:
      - NO se usa `estado`: una suscripción cancelada después sigue contando
        como activa para fechas anteriores a su `fecha_expiracion`.
      - `dias_para_vencer` nunca es negativo (a lo sumo 0 = vence ese día).
    """
    vence = db.query(func.max(Suscripcion.fecha_expiracion)).filter(
        Suscripcion.tenant_id == tenant_id,
        Suscripcion.usuario_id == usuario_id,
        func.date(Suscripcion.fecha_inicio) <= fecha_ref,
        func.date(Suscripcion.fecha_expiracion) >= fecha_ref,
    ).scalar()
    if not vence:
        return False, None
    vence_date = vence.date()
    return True, (vence_date - fecha_ref).days


def features_alumno(db, tenant_id, alumno, fecha_ref) -> dict:
    """Features de UN alumno **a `fecha_ref`** (as-of: sólo datos <= esa fecha)."""
    ultima = _ultima_asistencia(db, tenant_id, alumno.id, hasta=fecha_ref)
    tiene_activa, dias_vencer = _suscripcion_activa(
        db, tenant_id, alumno.id, fecha_ref)
    antiguedad = ((fecha_ref - alumno.created_at.date()).days
                  if alumno.created_at else 0)

    fila = {
        "usuario_id": alumno.id,
        "correo": alumno.correo,
        "dias_desde_ultima_asistencia": dias_desde_ultima_asistencia(
            ultima, alumno.created_at, fecha_ref),
        "antiguedad_dias": max(0, antiguedad),
        "tiene_suscripcion_activa": tiene_activa,
        "dias_para_vencer_plan": dias_vencer,
    }
    for dias in VENTANAS_DIAS:
        fila[f"asistencias_ultimos_{dias}_dias"] = _asistencias_en_ventana(
            db, tenant_id, alumno.id, fecha_ref - timedelta(days=dias), fecha_ref)
    return fila


def cargar_alumnos(db, tenant_id):
    """Todos los alumnos (rol=alumno) del tenant, sin filtrar por `estado`."""
    return db.query(Usuario).filter(
        Usuario.tenant_id == tenant_id,
        Usuario.rol == RolUsuario.alumno,
    ).order_by(Usuario.id).all()


def build_features(db, tenant_id, fecha_ref=None) -> pd.DataFrame:
    """DataFrame con 1 fila por alumno (columnas = ID_COLS + FEATURE_COLS).

    `dias_para_vencer_plan` queda en None cuando el alumno no tiene plan activo
    (es el único campo que puede venir nulo).

    Rendimiento: usa 5 queries AGREGADAS (GROUP BY) en vez de ~6 por alumno.
    Con Neon y ~100 alumnos, la versión por alumno tardaba minutos; esta tarda
    segundos. Los features son idénticos a `features_alumno()`.
    """
    fecha_ref = fecha_ref or date.today()
    alumnos = cargar_alumnos(db, tenant_id)
    if not alumnos:
        return pd.DataFrame(columns=ID_COLS + FEATURE_COLS)

    ids = [a.id for a in alumnos]

    # 1) última asistencia por alumno (AS-OF: sólo hasta fecha_ref; sin la cota
    #    superior se verían asistencias POSTERIORES = fuga del futuro)
    ultimas = dict(db.query(
        Asistencia.usuario_id, func.max(Asistencia.fecha)
    ).filter(
        Asistencia.tenant_id == tenant_id,
        Asistencia.usuario_id.in_(ids),
        Asistencia.fecha <= fecha_ref,
    ).group_by(Asistencia.usuario_id).all())

    # 2) conteo de asistencias por ventana (1 query por ventana)
    conteos = {}
    for dias in VENTANAS_DIAS:
        conteos[dias] = dict(db.query(
            Asistencia.usuario_id, func.count(Asistencia.id)
        ).filter(
            Asistencia.tenant_id == tenant_id,
            Asistencia.usuario_id.in_(ids),
            Asistencia.fecha >= fecha_ref - timedelta(days=dias),
            Asistencia.fecha <= fecha_ref,
        ).group_by(Asistencia.usuario_id).all())

    # 3) vencimiento MÁS LEJANO entre las suscripciones VIGENTES a fecha_ref.
    #    AS-OF con FECHAS (no con `estado`, que es un snapshot mutable): ver el
    #    detalle/limitación en `_suscripcion_activa`.
    vencimientos = dict(db.query(
        Suscripcion.usuario_id, func.max(Suscripcion.fecha_expiracion)
    ).filter(
        Suscripcion.tenant_id == tenant_id,
        Suscripcion.usuario_id.in_(ids),
        func.date(Suscripcion.fecha_inicio) <= fecha_ref,
        func.date(Suscripcion.fecha_expiracion) >= fecha_ref,
    ).group_by(Suscripcion.usuario_id).all())

    filas = []
    for alumno in alumnos:
        vence = vencimientos.get(alumno.id)
        vence_date = vence.date() if vence else None
        antiguedad = ((fecha_ref - alumno.created_at.date()).days
                      if alumno.created_at else 0)
        fila = {
            "usuario_id": alumno.id,
            "correo": alumno.correo,
            "dias_desde_ultima_asistencia": dias_desde_ultima_asistencia(
                ultimas.get(alumno.id), alumno.created_at, fecha_ref),
            "antiguedad_dias": max(0, antiguedad),
            # As-of: la query ya garantiza fecha_expiracion >= fecha_ref.
            "tiene_suscripcion_activa": vence_date is not None,
            "dias_para_vencer_plan": (
                (vence_date - fecha_ref).days if vence_date else None),
        }
        for dias in VENTANAS_DIAS:
            fila[f"asistencias_ultimos_{dias}_dias"] = conteos[dias].get(
                alumno.id, 0)
        filas.append(fila)

    return pd.DataFrame(filas, columns=ID_COLS + FEATURE_COLS)
