"""
Script para RECREAR la tabla 'clases' con el esquema correcto.
"""
import psycopg2
from app.core.config import settings


def recrear_tabla_clases():
    print("=" * 70)
    print("RECREANDO TABLA 'clases' CON ESQUEMA CORRECTO")
    print("=" * 70)

    try:
        conn = psycopg2.connect(settings.DATABASE_URL)
        conn.autocommit = True
        cursor = conn.cursor()
        print("\n✓ Conexión a Neon establecida\n")
    except Exception as e:
        print(f"\n✗ Error al conectar a Neon: {str(e)}")
        return False

    try:
        cursor.execute("SELECT COUNT(*) FROM clases")
        count = cursor.fetchone()[0]
        print(f"Registros actuales en 'clases': {count}")

        if count > 0:
            print(f"\n⚠ ADVERTENCIA: La tabla tiene {count} registro(s).")
            respuesta = input(
                "¿Confirmas que quieres borrarlos? (escribe 'si' para continuar): ")
            if respuesta.strip().lower() != "si":
                print("Operación cancelada.")
                return False

        print("\n🔨 Eliminando tabla 'clases' vieja...")
        cursor.execute("DROP TABLE IF EXISTS clases CASCADE;")
        print("✓ Tabla vieja eliminada")

        print("\n🔨 Creando tabla 'clases' con esquema correcto...")
        cursor.execute("""
            CREATE TABLE clases (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                horario_base_id INTEGER NOT NULL REFERENCES horarios_base(id) ON DELETE CASCADE,
                coach_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
                disciplina_id INTEGER NOT NULL REFERENCES disciplinas(id) ON DELETE CASCADE,
                fecha DATE NOT NULL,
                hora_inicio TIME NOT NULL,
                hora_fin TIME NOT NULL,
                cupo_maximo INTEGER NOT NULL DEFAULT 20,
                asistentes_confirmados INTEGER NOT NULL DEFAULT 0,
                cancelada BOOLEAN NOT NULL DEFAULT false,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
            );
        """)
        print("✓ Tabla 'clases' creada")

        print("\n🔨 Creando índices...")
        cursor.execute(
            "CREATE INDEX ix_clases_tenant_id ON clases(tenant_id);")
        cursor.execute("CREATE INDEX ix_clases_fecha ON clases(fecha);")
        cursor.execute("CREATE INDEX ix_clases_coach_id ON clases(coach_id);")
        print("✓ Índices creados")

        cursor.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'clases'
            ORDER BY ordinal_position
        """)
        cols = cursor.fetchall()
        print(f"\n📋 Columnas finales en 'clases' ({len(cols)}):")
        for c in cols:
            print(f"   - {c[0]} -> {c[1]}")

        cursor.close()
        conn.close()

        print("\n" + "=" * 70)
        print("✨ TABLA 'clases' RECREADA EXITOSAMENTE")
        print("=" * 70)
        return True

    except Exception as e:
        print(f"\n✗ Error: {str(e)}")
        conn.rollback()
        cursor.close()
        conn.close()
        return False


if __name__ == "__main__":
    recrear_tabla_clases()
