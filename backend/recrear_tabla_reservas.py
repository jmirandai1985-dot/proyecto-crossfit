import psycopg2
from app.core.config import settings


def recrear_tabla_reservas():
    print("=" * 70)
    print("RECREANDO TABLA 'reservas' CON ESQUEMA CORRECTO")
    print("=" * 70)

    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM reservas")
    count = cur.fetchone()[0]
    print(f"\nRegistros actuales en 'reservas': {count}")

    if count > 0:
        respuesta = input(
            f"¿Confirmas borrar {count} registro(s)? (escribe 'si'): ")
        if respuesta.strip().lower() != "si":
            print("Cancelado.")
            return False

    print("\nEliminando tabla reservas vieja...")
    cur.execute("DROP TABLE IF EXISTS reservas CASCADE;")
    print("Tabla vieja eliminada")

    print("\nCreando tabla reservas con esquema correcto...")
    cur.execute("""
        CREATE TABLE reservas (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            clase_id INTEGER NOT NULL REFERENCES clases(id) ON DELETE CASCADE,
            alumno_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
            fecha_reserva TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            asistio BOOLEAN NOT NULL DEFAULT false,
            tokens_gastados INTEGER NOT NULL DEFAULT 0,
            estado VARCHAR(20) NOT NULL DEFAULT 'reserved',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        );
    """)
    print("Tabla reservas creada")

    cur.execute("CREATE INDEX ix_reservas_tenant_id ON reservas(tenant_id);")
    cur.execute("CREATE INDEX ix_reservas_clase_id ON reservas(clase_id);")
    cur.execute("CREATE INDEX ix_reservas_alumno_id ON reservas(alumno_id);")
    print("Indices creados")

    cur.execute("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'reservas'
        ORDER BY ordinal_position
    """)
    cols = cur.fetchall()
    print(f"\nColumnas finales ({len(cols)}):")
    for c in cols:
        print(f"   - {c[0]} -> {c[1]}")

    cur.close()
    conn.close()

    print("\n" + "=" * 70)
    print("TABLA reservas RECREADA EXITOSAMENTE")
    print("=" * 70)
    return True


if __name__ == "__main__":
    recrear_tabla_reservas()
