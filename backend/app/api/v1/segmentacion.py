"""Endpoints de SEGMENTACIÓN de alumnos (arquetipos de retención, K-Means K=5).

- `POST /api/v1/segmentacion/reentrenar`: entrena el modelo, lo persiste en
  `ml_modelos` (`tipo_modelo='segmentacion'`) y hace FULL REFRESH de las
  etiquetas en `segmentacion_alumnos`. PROTEGIDO con `X-N8N-API-Key` (mismo
  mecanismo que `app/api/v1/ml.py`, del que se IMPORTAN los helpers: no se
  duplica la lógica de auth ni el mapeo de errores).
- `GET  /api/v1/segmentacion`: resumen para el panel (conteos por arquetipo,
  fecha del modelo). Auth: token del usuario (`get_current_user`).

La lógica de dominio vive en `ml/segmentacion.py` y la persistencia en
`ml/persistencia.py`; acá solo se orquesta y se traduce a HTTP.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v1.ml import _clasificar_error, _verificar_api_key_n8n
from app.core.dependencies import get_current_user
from app.db.database import get_db
from app.models.segmentacion_alumno import SegmentacionAlumno

router = APIRouter(prefix="/api/v1/segmentacion", tags=["Segmentación"])

logger = logging.getLogger(__name__)

# Hoy hay un solo box (igual que ml.py y kpis_populate.py); parametrizable luego.
TENANT_ID = 1


@router.post("/reentrenar")
def reentrenar_segmentacion(
    db: Session = Depends(get_db),
    _auth: bool = Depends(_verificar_api_key_n8n),
):
    """Reentrena la segmentación y REFRESCA `segmentacion_alumnos`.

    Pasos en UNA transacción (el commit es al final):
      1. `entrenar_segmentacion` -> K-Means K=5 sobre las 5 features.
      2. UPSERT del artefacto en `ml_modelos` (tipo 'segmentacion').
      3. FULL REFRESH de las etiquetas por alumno (DELETE + INSERT).

    Si algo falla se hace `rollback`: no queda ni el modelo ni etiquetas a
    medias. Códigos: 409 (datos insuficientes) / 503 (falta scikit-learn) /
    500 (error inesperado) — mismos que `POST /ml/reentrenar`.
    """
    # Import perezoso: si falta scikit-learn/pandas o `ml/`, la app arranca
    # igual y solo falla este endpoint (503) en vez de romper el router entero.
    try:
        from ml.persistencia import (guardar_etiquetas_segmentacion,
                                     guardar_modelo)
        from ml.segmentacion import (ARQUETIPOS, DESCRIPCIONES,
                                     entrenar_segmentacion)
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"ML no disponible: {e}")

    tenant_id = TENANT_ID
    try:
        artefacto, metadata, etiquetas = entrenar_segmentacion(db, tenant_id)
        modelo_fecha = datetime.now(timezone.utc)
        persistido = guardar_modelo(db, tenant_id, "segmentacion",
                                    artefacto, metadata)
        resumen = guardar_etiquetas_segmentacion(db, tenant_id, etiquetas,
                                                 modelo_fecha)
        db.commit()
    except Exception as e:
        db.rollback()
        codigo, detalle = _clasificar_error(e)
        logger.warning("segmentacion/reentrenar falló (HTTP %s): %s",
                       codigo, e)
        raise HTTPException(status_code=codigo, detail=detalle)

    logger.info("segmentacion/reentrenar ok: %s etiquetas, silhouette=%s",
                resumen["filas"], metadata["silhouette"])
    return {
        "status": "ok",
        "tenant_id": tenant_id,
        "entrenado_en": modelo_fecha.isoformat(),
        "k": metadata["k"],
        "n_alumnos": metadata["n_alumnos"],
        "silhouette": metadata["silhouette"],
        # Los 6 arquetipos siempre (n=0 los que no disparan en esta corrida).
        "arquetipos": {
            arq: {"n": resumen["arquetipos"].get(arq, 0),
                  "descripcion": DESCRIPCIONES[arq]}
            for arq in ARQUETIPOS
        },
        "perfiles_cluster": metadata["perfiles_cluster"],
        "modelo_persistido": persistido,
        "etiquetas_persistidas": resumen,
    }


@router.get("")
def resumen_segmentacion(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Resumen de la segmentación vigente del box (conteos por arquetipo).

    Devuelve SIEMPRE los 6 arquetipos (con `n=0` los que no disparan) para que
    el panel no tenga que conocer la escalera. `modelo_fecha` es `None` si el
    reentrenamiento todavía no corrió (tabla vacía).
    """
    try:
        from ml.segmentacion import ARQUETIPOS, DESCRIPCIONES
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"ML no disponible: {e}")

    tenant_id = current_user["tenant_id"]

    filas = db.query(
        SegmentacionAlumno.arquetipo, func.count(SegmentacionAlumno.id),
    ).filter(
        SegmentacionAlumno.tenant_id == tenant_id,
    ).group_by(SegmentacionAlumno.arquetipo).all()
    conteos = {arq: int(n) for arq, n in filas}
    total = sum(conteos.values())

    modelo_fecha = db.query(func.max(SegmentacionAlumno.modelo_fecha)).filter(
        SegmentacionAlumno.tenant_id == tenant_id).scalar()

    return {
        "total": total,
        "modelo_fecha": modelo_fecha.isoformat() if modelo_fecha else None,
        "arquetipos": [
            {
                "arquetipo": arq,
                "n": conteos.get(arq, 0),
                "pct": round(conteos.get(arq, 0) / total * 100, 1) if total
                       else 0.0,
                "descripcion": DESCRIPCIONES[arq],
            }
            for arq in ARQUETIPOS
        ],
    }
