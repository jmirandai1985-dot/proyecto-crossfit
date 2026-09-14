"""
CLI de DEBUG local: entrena el modelo de FORECAST y lo guarda en la BD.

La lógica de entrenamiento vive en `ml/entrenar.py` (reusable) y la persistencia
en `ml/persistencia.py` — las mismas que usa el endpoint
`POST /api/v1/ml/reentrenar` (que llama n8n automáticamente).

⚠️ Ya NO escribe en `ml/artifacts/`: el modelo se persiste como pickle en la
   tabla `ml_modelos` (BD) para sobrevivir a los reinicios/redeploys de Render.

- Guard de seguridad: ENVIRONMENT=test + DATABASE_URL con 'billowing-violet-acdqud44'.

Uso (PowerShell, desde backend/):
    $env:ENVIRONMENT="test"; python3.12 ml\\train_forecast.py
"""
import os
import sys
import importlib

TENANT_ID = 1
MESES_PROYECCION = 6

# ── GUARD 1: ENVIRONMENT (debe correr ANTES de importar app.core.config) ──
if os.environ.get("ENVIRONMENT", "") != "test":
    print("ERROR: solo con ENVIRONMENT=test")
    sys.exit(1)
os.environ["ENVIRONMENT"] = "test"

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)

# ── GUARD 2: la URL debe ser la de TEST (billowing-violet-acdqud44) ──
settings = importlib.import_module("app.core.config").settings
if "billowing-violet-acdqud44" not in settings.DATABASE_URL:
    print("ERROR: URL no es billowing-violet-acdqud44")
    sys.exit(1)

import ml.entrenar as entrenar  # noqa: E402
import ml.persistencia as persistencia  # noqa: E402


def main():
    print("=" * 72)
    print("  [CLI] Entrenar FORECAST -> tabla ml_modelos")
    print("=" * 72)

    SessionLocal = importlib.import_module("app.db.database").SessionLocal
    db = SessionLocal()
    try:
        modelo, meta = entrenar.entrenar_forecast(
            db, TENANT_ID, meses_proyeccion=MESES_PROYECCION)
        resumen = persistencia.guardar_modelo(db, TENANT_ID, "forecast",
                                              modelo, meta)
        db.commit()

        print(f"\nmeses     : {meta['n_meses']} "
              f"({meta['rango']['desde']} .. {meta['rango']['hasta']})")
        print(f"R2        : {meta['metricas_train']['r2']}")
        print(f"MAE       : {meta['metricas_train']['mae']} CLP")
        print("\ncoeficientes:")
        for nombre, coef in meta["coeficientes"].items():
            print(f"  {nombre:<10} {coef:>18,.2f}".replace(",", "."))

        print(f"\nserie mensual ({len(meta['serie_mensual'])} meses):")
        for fila in meta["serie_mensual"]:
            print(f"  {fila['anio']}-{fila['mes']:02d}  "
                  f"{int(fila['ingreso_neto']):>12,}".replace(",", "."))

        print(f"\nproyeccion ({len(meta['proyeccion'])} meses):")
        for p in meta["proyeccion"]:
            print(f"  {p['anio']}-{p['mes']:02d}  "
                  f"{int(p['ingreso_predicho']):>12,} CLP".replace(",", "."))

        print(f"\n[persistido] tipo={resumen['tipo_modelo']} "
              f"bytes={resumen['bytes']} "
              f"fecha={resumen['fecha_entrenamiento']}")

        # ── Read-back: el modelo quedó guardado y se puede volver a leer ──
        cargado, meta_cargada = persistencia.cargar_modelo(
            db, TENANT_ID, "forecast")
        print(f"[read-back] modelo recargado : {type(cargado).__name__}")
        print(f"            R2 recargado      : "
              f"{meta_cargada.get('metricas_train', {}).get('r2')}")
        print(f"            coincide con la recién entrenada: "
              f"{meta_cargada.get('metricas_train') == meta['metricas_train']}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
