"""
Script para crear las tablas nuevas en la base de datos Neon
Usa psycopg2 directamente con CREATE TABLE IF NOT EXISTS
"""
import sys
import psycopg2
from psycopg2 import sql

from app.core.config import settings


def crear_tablas_nuevas():
    """
    Crea las tablas nuevas en la base de datos usando SQL directo.
    Usa CREATE TABLE IF NOT EXISTS y CREATE INDEX IF NOT EXISTS.
    """
    print("=" * 70)
    print("CREANDO TABLAS NUEVAS EN NEON (psycopg2)")
    print("=" * 70)

    # Conectar a la BD
    try:
        conn = psycopg2.connect(settings.DATABASE_URL)
        cursor = conn.cursor()
        print("\n✓ Conexión a Neon establecida\n")
    except Exception as e:
        print(f"\n✗ Error al conectar a Neon: {str(e)}")
        return False

    # SQL para crear las tablas
    sql_statements = [
        # Tabla: movimientos
        """
        CREATE TABLE IF NOT EXISTS movimientos (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            nombre VARCHAR(100) NOT NULL,
            descripcion VARCHAR(500),
            activo BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        );
        """,
        "CREATE INDEX IF NOT EXISTS ix_movimientos_tenant_id ON movimientos(tenant_id);",
        "CREATE INDEX IF NOT EXISTS ix_movimientos_nombre ON movimientos(nombre);",

        # Tabla: historial_rm
        """
        CREATE TABLE IF NOT EXISTS historial_rm (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            alumno_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
            movimiento_id INTEGER NOT NULL REFERENCES movimientos(id) ON DELETE CASCADE,
            peso_kg FLOAT NOT NULL,
            fecha DATE NOT NULL,
            notas VARCHAR(500),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        );
        """,
        "CREATE INDEX IF NOT EXISTS ix_historial_rm_tenant_id ON historial_rm(tenant_id);",
        "CREATE INDEX IF NOT EXISTS ix_historial_rm_alumno_id ON historial_rm(alumno_id);",
        "CREATE INDEX IF NOT EXISTS ix_historial_rm_movimiento_id ON historial_rm(movimiento_id);",
        "CREATE INDEX IF NOT EXISTS ix_historial_rm_fecha ON historial_rm(fecha);",

        # Tabla: retencion_alumnos
        """
        CREATE TABLE IF NOT EXISTS retencion_alumnos (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            alumno_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
            coach_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
            proxima_renovacion DATE NOT NULL,
            estado_plan VARCHAR(20) NOT NULL DEFAULT 'activo',
            notas VARCHAR(500),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        );
        """,
        "CREATE INDEX IF NOT EXISTS ix_retencion_tenant_id ON retencion_alumnos(tenant_id);",
        "CREATE INDEX IF NOT EXISTS ix_retencion_alumno_id ON retencion_alumnos(alumno_id);",
        "CREATE INDEX IF NOT EXISTS ix_retencion_coach_id ON retencion_alumnos(coach_id);",
        "CREATE INDEX IF NOT EXISTS ix_retencion_proxima_renovacion ON retencion_alumnos(proxima_renovacion);",
        "CREATE INDEX IF NOT EXISTS ix_retencion_estado_plan ON retencion_alumnos(estado_plan);",

        # Tabla: productos
        """
        CREATE TABLE IF NOT EXISTS productos (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            nombre VARCHAR(150) NOT NULL,
            descripcion VARCHAR(500),
            precio FLOAT NOT NULL,
            stock INTEGER NOT NULL DEFAULT 0,
            activo BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        );
        """,
        "CREATE INDEX IF NOT EXISTS ix_productos_tenant_id ON productos(tenant_id);",
        "CREATE INDEX IF NOT EXISTS ix_productos_nombre ON productos(nombre);",
        "CREATE INDEX IF NOT EXISTS ix_productos_activo ON productos(activo);",

        # Tabla: pedidos
        """
        CREATE TABLE IF NOT EXISTS pedidos (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            alumno_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
            producto_id INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
            cantidad INTEGER NOT NULL,
            total FLOAT NOT NULL,
            estado VARCHAR(20) NOT NULL DEFAULT 'pendiente',
            fecha_pedido TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        );
        """,
        "CREATE INDEX IF NOT EXISTS ix_pedidos_tenant_id ON pedidos(tenant_id);",
        "CREATE INDEX IF NOT EXISTS ix_pedidos_alumno_id ON pedidos(alumno_id);",
        "CREATE INDEX IF NOT EXISTS ix_pedidos_producto_id ON pedidos(producto_id);",
        "CREATE INDEX IF NOT EXISTS ix_pedidos_estado ON pedidos(estado);",
        "CREATE INDEX IF NOT EXISTS ix_pedidos_fecha_pedido ON pedidos(fecha_pedido);",

        # Tabla: auditoria
        """
        CREATE TABLE IF NOT EXISTS auditoria (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            usuario_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
            accion VARCHAR(20) NOT NULL,
            entidad VARCHAR(50) NOT NULL,
            entidad_id INTEGER,
            detalle JSONB,
            fecha TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        );
        """,
        "CREATE INDEX IF NOT EXISTS ix_auditoria_tenant_id ON auditoria(tenant_id);",
        "CREATE INDEX IF NOT EXISTS ix_auditoria_usuario_id ON auditoria(usuario_id);",
        "CREATE INDEX IF NOT EXISTS ix_auditoria_accion ON auditoria(accion);",
        "CREATE INDEX IF NOT EXISTS ix_auditoria_entidad ON auditoria(entidad);",
        "CREATE INDEX IF NOT EXISTS ix_auditoria_fecha ON auditoria(fecha);",

        # Tabla: wods
        """
        CREATE TABLE IF NOT EXISTS wods (
            id SERIAL PRIMARY KEY,
            tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            fecha DATE NOT NULL,
            titulo VARCHAR(200),
            descripcion VARCHAR(500),
            coach_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
            estado VARCHAR(20) NOT NULL DEFAULT 'draft',
            activo BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE
        );
        """,
        "CREATE INDEX IF NOT EXISTS ix_wods_tenant_id ON wods(tenant_id);",
        "CREATE INDEX IF NOT EXISTS ix_wods_fecha ON wods(fecha);",

        # Tabla: wod_movimientos
        """
        CREATE TABLE IF NOT EXISTS wod_movimientos (
            id SERIAL PRIMARY KEY,
            wod_id INTEGER NOT NULL REFERENCES wods(id) ON DELETE CASCADE,
            movimiento_id INTEGER NOT NULL REFERENCES movimientos(id) ON DELETE CASCADE,
            orden INTEGER NOT NULL DEFAULT 1,
            series INTEGER,
            repeticiones VARCHAR(50),
            peso FLOAT,
            tiempo VARCHAR(20),
            notas VARCHAR(500)
        );
        """,
        "CREATE INDEX IF NOT EXISTS ix_wod_movimientos_wod_id ON wod_movimientos(wod_id);",
        "CREATE INDEX IF NOT EXISTS ix_wod_movimientos_movimiento_id ON wod_movimientos(movimiento_id);",
    ]

    # Ejecutar cada statement
    tablas_creadas = []
    errores = []

    for i, statement in enumerate(sql_statements, 1):
        try:
            cursor.execute(statement)
            conn.commit()

            # Detectar si es una tabla (contiene CREATE TABLE)
            if "CREATE TABLE" in statement:
                tabla_name = statement.split("CREATE TABLE IF NOT EXISTS")[
                    1].split("(")[0].strip()
                tablas_creadas.append(tabla_name)
                print(f"✓ Tabla '{tabla_name}' creada/verificada")
            elif "CREATE INDEX" in statement:
                index_name = statement.split("CREATE INDEX IF NOT EXISTS")[
                    1].split("ON")[0].strip()
                print(f"  ✓ Índice '{index_name}' creado/verificado")

        except Exception as e:
            error_msg = str(e)
            errores.append(error_msg)
            print(f"✗ Error en statement {i}: {error_msg}")

    # Cerrar conexión
    cursor.close()
    conn.close()

    print("\n" + "=" * 70)
    print("RESULTADO:")
    print("=" * 70)

    if tablas_creadas:
        print(f"\n✓ {len(tablas_creadas)} tablas creadas/verificadas:")
        for tabla in tablas_creadas:
            print(f"  - {tabla}")

    if errores:
        print(f"\n⚠ {len(errores)} errores encontrados:")
        for error in errores:
            print(f"  - {error}")

    print("\n" + "=" * 70)

    if len(tablas_creadas) == 6:
        print("✓ TODAS LAS TABLAS NUEVAS SE CREARON EXITOSAMENTE!")
        print("=" * 70)
        return True
    else:
        print(f"⚠ Se crearon {len(tablas_creadas)}/6 tablas esperadas")
        print("=" * 70)
        return len(tablas_creadas) > 0


if __name__ == "__main__":
    try:
        exito = crear_tablas_nuevas()
        sys.exit(0 if exito else 1)
    except Exception as e:
        print(f"\n✗ Error fatal: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
