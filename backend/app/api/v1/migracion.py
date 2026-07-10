"""
Endpoint temporal para ejecutar migraciones via HTTP
"""
from fastapi import APIRouter
from sqlalchemy import text
from app.db.database import engine

router = APIRouter()


@router.post("/run")
def ejecutar_migracion():
    """Ejecuta migraciones pendientes"""
    resultados = []
    with engine.connect() as conn:
        # Columna es_compra_emergencia
        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'suscripciones' AND column_name = 'es_compra_emergencia'
        """))
        if not result.fetchone():
            conn.execute(text(
                "ALTER TABLE suscripciones ADD COLUMN es_compra_emergencia BOOLEAN NOT NULL DEFAULT FALSE"))
            resultados.append("✅ es_compra_emergencia agregada")
        else:
            resultados.append("⚠️ es_compra_emergencia ya existe")

        # Columna puede_comprar_emergencia
        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'suscripciones' AND column_name = 'puede_comprar_emergencia'
        """))
        if not result.fetchone():
            conn.execute(text(
                "ALTER TABLE suscripciones ADD COLUMN puede_comprar_emergencia BOOLEAN NOT NULL DEFAULT TRUE"))
            resultados.append("✅ puede_comprar_emergencia agregada")
        else:
            resultados.append("⚠️ puede_comprar_emergencia ya existe")

        # Columna fecha_compra_emergencia
        result = conn.execute(text("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'suscripciones' AND column_name = 'fecha_compra_emergencia'
        """))
        if not result.fetchone():
            conn.execute(text(
                "ALTER TABLE suscripciones ADD COLUMN fecha_compra_emergencia TIMESTAMP WITH TIME ZONE"))
            resultados.append("✅ fecha_compra_emergencia agregada")
        else:
            resultados.append("⚠️ fecha_compra_emergencia ya existe")

        conn.commit()

    return {"migracion": "completada", "detalles": resultados}
