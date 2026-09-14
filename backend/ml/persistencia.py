"""
Persistencia de los modelos de ML en la tabla `ml_modelos` (BD, no disco).

- `guardar_modelo(db, tenant_id, tipo, modelo, metadata)` -> UPSERT por
  (tenant_id, tipo_modelo): siempre queda UN modelo vigente por tipo (el
  índice único lo garantiza).
- `cargar_modelo(db, tenant_id, tipo)` -> `(modelo, metadata)` o `(None, None)`.
- `info_modelos(db, tenant_id)` -> resumen sin deserializar (monitoreo/health).

Serialización con `pickle` (mismo formato que los .pkl que usábamos antes).
El llamador es responsable del `db.commit()`.

Los .pkl en disco se abandonaron a propósito: el filesystem de Render es
efímero y los artefactos se perdían en cada reinicio/redeploy.
"""
import json
import pickle
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.ml_modelo import TIPOS_MODELO, MlModelo


def guardar_modelo(db, tenant_id, tipo, modelo, metadata) -> dict:
    """Upsert del modelo vigente de (tenant, tipo). Devuelve un resumen.

    `ON CONFLICT (tenant_id, tipo_modelo) DO UPDATE` -> si ya existía un modelo
    del mismo tipo se reemplaza (no se acumulan versiones).
    """
    if tipo not in TIPOS_MODELO:
        raise ValueError(f"tipo de modelo inválido: {tipo!r} "
                         f"(esperado uno de {TIPOS_MODELO})")

    binario = pickle.dumps(modelo, protocol=pickle.HIGHEST_PROTOCOL)
    ahora = datetime.now(timezone.utc)
    valores = {
        "tenant_id": tenant_id,
        "tipo_modelo": tipo,
        "modelo_binario": binario,
        "metadata_json": json.dumps(metadata, ensure_ascii=False),
        "fecha_entrenamiento": ahora,
    }

    db.execute(
        pg_insert(MlModelo).values(**valores).on_conflict_do_update(
            index_elements=["tenant_id", "tipo_modelo"],
            set_={clave: valores[clave] for clave in (
                "modelo_binario", "metadata_json", "fecha_entrenamiento")},
        )
    )
    return {
        "tipo_modelo": tipo,
        "bytes": len(binario),
        "fecha_entrenamiento": ahora.isoformat(),
    }


def cargar_modelo(db, tenant_id, tipo):
    """Devuelve `(modelo, metadata)`. `(None, None)` si no hay modelo guardado."""
    fila = db.query(MlModelo).filter(
        MlModelo.tenant_id == tenant_id,
        MlModelo.tipo_modelo == tipo,
    ).first()
    if fila is None:
        return None, None
    modelo = pickle.loads(fila.modelo_binario)
    metadata = json.loads(fila.metadata_json) if fila.metadata_json else {}
    return modelo, metadata


def info_modelos(db, tenant_id) -> list:
    """Resumen de los modelos vigentes SIN deserializar (health/monitoreo)."""
    filas = db.query(MlModelo).filter(
        MlModelo.tenant_id == tenant_id).order_by(MlModelo.tipo_modelo).all()
    return [
        {
            "tipo_modelo": f.tipo_modelo,
            "fecha_entrenamiento": (
                f.fecha_entrenamiento.isoformat()
                if f.fecha_entrenamiento else None),
            "bytes": len(f.modelo_binario or b""),
        }
        for f in filas
    ]


def guardar_etiquetas_segmentacion(db, tenant_id, etiquetas, modelo_fecha) -> dict:
    """FULL REFRESH de `segmentacion_alumnos` del tenant (DELETE + INSERT).

    Mismo patrón que `predictions_churn` en `kpis_populate`: es una data mart
    DERIVADA, así que se borra y se reescribe completa en la MISMA transacción
    (el `db.commit()` lo hace el llamador, igual que en `guardar_modelo`).

    `etiquetas` = salida de `ml.segmentacion.entrenar_segmentacion`:
    `[{usuario_id, cluster_id, arquetipo, perfil_json}]`.

    Validaciones fail-fast ANTES de escribir: arquetipo perteneciente a
    `ml.segmentacion.ARQUETIPOS` y sin `usuario_id` repetidos (el UNIQUE de la
    tabla los rechazaría igual, pero así el error es claro).

    Devuelve `{"filas", "arquetipos", "modelo_fecha"}`.
    """
    # Import perezoso: no cargar pandas/sklearn al importar este módulo.
    from app.models.segmentacion_alumno import SegmentacionAlumno
    from ml.segmentacion import ARQUETIPOS

    vistos = set()
    conteos = {a: 0 for a in ARQUETIPOS}
    for e in etiquetas:
        arq = e["arquetipo"]
        if arq not in ARQUETIPOS:
            raise ValueError(f"arquetipo inválido: {arq!r} "
                             f"(esperado uno de {ARQUETIPOS})")
        if e["usuario_id"] in vistos:
            raise ValueError(f"usuario_id repetido: {e['usuario_id']}")
        vistos.add(e["usuario_id"])
        conteos[arq] += 1

    db.query(SegmentacionAlumno).filter(
        SegmentacionAlumno.tenant_id == tenant_id).delete()

    if etiquetas:
        db.add_all([
            SegmentacionAlumno(
                tenant_id=tenant_id,
                usuario_id=e["usuario_id"],
                cluster_id=e["cluster_id"],
                arquetipo=e["arquetipo"],
                perfil_json=json.dumps(e["perfil_json"], ensure_ascii=False),
                modelo_fecha=modelo_fecha,
            )
            for e in etiquetas
        ])
    return {
        "filas": len(etiquetas),
        "arquetipos": conteos,
        "modelo_fecha": modelo_fecha.isoformat(),
    }
