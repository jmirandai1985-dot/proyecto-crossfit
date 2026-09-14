"""
Segmentación de alumnos por retención — K-Means (K=5) + escalera de 6 tramos.

Diseño validado contra PROD (106 alumnos; análisis de fases 1-2):
  - 5 features, con las MISMAS queries que `ml/features.py` (= kpis_populate).
  - K=5 > K=4 en silhouette (0.4699 vs 0.4450) y estable con 10 semillas
    (ARI mínimo 0.9714; 9 de 10 semillas dan la MISMA partición).
  - Las features derivadas (`ratio_caida` / `asist_semanal_90`) se DESCARTARON:
    son funciones de estas 5 (colineales), bajan la estabilidad (ARI min 0.873)
    y mezclan grupos (aparecía un cluster con 68% de suscripción).

La escalera etiqueta CLUSTERS (no alumnos sueltos): todos los miembros de un
cluster reciben el arquetipo del cluster, evaluado sobre MEDIANAS (robusto a
outliers). Las 6 reglas están documentadas en `etiquetar_cluster`.

Uso:
    import ml.segmentacion as seg
    artefacto, metadata, etiquetas = seg.entrenar_segmentacion(db, tenant_id=1)
"""
from datetime import date, datetime, timezone

import pandas as pd

import ml.features as features

# ── Configuración (validada empíricamente; NO cambiar sin re-validar) ────────
K_CLUSTERS = 5
RANDOM_STATE = 42
N_INIT = 10
# Con menos alumnos K-Means no es confiable -> ValueError (HTTP 409).
MIN_ALUMNOS = 25
FEATURES_SEGMENTACION = [
    "dias_desde_ultima_asistencia",
    "asistencias_ultimos_30_dias",
    "asistencias_ultimos_90_dias",
    "antiguedad_dias",
    "tiene_suscripcion_activa",
]
# Reusa el umbral del label de churn del proyecto (45 días) -> una sola fuente.
UMBRAL_ABANDONO_DIAS = features.UMBRAL_ABANDONO_DIAS

# Los 6 valores posibles de `arquetipo` (orden = prioridad en la escalera).
ARQUETIPOS = (
    "ABANDONADO_PERDIDO",
    "ABANDONADO_RECUPERABLE",
    "EN_RIESGO",
    "NUEVO",
    "ACTIVO_EN_DECLIVE",
    "ACTIVO_FIEL",
)
DESCRIPCIONES = {
    "ABANDONADO_PERDIDO":
        "Sin plan y más de 45 días sin venir (sin asistencias en 90 días).",
    "ABANDONADO_RECUPERABLE":
        "Sin plan y más de 45 días sin venir, pero con historial reciente: "
        "candidato a campaña de recuperación.",
    "EN_RIESGO":
        "Se está alejando (más de 30 días sin venir) sin llegar al umbral de "
        "abandono.",
    "NUEVO":
        "Recién incorporado (hasta 60 días) que ya entrena con frecuencia.",
    "ACTIVO_EN_DECLIVE":
        "Con plan activo pero bajó la frecuencia (menos de 8 asistencias en "
        "30 días).",
    "ACTIVO_FIEL":
        "Alta frecuencia sostenida (8 o más asistencias en 30 días).",
}


def etiquetar_cluster(m: dict) -> tuple:
    """Escalera de 6 tramos: devuelve `(arquetipo, regla)`.

    `m` = métricas del cluster (`_metricas_cluster`). Orden = PRIORIDAD (gana la
    primera que matchea):

      L1 ABANDONADO_PERDIDO     : %susc < 0.50 Y med(dias) > 45 Y med(a90) == 0
      L2 ABANDONADO_RECUPERABLE : %susc < 0.50 Y med(dias) > 45 Y med(a90)  > 0
      L3 EN_RIESGO              : med(dias) > 30
      L4 NUEVO                  : med(antiguedad) <= 60 Y med(dias) <= 10
      L5 ACTIVO_EN_DECLIVE      : med(asist_30) < 8
      L6 ACTIVO_FIEL            : (default) alta frecuencia sostenida
    """
    med = m["medianas"]
    dias = med["dias_desde_ultima_asistencia"]
    a30 = med["asistencias_ultimos_30_dias"]
    a90 = med["asistencias_ultimos_90_dias"]
    ant = med["antiguedad_dias"]
    susc = m["pct_suscripcion_activa"]

    if susc < 0.50 and dias > UMBRAL_ABANDONO_DIAS:
        if a90 == 0:
            return "ABANDONADO_PERDIDO", "L1"
        return "ABANDONADO_RECUPERABLE", "L2"
    if dias > 30:
        return "EN_RIESGO", "L3"
    if ant <= 60 and dias <= 10:
        return "NUEVO", "L4"
    if a30 < 8:
        return "ACTIVO_EN_DECLIVE", "L5"
    return "ACTIVO_FIEL", "L6"


