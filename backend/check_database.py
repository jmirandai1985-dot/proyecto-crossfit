"""
Script para verificar el contenido de la base de datos Neon
y eliminar datos de prueba si existen
"""
import psycopg2
from urllib.parse import urlparse
import os
import sys
from dotenv import load_dotenv

# Configurar encoding para Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Cargar variables de entorno
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


def check_and_clean_database():
    """Verifica y limpia la base de datos"""
    try:
        print("\n" + "="*60)
        print("🔍 VERIFICACIÓN DE BASE DE DATOS NEON")
        print("="*60)

        # Parsear URL para mostrar info
        parsed = urlparse(DATABASE_URL)
        print(f"\n📍 Host: {parsed.hostname}")
        print(f"📍 Base de datos: {parsed.path[1:]}")

        # Conectar
        print("\n⏳ Conectando a Neon...")
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        print("✅ Conexión exitosa\n")

        # ============================================
        # 1. VERIFICAR TABLA TENANTS
        # ============================================
        print("="*60)
        print("📊 TABLA: tenants")
        print("="*60)

        cursor.execute("""
            SELECT id, nombre, subdomain, activo, created_at 
            FROM tenants 
            ORDER BY id
        """)

        tenants = cursor.fetchall()

        if tenants:
            print(f"\n✅ Se encontraron {len(tenants)} registro(s):\n")
            for tenant in tenants:
                print(f"  ID: {tenant[0]}")
                print(f"  Nombre: {tenant[1]}")
                print(f"  Subdominio: {tenant[2]}")
                print(f"  Activo: {tenant[3]}")
                print(f"  Creado: {tenant[4]}")
                print("-" * 40)
        else:
            print("\n✅ La tabla está vacía (sin datos)")

        # ============================================
        # 2. VERIFICAR OTRAS TABLAS PRINCIPALES
        # ============================================
        tablas_a_verificar = [
            'usuarios',
            'planes',
            'disciplinas',
            'suscripciones',
            'pagos',
            'clases',
            'asistencias'
        ]

        print("\n" + "="*60)
        print("📊 VERIFICANDO OTRAS TABLAS")
        print("="*60 + "\n")

        for tabla in tablas_a_verificar:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {tabla}")
                count = cursor.fetchone()[0]
                print(f"  {tabla.upper()}: {count} registro(s)")
            except Exception as e:
                print(f"  {tabla.upper()}: ⚠️  Tabla no existe o error: {str(e)}")
                conn.rollback()  # Rollback para continuar después de un error

        # ============================================
        # 3. BUSCAR DATOS DE PRUEBA ESPECÍFICOS
        # ============================================
        print("\n" + "="*60)
        print("🔍 BUSCANDO DATOS DE PRUEBA ESPECÍFICOS")
        print("="*60 + "\n")

        datos_prueba_encontrados = []

        # Buscar en tenants
        cursor.execute("""
            SELECT id, nombre, subdomain 
            FROM tenants 
            WHERE nombre ILIKE '%formación urbana%' 
               OR nombre ILIKE '%gorila%'
               OR nombre ILIKE '%urban%'
               OR subdomain ILIKE '%demo%'
               OR subdomain ILIKE '%test%'
        """)
        tenants_prueba = cursor.fetchall()

        if tenants_prueba:
            print("⚠️  TENANTS DE PRUEBA ENCONTRADOS:")
            for t in tenants_prueba:
                print(f"  - ID {t[0]}: {t[1]} (subdominio: {t[2]})")
                datos_prueba_encontrados.append(('tenants', t[0]))

        # Buscar disciplinas de prueba
        try:
            cursor.execute("""
                SELECT id, nombre 
                FROM disciplinas 
                WHERE nombre ILIKE '%caja abierta%'
                   OR nombre ILIKE '%levantamiento de pesas%'
                   OR nombre ILIKE '%open box%'
            """)
            disciplinas_prueba = cursor.fetchall()

            if disciplinas_prueba:
                print("\n⚠️  DISCIPLINAS DE PRUEBA ENCONTRADAS:")
                for d in disciplinas_prueba:
                    print(f"  - ID {d[0]}: {d[1]}")
                    datos_prueba_encontrados.append(('disciplinas', d[0]))
        except Exception:
            pass

        # ============================================
        # 4. ELIMINAR DATOS DE PRUEBA
        # ============================================
        if datos_prueba_encontrados:
            print("\n" + "="*60)
            print("🗑️  ELIMINANDO DATOS DE PRUEBA")
            print("="*60 + "\n")

            # Eliminar en orden correcto (respetando foreign keys)
            tablas_orden = [
                'asistencias',
                'clases',
                'pagos',
                'suscripciones',
                'disciplinas',
                'planes',
                'usuarios',
                'tenants'
            ]

            for tabla in tablas_orden:
                try:
                    cursor.execute(f"DELETE FROM {tabla}")
                    deleted = cursor.rowcount
                    if deleted > 0:
                        print(
                            f"  ✅ {tabla}: {deleted} registro(s) eliminado(s)")
                except Exception as e:
                    print(f"  ⚠️  {tabla}: {str(e)}")

            conn.commit()
            print("\n✅ Datos de prueba eliminados exitosamente")

        else:
            print("\n✅ No se encontraron datos de prueba específicos")

        # ============================================
        # 5. VERIFICACIÓN FINAL
        # ============================================
        print("\n" + "="*60)
        print("📊 ESTADO FINAL DE LA BASE DE DATOS")
        print("="*60 + "\n")

        cursor.execute("SELECT COUNT(*) FROM tenants")
        count_tenants = cursor.fetchone()[0]
        print(f"  TENANTS: {count_tenants} registro(s)")

        for tabla in tablas_a_verificar:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {tabla}")
                count = cursor.fetchone()[0]
                print(f"  {tabla.upper()}: {count} registro(s)")
            except:
                pass

        print("\n" + "="*60)
        print("✅ VERIFICACIÓN COMPLETADA")
        print("="*60 + "\n")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    check_and_clean_database()
