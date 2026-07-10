-- ============================================
-- ESQUEMA RELACIONAL - PLATAFORMA MULTI-TENANT GESTIÓN BOX CROSSFIT
-- PostgreSQL 15+
-- ============================================

-- 1. TENANTS (Boxes / Gimnasios)
-- Cada fila es un cliente (box) de la plataforma SaaS.
-- El subdominio es la pieza clave que permite resolver el tenant
-- desde la URL (ej: boxdetuamigo.tuapp.com -> subdomain = 'boxdetuamigo')
CREATE TABLE IF NOT EXISTS tenants (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(150) NOT NULL,
    subdomain       VARCHAR(63) NOT NULL UNIQUE,
    activo          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. USUARIOS
-- RUT único POR TENANT, no global (un mismo RUT puede existir
-- en distintos boxes como cuentas independientes).
CREATE TYPE rol_usuario AS ENUM ('alumno', 'coach', 'administrador');

CREATE TABLE IF NOT EXISTS usuarios (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    rut             VARCHAR(12) NOT NULL,
    nombre          VARCHAR(150) NOT NULL,
    telefono        VARCHAR(20),
    correo          VARCHAR(150) NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    rol             rol_usuario NOT NULL DEFAULT 'alumno',
    activo          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_rut_por_tenant UNIQUE (tenant_id, rut),
    CONSTRAINT uq_correo_por_tenant UNIQUE (tenant_id, correo)
);

CREATE INDEX idx_usuarios_tenant ON usuarios(tenant_id);

-- 3. PLANES (catálogo de planes disponibles, definido por el admin)
CREATE TABLE IF NOT EXISTS planes (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    nombre          VARCHAR(100) NOT NULL,
    creditos        INTEGER,
    es_ilimitado    BOOLEAN NOT NULL DEFAULT FALSE,
    precio_clp      INTEGER NOT NULL,
    duracion_dias   INTEGER NOT NULL DEFAULT 30,
    activo          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_planes_tenant ON planes(tenant_id);

-- 4. SUSCRIPCIONES / PLANES ACTIVOS DEL ALUMNO
-- Cada vez que se aprueba un voucher, se crea una fila aquí con
-- su propia fecha de inicio/expiración (30 días desde activación).
CREATE TYPE estado_suscripcion AS ENUM ('pendiente', 'activo', 'vencido', 'rechazado');

CREATE TABLE IF NOT EXISTS suscripciones (
    id                  SERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    usuario_id          INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    plan_id             INTEGER NOT NULL REFERENCES planes(id),
    estado              estado_suscripcion NOT NULL DEFAULT 'pendiente',
    creditos_totales    INTEGER,
    creditos_disponibles INTEGER,
    fecha_inicio        TIMESTAMPTZ,
    fecha_expiracion    TIMESTAMPTZ,
    voucher_url         VARCHAR(500) NOT NULL,
    aprobado_por        INTEGER REFERENCES usuarios(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_suscripciones_tenant ON suscripciones(tenant_id);
CREATE INDEX idx_suscripciones_usuario ON suscripciones(usuario_id);
CREATE INDEX idx_suscripciones_estado ON suscripciones(tenant_id, estado);

-- 5. DISCIPLINAS
-- es_open_box es SOLO una etiqueta para el dashboard (comparar
-- asistencia entre disciplinas). NO afecta el descuento de
-- créditos: todas las disciplinas, sin excepción, descuentan
-- 1 token del plan del alumno (confirmado).
CREATE TABLE IF NOT EXISTS disciplinas (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    nombre          VARCHAR(100) NOT NULL,
    es_open_box     BOOLEAN NOT NULL DEFAULT FALSE,
    activo          BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX idx_disciplinas_tenant ON disciplinas(tenant_id);

-- 6. HORARIOS_BASE (plantillas recurrentes)
-- Define el patrón semanal (ej: "CrossFit, Lunes, 18:00").
-- Un job periódico lee esta tabla y genera filas concretas en
-- `clases` para las próximas semanas.
-- dia_semana: 0=Domingo, 1=Lunes, ..., 6=Sábado (convención ISO/Postgres EXTRACT(DOW))
CREATE TABLE IF NOT EXISTS horarios_base (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    disciplina_id   INTEGER NOT NULL REFERENCES disciplinas(id),
    coach_id        INTEGER REFERENCES usuarios(id),
    dia_semana      SMALLINT NOT NULL CHECK (dia_semana BETWEEN 0 AND 6),
    hora            TIME NOT NULL,
    cupo_maximo     INTEGER NOT NULL DEFAULT 16,
    activo          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_horarios_base_tenant ON horarios_base(tenant_id);

-- 7. CLASES (instancias agendadas, no horarios "plantilla")
-- Diseño: cada clase es una fila concreta en el calendario
-- (ej: "CrossFit, 23-jun-2026, 18:00"), no una plantilla recurrente
-- abstracta. Esto simplifica enormemente el manejo de cupos y
-- cancelaciones, al costo de tener que generar filas con
-- antelación (vía un job/script).
CREATE TABLE IF NOT EXISTS clases (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    disciplina_id   INTEGER NOT NULL REFERENCES disciplinas(id),
    coach_id        INTEGER REFERENCES usuarios(id),
    horario_base_id INTEGER REFERENCES horarios_base(id),
    fecha_hora      TIMESTAMPTZ NOT NULL,
    cupo_maximo     INTEGER NOT NULL DEFAULT 16,
    estado          VARCHAR(20) NOT NULL DEFAULT 'programada',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_clase_horario UNIQUE (tenant_id, disciplina_id, fecha_hora)
);

CREATE INDEX idx_clases_tenant_fecha ON clases(tenant_id, fecha_hora);
CREATE INDEX idx_clases_coach ON clases(coach_id);

-- 8. RESERVAS
-- IMPORTANTE: el token se descuenta AL RESERVAR (no al asistir).
-- Solo se devuelve si se cancela con 2+ horas de anticipación.
CREATE TYPE estado_reserva AS ENUM ('confirmada', 'cancelada');

CREATE TABLE IF NOT EXISTS reservas (
    id                  SERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    clase_id            INTEGER NOT NULL REFERENCES clases(id) ON DELETE CASCADE,
    usuario_id          INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    suscripcion_id      INTEGER NOT NULL REFERENCES suscripciones(id),
    estado              estado_reserva NOT NULL DEFAULT 'confirmada',
    token_devuelto      BOOLEAN NOT NULL DEFAULT FALSE,
    asistio             BOOLEAN,
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now(),
    cancelado_en        TIMESTAMPTZ,
    CONSTRAINT uq_reserva_unica UNIQUE (clase_id, usuario_id)
);

CREATE INDEX idx_reservas_tenant ON reservas(tenant_id);
CREATE INDEX idx_reservas_clase ON reservas(clase_id);
CREATE INDEX idx_reservas_usuario ON reservas(usuario_id, estado);