def _metricas_cluster(sub: pd.DataFrame) -> dict:
    """n, % de suscripción activa y MEDIANAS de las 5 features del cluster."""
    med = sub[FEATURES_SEGMENTACION].median()
    return {
        "n_alumnos": int(len(sub)),
        "pct_suscripcion_activa": round(
            float(sub["tiene_suscripcion_activa"].mean()), 4),
        "medianas": {f: round(float(med[f]), 2)
                     for f in FEATURES_SEGMENTACION},
    }


def entrenar_segmentacion(db, tenant_id, fecha_ref=None, k=K_CLUSTERS,
                          random_state=RANDOM_STATE):
    """Entrena K-Means y arma las etiquetas por alumno.

    Devuelve `(artefacto, metadata, etiquetas)`:
      - `artefacto`: dict picklable -> se persiste en `ml_modelos`
        (`tipo_modelo='segmentacion'`).
      - `metadata` : JSON-serializable (métricas + perfiles + reglas).
      - `etiquetas`: filas para `segmentacion_alumnos` (full refresh).
    """
    try:
        import sklearn
        from sklearn.cluster import KMeans
        from sklearn.metrics import silhouette_score
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as e:
        raise RuntimeError(
            f"falta scikit-learn ({e}); instalá con: "
            f"pip install -r requirements.txt") from e

    fecha_ref = fecha_ref or date.today()
    df = features.build_features(db, tenant_id, fecha_ref)
    if df.empty:
        raise ValueError("no hay alumnos (rol=alumno) en el tenant")
    if len(df) < max(MIN_ALUMNOS, k * 2):
        raise ValueError(
            f"muy pocos alumnos para segmentar: {len(df)} "
            f"(mínimo {max(MIN_ALUMNOS, k * 2)})")

    X = df[FEATURES_SEGMENTACION].astype(float)
    # Escalado obligatorio (distancia euclídea): sin escalar, las ventanas de 90
    # días aplastarían a las features binarias/pequeñas.
    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("kmeans", KMeans(n_clusters=k, n_init=N_INIT,
                          random_state=random_state)),
    ])
    labels = pipe.fit_predict(X)
    X_esc = pipe.named_steps["scaler"].transform(X)
    sil = float(silhouette_score(X_esc, labels))

    perfiles, nombres, reglas = {}, {}, {}
    for c in range(k):
        m = _metricas_cluster(df[labels == c])
        nombre, regla = etiquetar_cluster(m)
        perfiles[c], nombres[c], reglas[c] = m, nombre, regla
    conteos = {a: 0 for a in ARQUETIPOS}
    for c, nombre in nombres.items():
        conteos[nombre] += perfiles[c]["n_alumnos"]

    resumen_modelo = {
        "k": k, "n_init": N_INIT, "random_state": random_state,
        "silhouette": round(sil, 4), "features": FEATURES_SEGMENTACION,
    }
    etiquetas = []
    for i, uid in enumerate(df["usuario_id"].tolist()):
        c = int(labels[i])
        fila = df.iloc[i]
        etiquetas.append({
            "usuario_id": int(uid),
            "cluster_id": c,
            "arquetipo": nombres[c],
            "perfil_json": {
                "modelo": resumen_modelo,
                "cluster": dict(perfiles[c], cluster_id=c, regla=reglas[c],
                                arquetipo=nombres[c]),
                "alumno": {f: int(fila[f]) for f in FEATURES_SEGMENTACION},
            },
        })

    metadata = {
        "modelo": f"KMeans(K={k}) + StandardScaler",
        "objetivo": "segmentación de alumnos por retención (arquetipos)",
        "fecha_entrenamiento": datetime.now(timezone.utc).isoformat(),
        "fecha_referencia": str(fecha_ref),
        "tenant_id": tenant_id,
        "n_alumnos": int(len(df)),
        "k": k,
        "n_init": N_INIT,
        "random_state": random_state,
        "feature_cols": FEATURES_SEGMENTACION,
        "silhouette": round(sil, 4),
        "arquetipos": conteos,
        "perfiles_cluster": {str(c): perfiles[c] for c in perfiles},
        "reglas_cluster": {str(c): reglas[c] for c in reglas},
        "nombres_cluster": {str(c): nombres[c] for c in nombres},
        "escalera": [
            "L1 ABANDONADO_PERDIDO: %susc<0.50 Y med(dias)>45 Y med(a90)==0",
            "L2 ABANDONADO_RECUPERABLE: %susc<0.50 Y med(dias)>45 Y med(a90)>0",
            "L3 EN_RIESGO: med(dias)>30",
            "L4 NUEVO: med(antiguedad)<=60 Y med(dias)<=10",
            "L5 ACTIVO_EN_DECLIVE: med(asist_30)<8",
            "L6 ACTIVO_FIEL: (default)",
        ],
        "descripciones": DESCRIPCIONES,
        "version_sklearn": sklearn.__version__,
    }
    artefacto = {
        "pipeline": pipe,
        "k": k,
        "features": FEATURES_SEGMENTACION,
        "arquetipos_por_cluster": nombres,
        "perfiles": perfiles,
        "silhouette": sil,
    }
    return artefacto, metadata, etiquetas
