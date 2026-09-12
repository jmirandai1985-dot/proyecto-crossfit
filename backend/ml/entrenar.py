"""
Entrenamiento de los modelos de ML (lógica reusable, SIN tocar disco).

    entrenar_churn(db, tenant_id)    -> (RandomForestClassifier, metadata dict)
    entrenar_forecast(db, tenant_id) -> (LinearRegression,       metadata dict)

- Features de churn: `ml/features.py` (mismas queries que kpis_populate.py).
- Label de churn   : abandonado = (sin suscripción activa) AND (>45 días sin
                     asistir) -> la misma regla del seed sintético `ml.seed.*`.
- Forecast         : ingreso neto mensual ~ tendencia + sin/cos del mes.

La persistencia la hace `ml/persistencia.py` (tabla `ml_modelos`).
scikit-learn se importa DENTRO de las funciones: si falta, la app arranca igual
y sólo falla el endpoint que entrena (error claro en vez de un import roto).
"""
import calendar
import math
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import func

import ml.features as features
from app.models.asistencia import Asistencia
from app.models.suscripcion import Suscripcion
from app.models.transaccion_financiera import TransaccionFinanciera

# ── Hiperparámetros (ajustables desde el endpoint/CLI) ──
RANDOM_STATE = 42
TEST_SIZE = 0.30
N_ESTIMATORS = 300
MESES_PROYECCION = 6
# Horizonte de predicción del churn: features "de hace N días" -> label de hoy.
DIAS_HORIZONTE = 30
# Cross-validation: sólo para REPORTAR métricas más estables (media ± std).
# El modelo que se persiste es el del split único de abajo, no se reentrena.
CV_FOLDS = 5


