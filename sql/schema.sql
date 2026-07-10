-- 
===========================================
=================
-- ESQUEMA RELACIONAL - PLATAFORMA MULTI-
TENANT GESTIÓN BOX CROSSFIT
-- PostgreSQL 15+
-- 
===========================================
=================
-- ----------------------------------------
--------------------
-- 1. TENANTS (Boxes / Gimnasios)
-- ----------------------------------------
--------------------
-- Cada fila es un cliente (box) de la 
plataforma SaaS.
-- El subdominio es la pieza clave que 
permite resolver el tenant
-- desde la URL (ej: boxdetuamigo.tuapp.com 
-> subdomain = 'boxdetuamigo')
CREATE TABLE tenants (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(150) NOT NULL,
    subdomain       VARCHAR(63) NOT NULL 
UNIQUE,  -- max length de un label DNS
    activo          BOOLEAN NOT NULL 
DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL 
DEFAULT now()

);
-- ----------------------------------------
--------------------
-- 2. USUARIOS
-- ----------------------------------------
--------------------
-- RUT único POR TENANT, no global (un 
mismo RUT puede existir
-- en distintos boxes como cuentas 
independientes).
CREATE TYPE rol_usuario AS ENUM ('alumno', 
'coach', 'administrador');
CREATE TABLE usuarios (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL 
REFERENCES tenants(id) ON DELETE CASCADE,
    rut             VARCHAR(12) NOT 
NULL,          -- formato sin puntos, con 
guión: 12345678-9
    nombre          VARCHAR(150) NOT NULL,
    telefono        VARCHAR(20),
    correo          VARCHAR(150) NOT NULL,
    password_hash   VARCHAR(255) NOT 
NULL,         -- argon2/bcrypt hash, nunca 
texto plano
    rol             rol_usuario NOT NULL 
DEFAULT 'alumno',
    activo          BOOLEAN NOT NULL 
DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL 
DEFAULT now(),

    CONSTRAINT uq_rut_por_tenant UNIQUE 
(tenant_id, rut),
    CONSTRAINT uq_correo_por_tenant UNIQUE 
(tenant_id, correo)
);
CREATE INDEX idx_usuarios_tenant ON 
usuarios(tenant_id);
-- ----------------------------------------
--------------------
-- 3. PLANES (catálogo de planes 
disponibles, definido por el admin)
-- ----------------------------------------
--------------------
CREATE TABLE planes (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL 
REFERENCES tenants(id) ON DELETE CASCADE,
    nombre          VARCHAR(100) NOT 
NULL,         -- ej: "Plan 8 clases", 
"Ilimitado"
    creditos        
INTEGER,                       -- NULL = 
ilimitado
    es_ilimitado    BOOLEAN NOT NULL 
DEFAULT FALSE,
    precio_clp      INTEGER NOT NULL,
    duracion_dias   INTEGER NOT NULL 
DEFAULT 30,   -- confirmado: 30 días desde 
activación
    activo          BOOLEAN NOT NULL 
DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL 

DEFAULT now()
);
CREATE INDEX idx_planes_tenant ON 
planes(tenant_id);
-- ----------------------------------------
--------------------
-- 4. SUSCRIPCIONES / PLANES ACTIVOS DEL 
ALUMNO
-- ----------------------------------------
--------------------
-- Cada vez que se aprueba un voucher, se 
crea una fila aquí con
-- su propia fecha de inicio/expiración (30 
días desde activación).
CREATE TYPE estado_suscripcion AS ENUM 
('pendiente', 'activo', 'vencido', 
'rechazado');
CREATE TABLE suscripciones (
    id                  SERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL 
REFERENCES tenants(id) ON DELETE CASCADE,
    usuario_id          INTEGER NOT NULL 
REFERENCES usuarios(id) ON DELETE CASCADE,
    plan_id             INTEGER NOT NULL 
REFERENCES planes(id),
    estado              estado_suscripcion 
NOT NULL DEFAULT 'pendiente',
    creditos_totales    
INTEGER,                   -- copia del 
plan al momento de activar (histórico)
    creditos_disponibles 

INTEGER,                  -- se va 
descontando con cada reserva
    fecha_inicio        
TIMESTAMPTZ,                -- se setea al 
APROBAR, no al crear
    fecha_expiracion    
TIMESTAMPTZ,                -- fecha_inicio 
+ duracion_dias
    voucher_url         VARCHAR(500) NOT 
NULL,      -- key del archivo en S3
    aprobado_por        INTEGER REFERENCES 
usuarios(id),  -- qué admin lo aprobó
    created_at          TIMESTAMPTZ NOT 
NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT 
NULL DEFAULT now()
);
CREATE INDEX idx_suscripciones_tenant ON 
suscripciones(tenant_id);
CREATE INDEX idx_suscripciones_usuario ON 
suscripciones(usuario_id);
CREATE INDEX idx_suscripciones_estado ON 
suscripciones(tenant_id, estado);
-- ----------------------------------------
--------------------
-- 5. DISCIPLINAS
-- ----------------------------------------
--------------------
-- es_open_box es SOLO una etiqueta para el 
dashboard (comparar
-- asistencia entre disciplinas). NO afecta 
el descuento de

