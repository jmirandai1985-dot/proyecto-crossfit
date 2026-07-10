"""
Script para corregir la FK de clases.horario_base_id
para que apunte a 'horarios' en vez de 'horarios_base'
"""
import psycopg2
from app.core.config import settings


def corregir_fk_clases():
    print("=" * 70)
    print("CORRIGIENDO FK clases.horario_base_id -> horarios")
    print("=" * 70)

    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = True
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT COUNT(*) FROM clases")
        count = cursor.fetchone()[0]
        print(f"\nRegistros actuales en 'clases': {count}")
        if count > 0:
            print("⚠ La tabla tiene datos, esta operación los preservará.")

        print("\n🔨 Buscando nombre de la constraint FK actual...")
        cursor.execute("""
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'clases'::regclass
              AND confrelid = 'horarios_base'::regclass
        """)
        constraint = cursor.fetchone()

        if constraint:
            constraint_name = constraint[0]
            print(f"✓ Constraint encontrada: {constraint_name}")

            print("\n🔨 Eliminando constraint vieja...")
            cursor.execute(
                f"ALTER TABLE clases DROP CONSTRAINT {constraint_name};")
            print("✓ Constraint vieja eliminada")
        else:
            print(
                "⚠ No se encontró constraint hacia horarios_base, puede que ya esté corregida.")

        print("\n🔨 Agregando nueva constraint hacia 'horarios'...")
        cursor.execute("""
            ALTER TABLE clases
            ADD CONSTRAINT clases_horario_base_id_fkey
            FOREIGN KEY (horario_base_id) REFERENCES horarios(id) ON DELETE CASCADE;
        """)
        print("✓ Nueva constraint creada: clases.horario_base_id -> horarios.id")

        cursor.close()
        conn.close()

        print("\n" + "=" * 70)
        print("✨ FK CORREGIDA EXITOSAMENTE")
        print("=" * 70)
        return True

    except Exception as e:
        print(f"\n✗ Error: {str(e)}")
        cursor.close()
        conn.close()
        return False


if __name__ == "__main__":
    corregir_fk_clases()