def entrenar_churn(db, tenant_id, fecha_ref=None,
                   dias_horizonte=DIAS_HORIZONTE, random_state=RANDOM_STATE,
                   test_size=TEST_SIZE, n_estimators=N_ESTIMATORS):
    """Entrena el RandomForest de churn con PREDICCIÓN HACIA ADELANTE.

    Metodología (label de EVENTO FUTURO; sin fuga posible):
      - `fecha_corte = fecha_ref - dias_horizonte` (hace 30 días): X se calcula
        AS-OF con la información disponible hasta esa fecha (nada posterior).
      - LABEL: "abandonó en la ventana (fecha_corte, fecha_ref]" <=>
        NO tiene NINGUNA asistencia en esa ventana
        Y  NO tiene suscripción activa a fecha_ref.
      Pregunta que responde: "¿con lo que sabíamos hace 30 días, el alumno va a
      desaparecer en los próximos 30 días?".

    Por qué esto NO se puede leakear: el positivo depende de lo que ocurre
    DESPUÉS del corte y las features sólo miran hacia atrás. (Con el label
    anterior —ninguna separación temporal entre features y label—
    `dias_desde_ultima_asistencia` era la variable del label desplazada 30 días
    y el modelo sacaba 1.0 memorizando la fórmula.)

    Métricas: se reportan DOS juegos —
      - `metricas_test`: el split único train/test (referencia, se mantiene).
      - `cross_validation`: media ± std de 5 folds (StratifiedKFold), mucho más
        estable con un dataset chico (19 positivos: 1 caso mueve precision y
        recall ~0.1).
    El modelo que se PERSISTE es el del split único; la CV sólo reporta (no se
    entrenan 5 modelos para producción).

    Devuelve `(modelo, metadata)`; `metadata` es JSON-serializable.
    """
    try:
        import numpy as np
        import sklearn
        from sklearn.base import clone
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.metrics import (accuracy_score, confusion_matrix,
                                     precision_score, recall_score)
        from sklearn.model_selection import (StratifiedKFold, cross_validate,
                                             train_test_split)
    except ImportError as e:
        raise RuntimeError(
            f"falta scikit-learn ({e}); instalá con: "
            f"pip install -r requirements.txt") from e

    fecha_ref = fecha_ref or date.today()
    fecha_corte = fecha_ref - timedelta(days=dias_horizonte)

    # ── X: features AS-OF a la fecha de corte (no ven nada posterior) ──
    df = features.build_features(db, tenant_id, fecha_corte)
    if df.empty:
        raise ValueError("no hay alumnos (rol=alumno) en el tenant")
    ids = df["usuario_id"].tolist()

    # ── y: EVENTO FUTURO en la ventana (fecha_corte, fecha_ref] ──
    # 1) "silencio total": CERO asistencias en la ventana posterior al corte.
    #    Las features no pueden ver esta ventana -> no hay fuga posible.
    asistencias_ventana = dict(db.query(
        Asistencia.usuario_id, func.count(Asistencia.id)
    ).filter(
        Asistencia.tenant_id == tenant_id,
        Asistencia.usuario_id.in_(ids),
        Asistencia.fecha > fecha_corte,
        Asistencia.fecha <= fecha_ref,
    ).group_by(Asistencia.usuario_id).all())

    # 2) sin suscripción activa a HOY. Acá SÍ se usa el estado actual de
    #    `suscripciones.estado`: fecha_ref es hoy, no una fecha pasada.
    con_suscripcion_hoy = {uid for (uid,) in db.query(
        Suscripcion.usuario_id
    ).filter(
        Suscripcion.tenant_id == tenant_id,
        Suscripcion.usuario_id.in_(ids),
        Suscripcion.estado == "activo",
        Suscripcion.fecha_expiracion >= fecha_ref,
    ).distinct().all()}

    df["abandonado"] = [
        (asistencias_ventana.get(uid, 0) == 0)
        and (uid not in con_suscripcion_hoy)
        for uid in ids
    ]
    # `dias_para_vencer_plan` es None si no hay plan activo -> sentinel -1
    # (no es ambiguo: `tiene_suscripcion_activa` distingue "sin plan" de
    # "vence hoy"; RandomForest no acepta NaN).
    df["dias_para_vencer_plan"] = (
        df["dias_para_vencer_plan"].fillna(-1).astype(int))
    df["tiene_suscripcion_activa"] = df["tiene_suscripcion_activa"].astype(int)

    n_aband = int(df["abandonado"].sum())
    X = df[features.FEATURE_COLS]
    y = df["abandonado"].astype(int)

    # Estratificar sólo si hay suficientes casos de cada clase.
    estratificar = y if (y.nunique() > 1 and y.value_counts().min() >= 2) else None
    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=test_size, random_state=random_state,
        stratify=estratificar)

    clf = RandomForestClassifier(
        n_estimators=n_estimators, random_state=random_state,
        class_weight="balanced", min_samples_leaf=2, n_jobs=-1,
    )
    clf.fit(X_tr, y_tr)
    pred = clf.predict(X_te)

    acc = float(accuracy_score(y_te, pred))
    prec = float(precision_score(y_te, pred, zero_division=0))
    rec = float(recall_score(y_te, pred, zero_division=0))
    cm = confusion_matrix(y_te, pred).tolist()
    importancias = sorted(zip(features.FEATURE_COLS, clf.feature_importances_),
                          key=lambda t: -t[1])

    # ── Cross-validation (StratifiedKFold) — SOLO para reportar métricas más
    #    estables: con 19 positivos, un único test set es muy ruidoso (1 caso
    #    cambia precision/recall ~0.1). Se evalúa sobre TODO el dataset con
    #    `clone(clf)`, así el modelo que se persiste no cambia.
    cv = StratifiedKFold(n_splits=CV_FOLDS, shuffle=True,
                         random_state=random_state)
    cv_res = cross_validate(
        clone(clf), X, y, cv=cv, n_jobs=1, error_score="raise",
        scoring={"accuracy": "accuracy",
                 "precision": "precision",
                 "recall": "recall"})

    def _resumen_cv(metrica):
        valores = [float(v) for v in cv_res[f"test_{metrica}"]]
        return {
            "media": round(float(np.mean(valores)), 4),
            "std": round(float(np.std(valores)), 4),
            "por_fold": [round(v, 4) for v in valores],
        }

    cv_metricas = {m: _resumen_cv(m) for m in ("accuracy", "precision", "recall")}

    metadata = {
        "modelo": "RandomForestClassifier",
        "objetivo": "churn / abandono de alumnos",
        "fecha_entrenamiento": datetime.now(timezone.utc).isoformat(),
        "fecha_referencia_features": str(fecha_corte),
        "fecha_referencia_label": str(fecha_ref),
        "horizonte_prediccion_dias": dias_horizonte,
        "definicion_label": (
            f"abandonado = SIN asistencias en la ventana ({fecha_corte}, "
            f"{fecha_ref}] AND SIN suscripcion activa a {fecha_ref} "
            f"(estado='activo' AND fecha_expiracion >= {fecha_ref})"),
        "nota_label": (
            "Label de EVENTO FUTURO, distinto de la regla historica de '>45 "
            f"dias sin asistir': el positivo exige silencio total en la ventana "
            f"de {dias_horizonte} dias POSTERIOR al corte, por lo que las "
            "features no pueden verlo y el modelo no puede memorizar la "
            "formula."),
        "metodologia": (
            f"Prediccion HACIA ADELANTE: X se calcula AS-OF con la informacion "
            f"disponible hasta {fecha_corte} (hace {dias_horizonte} dias) y el "
            f"label es un EVENTO FUTURO: ausencia total de actividad en la "
            f"ventana ({fecha_corte}, {fecha_ref}]. Responde: '¿el alumno va a "
            f"abandonar en los proximos {dias_horizonte} dias?'."),
        "tenant_id": tenant_id,
        "n_alumnos": len(df),
        "n_abandonados": n_aband,
        "n_train": len(y_tr),
        "n_test": len(y_te),
        "feature_cols": features.FEATURE_COLS,
        "label_col": "abandonado",
        "hiperparametros": clf.get_params(),
        "metricas_test": {            # split único (se mantiene de referencia)
            "accuracy": round(acc, 4),
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "confusion_matrix": cm,
        },
        "cross_validation": {         # métricas estables: media ± std de 5 folds
            "estrategia": (f"StratifiedKFold(n_splits={CV_FOLDS}, shuffle=True, "
                           f"random_state={random_state})"),
            "n_splits": CV_FOLDS,
            "n_muestras": len(df),
            "n_positivos": n_aband,
            "accuracy": cv_metricas["accuracy"],
            "precision": cv_metricas["precision"],
            "recall": cv_metricas["recall"],
        },
        "importancias": {n: round(float(i), 6) for n, i in importancias},
        "version_sklearn": sklearn.__version__,
        "semilla": random_state,
    }
    return clf, metadata


