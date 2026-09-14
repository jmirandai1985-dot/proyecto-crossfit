"""
CLI de DEBUG local: entrena el modelo de CHURN y lo guarda en la BD.

La lógica de entrenamiento vive en `ml/entrenar.py` (reusable) y la persistencia
en `ml/persistencia.py` — las mismas que usa el endpoint
`POST /api/v1/ml/reentrenar` (que llama n8n automáticamente).

⚠️ Ya NO escribe en `ml/artifacts/`: el modelo se persiste como pickle en la
   tabla `ml_modelos` (BD) para sobrevivir a los reinicios/redeploys de Render.

- Guard de seguridad: ENVIRONMENT=test + DATABASE_URL con 'billowing-violet-acdqud44'.

Uso (PowerShell, desde backend/):
    $env:ENVIRONMENT="test"; python3.12 ml\\train_churn.py
"""
import os
import sys
import importlib

TENANT_ID = 1

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
    print("  [CLI] Entrenar CHURN -> tabla ml_modelos")
    print("=" * 72)

    SessionLocal = importlib.import_module("app.db.database").SessionLocal
    db = SessionLocal()
    try:
        modelo, meta = entrenar.entrenar_churn(db, TENANT_ID)
        resumen = persistencia.guardar_modelo(db, TENANT_ID, "churn",
                                              modelo, meta)
        db.commit()

        m = meta["metricas_test"]
        print(f"\ndataset   : {meta['n_alumnos']} alumnos "
              f"({meta['n_abandonados']} abandonados)")
        print(f"train/test: {meta['n_train']}/{meta['n_test']}")
        print(f"accuracy  : {m['accuracy']}")
        print(f"precision : {m['precision']}")
        print(f"recall    : {m['recall']}")
        print(f"confusion : {m['confusion_matrix']}")
        print("\nimportancia de features:")
        for nombre, imp in meta["importancias"].items():
            print(f"  {nombre:<32} {imp:.4f}")

        print(f"\n[persistido] tipo={resumen['tipo_modelo']} "
              f"bytes={resumen['bytes']} "
              f"fecha={resumen['fecha_entrenamiento']}")

        # ── Read-back: el modelo quedó guardado y se puede volver a leer ──
        cargado, meta_cargada = persistencia.cargar_modelo(db, TENANT_ID, "churn")
        print(f"[read-back] modelo recargado : {type(cargado).__name__}")
        print(f"            accuracy recargada: "
              f"{meta_cargada.get('metricas_test', {}).get('accuracy')}")
        print(f"            coincide con la recién entrenada: "
              f"{meta_cargada.get('metricas_test') == m}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