-- créditos: todas las disciplinas, sin 
excepción, descuentan
-- 1 token del plan del alumno 
(confirmado).
CREATE TABLE disciplinas (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL 
REFERENCES tenants(id) ON DELETE CASCADE,
    nombre          VARCHAR(100) NOT 
NULL,         -- CrossFit, GAP, 
Musculación, Open Box
    es_open_box     BOOLEAN NOT NULL 
DEFAULT FALSE, -- solo etiqueta informativa 
para reportes
    activo          BOOLEAN NOT NULL 
DEFAULT TRUE
);
CREATE INDEX idx_disciplinas_tenant ON 
disciplinas(tenant_id);
-- ----------------------------------------
--------------------
-- 6. HORARIOS_BASE (plantillas 
recurrentes)
-- ----------------------------------------
--------------------
-- Define el patrón semanal (ej: "CrossFit, 
Lunes, 18:00").
-- Un job periódico lee esta tabla y genera 
filas concretas en
-- `clases` para las próximas semanas (ver 
nota 'd' al final).
-- dia_semana: 0=Domingo, 1=Lunes, ..., 

6=Sábado (convención ISO/Postgres 
EXTRACT(DOW))
CREATE TABLE horarios_base (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL 
REFERENCES tenants(id) ON DELETE CASCADE,
    disciplina_id   INTEGER NOT NULL 
REFERENCES disciplinas(id),
    coach_id        INTEGER REFERENCES 
usuarios(id),
    dia_semana      SMALLINT NOT NULL CHECK 
(dia_semana BETWEEN 0 AND 6),
    hora            TIME NOT 
NULL,                 -- ej: 18:00:00
    cupo_maximo     INTEGER NOT NULL 
DEFAULT 16,
    activo          BOOLEAN NOT NULL 
DEFAULT TRUE,  -- desactivar sin borrar 
histórico
    created_at      TIMESTAMPTZ NOT NULL 
DEFAULT now()
);
CREATE INDEX idx_horarios_base_tenant ON 
horarios_base(tenant_id);
-- Vínculo opcional: permite saber si una 
clase concreta nació de
-- una plantilla o fue creada manualmente 
por el coach.
-- (se agrega como columna en `clases`, ver 
tabla siguiente)
-- ----------------------------------------

--------------------
-- 7. CLASES (instancias agendadas, no 
horarios "plantilla")
-- ----------------------------------------
--------------------
-- Diseño: cada clase es una fila concreta 
en el calendario
-- (ej: "CrossFit, 23-jun-2026, 18:00"), no 
una plantilla recurrente
-- abstracta. Esto simplifica enormemente 
el manejo de cupos y
-- cancelaciones, al costo de tener que 
generar filas con
-- antelación (vía un job/script, ver nota 
más abajo).
CREATE TABLE clases (
    id              SERIAL PRIMARY KEY,
    tenant_id       INTEGER NOT NULL 
REFERENCES tenants(id) ON DELETE CASCADE,
    disciplina_id   INTEGER NOT NULL 
REFERENCES disciplinas(id),
    coach_id        INTEGER REFERENCES 
usuarios(id),   -- usuario con rol 'coach'
    horario_base_id INTEGER REFERENCES 
horarios_base(id), -- NULL si fue creada 
manualmente
    fecha_hora      TIMESTAMPTZ NOT NULL,
    cupo_maximo     INTEGER NOT NULL 
DEFAULT 16,
    estado          VARCHAR(20) NOT NULL 
DEFAULT 'programada', -- 
programada/cancelada
    created_at      TIMESTAMPTZ NOT NULL 
DEFAULT now(),

    CONSTRAINT uq_clase_horario UNIQUE 
(tenant_id, disciplina_id, fecha_hora)
);
CREATE INDEX idx_clases_tenant_fecha ON 
clases(tenant_id, fecha_hora);
CREATE INDEX idx_clases_coach ON 
clases(coach_id);
-- ----------------------------------------
--------------------
-- 8. RESERVAS
-- ----------------------------------------
--------------------
-- IMPORTANTE: el token se descuenta AL 
RESERVAR (no al asistir).
-- Solo se devuelve si se cancela con 2+ 
horas de anticipación.
-- Si nunca se cancela (no-show) o se 
cancela tarde, el token
-- simplemente queda perdido — no se 
necesita ningún job/proceso
-- para "detectar" el no-show, es la 
ausencia de cancelación a
-- tiempo lo que decide el resultado, no un 
evento nuevo.
CREATE TYPE estado_reserva AS ENUM 
('confirmada', 'cancelada');
CREATE TABLE reservas (
    id                  SERIAL PRIMARY KEY,
    tenant_id           INTEGER NOT NULL 
REFERENCES tenants(id) ON DELETE CASCADE,

    clase_id            INTEGER NOT NULL 
REFERENCES clases(id) ON DELETE CASCADE,
    usuario_id          INTEGER NOT NULL 
REFERENCES usuarios(id) ON DELETE CASCADE,
    suscripcion_id      INTEGER NOT NULL 
REFERENCES suscripciones(id),  -- de qué 
plan se descontó el token
    estado              estado_reserva NOT 
NULL DEFAULT 'confirmada',
    token_devuelto      BOOLEAN NOT NULL 
DEFAULT FALSE,  -- TRUE solo si canceló con 
2+ horas de anticipación
    asistio             
BOOLEAN,                          -- 
NULL=sin marcar, TRUE/FALSE = marcado por 
el coach.
                                           
                 -- SOLO informativo 
(rankings/métricas), no afecta tokens.
    creado_en           TIMESTAMPTZ NOT 
NULL DEFAULT now(),
    cancelado_en        TIMESTAMPTZ,
    CONSTRAINT uq_reserva_unica UNIQUE 
(clase_id, usuario_id)  -- no reservar 2 
veces la misma clase
);
CREATE INDEX idx_reservas_tenant ON 
reservas(tenant_id);
CREATE INDEX idx_reservas_clase ON 
reservas(clase_id);
CREATE INDEX idx_reservas_usuario ON 
reservas(usuario_id, estado);

-- ----------------------------------------
--------------------
-- NOTAS DE DISEÑO IMPORTANTES
-- ----------------------------------------
--------------------
-- a) Aforo (16 cupos): se valida a nivel 
de APLICACIÓN antes de
--    insertar en `reservas`, contando 
reservas con estado='confirmada'
--    para esa clase. Para evitar 
condiciones de carrera (dos alumnos
--    reservando el último cupo al mismo 
tiempo), la transacción de
--    reserva debe hacerse con un SELECT 
... FOR UPDATE sobre la fila
--    de `clases`, o un COUNT(*) dentro de 
la misma transacción con
--    nivel de aislamiento SERIALIZABLE.
--
-- b) Política de cancelación (2 horas) — 
lógica de tokens:
--    Al RESERVAR: se descuenta 1 token de 
inmediato
--    (suscripciones.creditos_disponibles -
= 1).
--    Al CANCELAR: se compara 
`clases.fecha_hora` con NOW().
--      - Si faltan >= 2 horas: 
estado='cancelada', token_devuelto=TRUE,
--        se devuelve el token 
(creditos_disponibles += 1).
--      - Si faltan < 2 horas: 
estado='cancelada', token_devuelto=FALSE,