# ══════════════════════════════════════════════════════════════════════════
#  FORECAST de ingresos (tendencia lineal + estacionalidad anual)
# ══════════════════════════════════════════════════════════════════════════
FEATURE_COLS_FORECAST = ["t", "sin_mes", "cos_mes"]


def _sum_tipo(db, tenant_id, tipo, desde, hasta) -> float:
    """SUM de montos por tipo ('ingreso'/'egreso') en [desde, hasta]."""
    return float(db.query(
        func.coalesce(func.sum(TransaccionFinanciera.monto), 0)
    ).filter(
        TransaccionFinanciera.tenant_id == tenant_id,
        TransaccionFinanciera.tipo == tipo,
        TransaccionFinanciera.fecha >= desde,
        TransaccionFinanciera.fecha <= hasta,
    ).scalar() or 0)


def serie_mensual(db, tenant_id) -> list:
    """[(year, month, ingreso_neto)] del 1er al último mes con transacciones.

    Los meses sin movimientos se incluyen con neto 0 (son meses reales).
    Mismo criterio que `populate_predictions._sum_ingresos/_sum_egresos`.
    """
    rango = db.query(
        func.min(TransaccionFinanciera.fecha),
        func.max(TransaccionFinanciera.fecha),
    ).filter(TransaccionFinanciera.tenant_id == tenant_id).first()
    if not rango or not rango[0] or not rango[1]:
        return []

    serie = []
    y, m = rango[0].year, rango[0].month
    while (y, m) <= (rango[1].year, rango[1].month):
        ini = date(y, m, 1)
        fin = date(y, m, calendar.monthrange(y, m)[1])
        neto = (_sum_tipo(db, tenant_id, "ingreso", ini, fin)
                - _sum_tipo(db, tenant_id, "egreso", ini, fin))
        serie.append((y, m, neto))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return serie


def _fila(t, anio, mes, neto=None) -> dict:
    """Fila de la matriz de diseño: tendencia + codificación cíclica del mes."""
    ang = 2.0 * math.pi * (mes - 1) / 12.0
    fila = {"t": t, "anio": anio, "mes": mes,
            "sin_mes": math.sin(ang), "cos_mes": math.cos(ang)}
    if neto is not None:
        fila["ingreso_neto"] = neto
    return fila


def construir_matriz(serie) -> pd.DataFrame:
    """DataFrame con t, sin_mes, cos_mes, anio, mes e ingreso_neto."""
    return pd.DataFrame(
        [_fila(t, y, m, neto) for t, (y, m, neto) in enumerate(serie)])


def proyectar(modelo, serie, meses) -> list:
    """Proyecta los próximos `meses` con un modelo ya entrenado."""
    filas, y, m = [], serie[-1][0], serie[-1][1]
    t0 = len(serie)
    for k in range(1, meses + 1):
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        filas.append(_fila(t0 + k - 1, y, m))
    df = pd.DataFrame(filas)
    df["ingreso_predicho"] = modelo.predict(df[FEATURE_COLS_FORECAST])
    return df.to_dict(orient="records")


def entrenar_forecast(db, tenant_id, meses_proyeccion=MESES_PROYECCION,
                      min_meses=6):
    """Entrena la Regresión Lineal de ingresos. Devuelve `(modelo, metadata)`."""
    try:
        import sklearn
        from sklearn.linear_model import LinearRegression
        from sklearn.metrics import mean_absolute_error, r2_score
    except ImportError as e:
        raise RuntimeError(
            f"falta scikit-learn ({e}); instalá con: "
            f"pip install -r requirements.txt") from e

    serie = serie_mensual(db, tenant_id)
    if len(serie) < min_meses:
        raise ValueError(
            f"sólo hay {len(serie)} meses con transacciones; se necesitan "
            f">= {min_meses} para entrenar (sugerencia: scripts/seed_ml_data.py)")

    df = construir_matriz(serie)
    X = df[FEATURE_COLS_FORECAST]
    y = df["ingreso_neto"]

    modelo = LinearRegression().fit(X, y)
    pred = modelo.predict(X)
    r2 = float(r2_score(y, pred))
    mae = float(mean_absolute_error(y, pred))
    proyeccion = proyectar(modelo, serie, meses_proyeccion)

    metadata = {
        "modelo": "LinearRegression",
        "objetivo": ("forecast de ingresos netos mensuales "
                     "(tendencia + estacionalidad anual)"),
        "fecha_entrenamiento": datetime.now(timezone.utc).isoformat(),
        "tenant_id": tenant_id,
        "n_meses": len(df),
        "rango": {
            "desde": f"{int(df.iloc[0]['anio'])}-{int(df.iloc[0]['mes']):02d}",
            "hasta": f"{int(df.iloc[-1]['anio'])}-{int(df.iloc[-1]['mes']):02d}",
        },
        "feature_cols": FEATURE_COLS_FORECAST,
        "features_desc": {
            "t": "indice temporal (tendencia)",
            "sin_mes": "sin(2*pi*(mes-1)/12) -> estacionalidad",
            "cos_mes": "cos(2*pi*(mes-1)/12) -> estacionalidad",
        },
        "coeficientes": {
            "intercepto": float(modelo.intercept_),
            **{n: float(c) for n, c in zip(FEATURE_COLS_FORECAST, modelo.coef_)},
        },
        "metricas_train": {"r2": round(r2, 4), "mae": round(mae, 2)},
        "proyeccion": [
            {"anio": int(p["anio"]), "mes": int(p["mes"]),
             "ingreso_predicho": round(float(p["ingreso_predicho"]), 2)}
            for p in proyeccion
        ],
        "serie_mensual": [
            {"anio": y, "mes": m, "ingreso_neto": round(neto, 2)}
            for y, m, neto in serie
        ],
        "version_sklearn": sklearn.__version__,
    }
    return modelo, metadata