--        el token NO se devuelve (la 
cancelación sigue liberando el
--        cupo para otro alumno, pero no 
hay reembolso de token).
--    Si el alumno simplemente no asiste y 
nunca cancela: la reserva
--    queda en 'confirmada' para siempre y 
el token permanece perdido
--    desde el momento en que se reservó. 
No se requiere ningún job
--    para "detectar" no-show — la ausencia 
de cancelación a tiempo
--    ya determina el resultado.
--    El campo `asistio` es marcado 
manualmente por el coach desde su
--    lista de asistencia, y es puramente 
informativo para reportes
--    (ranking de asistencia, retención), 
sin ningún efecto sobre tokens.
--
-- c) Open Box: NO tiene lógica especial de 
créditos. Se trata como
--    cualquier otra disciplina — descuenta 
1 token del mismo pool
--    de la suscripción activa del alumno. 
El flag `es_open_box` en
--    `disciplinas` es solo informativo, 
para separar reportes en
--    el dashboard (ej. "Rendimiento por 
Disciplina").
--
-- d) Generación de clases futuras: un job 
periódico (AWS Lambda +
--    EventBridge Scheduler, ej. corre 

todos los domingos a las 00:00)
--    lee `horarios_base` donde 
activo=TRUE, y por cada fila genera
--    las clases concretas en `clases` para 
la semana/mes siguiente,
--    seteando `horario_base_id` para dejar 
registro de su origen.
--    El coach/admin puede además crear 
clases sueltas manualmente
--    en `clases` sin pasar por una 
plantilla (horario_base_id = NULL),
--    por ejemplo para una clase especial 
un sábado.
