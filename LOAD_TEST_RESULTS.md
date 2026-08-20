# LOAD TEST RESULTS — Test de esfuerzo del panel (backend CrossFit)

> Fecha: 2026-08-19/20 · Metodología k6 + seeds Python aislados · Base: Neon (plan **Free**)
> Documento de cierre del test de esfuerzo, previo a la fase de Dockerización/despliegue.

---

## 1. Resumen ejecutivo

Se probó el sistema bajo carga real contra **tenants aislados `LOAD_TEST_BOX`**
(uno por escenario, con prefijos marcados y cleanup verificado en cada corrida:
`_cleanup_load_test.py` con doble pasada tolerante a FKs + verificación de 0
leftovers). Herramienta: **k6 v2.2.0** (instalada vía winget) con rampa
**10 → 50 → 150 → 500 VUs** por escenario, monitoreo en paralelo del backend
(`_monitor_backend.py`, psutil) y verificación de invariantes en BD post-corrida.

**Resultado global**: 6/6 escenarios ejecutados. **0 errores 5xx reales**
(1×500 transitorio documentado en Bazar, no reproducido), **integridad de datos
perfecta en todos** (cupos respetados, tokens 1:1, sin duplicados, stock nunca
negativo). Los cuellos reales del plan Free: **pooler ~100 transacciones
concurrentes**, **threadpool de uvicorn (40 hilos** para endpoints síncronos) y
**latencia Neon ~0.5-2s por query**. Ningún escenario perdió datos.

---

## 2. Metodología

- **Aislamiento**: tenant `LOAD_TEST_BOX` por escenario (subdomain
  `load-test-box-*`), creado por seed directo a BD (nunca por API, para no
  contaminar rate limiters). Tokens JWT pre-generados para cada alumno de prueba.
- **Carga**: k6 con rampa 10→50→150→500 VUs (30s por etapa) donde aplica, o
  ráfagas concurrentes puntuales (per-vu-iterations). Cada VU ejecuta su acción
  una vez.
- **Monitoreo**: `_monitor_backend.py` muestrea CPU%/RSS del proceso backend
  cada 0.5s → CSV (`_analizar_monitor.py` agrupa por ventanas de 30s).
- **Verificación post-corrida**: scripts `_verificar_escenario_*.py` chequean
  invariantes en BD (cupo, tokens, stock, duplicados, estados).
- **Cleanup**: `_cleanup_load_test.py` + chequeo global final
  `_check_leftovers_global.py` (0 leftovers confirmado al cierre).

---

## 3. Tabla consolidada de escenarios

| Esc | Qué se probó | Resultado k6 | Invariantes verificadas | Estado |
|---|---|---|---|---|
| **B** | Reservas concurrentes a la MISMA clase (cupo=50) | 50×201 + 450×400 + 0×5xx | cupo exacto, token descontado ⟺ reserva (1:1), sin créditos negativos | ✅ |
| **C** | Compra de plan + doble-aprobación concurrente (2 pares sobre s0/s1) | 20×200 + 2×400 + 0×5xx | 20 solicitudes approved, 20 suscripciones (0 duplicados), 20 transacciones, Prueba→vencido | ✅ |
| **D** | Bazar: compras concurrentes del mismo producto (stock=30) | 30×201 + 20×400 + 0×5xx (1×500 transitorio en 1ª corrida) | stock final 0 (nunca negativo), 30 pedidos, 1/alumno, total correcto | ✅ |
| **F1** | RMs volumen: lecturas con historial cargado (20×20 filas) | 147 req, 0 fallos, 100% checks | historial intacto | ✅ |
| **F2** | RMs concurrencia: 500 alumnos registran RM | 500/500 creados en BD (231 resp. dentro de 60s; resto timeout de respuesta) | 0 duplicados, 0 faltantes | ✅ |
| **A** | Registro masivo (rate limit 5/hora) | 5×201 + 495×429 + 0×5xx | 5 usuarios únicos, sin duplicados, pendiente_activacion + Prueba pendiente | ✅ |
| **E** | Mix final (login+reservas+plan+bazar+registro, 60s) | reservas 30/30, bazar 20/20, aprobar 10, solicitudes 5, login 5/30 (rate), registro 5, 0×5xx | 4/4 invariantes PASS | ✅ |

---

## 4. Límite real del plan Free (Neon) — confirmado empíricamente

| Recurso | Valor medido | Detalle |
|---|---|---|
| **Pooler Neon (PgBouncer)** | **~100 transacciones concurrentes** | Probe `_probe_neon_slots.py`: N=50 paralelo total; N=300→6.0s, N=500→8.9s (pg_sleep 2s) ≈ 100-110 slots. El "10 de Free" documentado antes **no aplica hoy** (Neon lo subió a ~100 pooled). |
| **Conexiones cliente al pooler** | ≥61 sin rechazo | Probe `_probe_neon_pool.py` (multiplexa clientes sobre pocas conexiones de servidor). |
| **SQLAlchemy pool** | pool_size=50 + max_overflow=100 = **150** | `app/db/database.py`; supera el techo del pooler → cola PgBouncer a partir de ~100 transacciones concurrentes. |
| **Threadpool uvicorn** | **40 hilos** para endpoints síncronos | Todas las rutas son `def` (síncronas) → máx 40 requests a la vez; el resto espera. |
| **Latencia Neon Free** | ~0.5-2s por query (vía pooler, incluye TLS) | Endpoints multi-query (ej. `rms` agrupado F1: ~11s) acumulan varios roundtrips. |
| **CPU backend** | avg 40-45%, max ~79% (nunca saturado) | El cuello NO es el proceso Python. |
| **RAM backend** | ~12-14 MB RSS | Irrelevante. ⚠️ El HOST local estuvo a 90-97% de RAM durante las corridas (factor ambiental a monitorear). |

### Conclusión para la fase de despliegue (NOTA, no accionable ahora)

Para sostener **500 usuarios reales simultáneos** en producción se necesita, en
orden de impacto:
1. **Plan Neon ≥ Pro** (pooler ≥100-500; Free queda corto para picos de 500
   transacciones concurrentes) — o desacoplar lecturas (replicas).
2. **Levantar más de un worker uvicorn** (o migrar los endpoints síncronos a
   async/greenlets) para superar el techo de 40 hilos.
3. **Optimizar los endpoints multi-query** detectados en F1 (ver §6c) antes de
   escalar usuarios.

---

## 5. Rate limiters — techos POR DISEÑO (no son bugs)

| Limiter | Valor | Endpoints | Impacto en el test |
|---|---|---|---|
| Registro | **5/hora/IP** (`LIMIT_REGISTRO`) | `/alumnos/registro/alumno-nuevo` | Escenario A: 5×201 + 495×429 |
| Crítico | **30/minuto/IP** (`LIMIT_CRITICO`) | `solicitar`, `aprobar`, `rechazar`, `POST /suscripciones`, `comprar-emergencia`, `upload/voucher`, `POST /usuarios` | Escenario C bajo ese techo |
| Login | **5/minuto/IP** (`LIMIT_LOGIN`) | `/auth/login` | Escenario E: solo 5/30 logins |

En **producción cada usuario real tiene su propia IP** → estos límites no
deberían ser un problema práctico. **Excepción**: redes NAT compartidas (ej. red
interna del box, kiosco, integraciones que logueen desde una IP única) quedan
throttleadas — si un día eso molesta, subir `LIMIT_LOGIN`/`LIMIT_CRITICO` en
config, no es un cambio de código.

---

## 6. Hallazgos menores pendientes (severidad + recomendación)

| # | Hallazgo | Severidad | Recomendación |
|---|---|---|---|
| **a** | `pedidos.py` no capturaba errores de BD (deadlock/timeout bajo contención extrema) → el 1×500 transitorio del Escenario D fue un `500` genérico | Media | **APLICADO (Iteración 2)**: wrapper que devuelve `503 "Alta demanda, intentá de nuevo"` + rollback. Aplicado también a `reservas.py` (UPDATE de cupo) y `historial_rm.py` (INSERT) por consistencia. |
| **b** | `enviar_email_solicitud_admin` enviaba al **primer admin GLOBAL de la BD** (sin filtro de tenant) → un alumno de un box generaba un correo al admin de otro box | Media | **APLICADO (Iteración 2)**: ahora filtra `tenant_id` del alumno registrado. |
| **c** | Endpoints más lentos en F1: `rms` agrupado (~11s), `nivel-gimnastico` (~10.7s), `progreso-destacado` (~8.7s) — multi-query sobre Neon | Baja | Optimización futura (joins/paginación), **no bloqueante** para el despliegue. |

---

## 7. Datos de referencia por corrida (latencia / CPU / memoria)

| Esc | Latencia relevante | CPU backend | RSS | Notas |
|---|---|---|---|---|
| B | éxitos ~0.9s; "sin cupo" 13-40s (row-lock) | avg 45% / max 76% | 12MB | degradación al llenarse la clase |
| C | aprobación ~12s (6-8 queries seriales) | avg 40% / max 61% | 12MB | 0×5xx, sin duplicados |
| D | ~35s corrida 1 / ~14s corrida 2 (contención stock) | — | — | 1×500 transitorio (no reproducido) |
| F1 | rms 11.2s · nivel-gim 10.7s · progreso 8.7s · nivel-fuerza 4.0s · vista-grupo 2.3s | — | — | 147 req, 0 fallos |
| F2 | med 2s, p90 60s (timeouts de respuesta) | avg 42% / max 73% | 14MB | 500/500 integridad |
| A | 429 ~37ms; registros exitosos ~7.5s | avg 43% / max 89% | 14MB | email al admin global (ver §6b) |
| E | avg ~32s bajo el mix | avg 43% / max 79% | 14MB | login 5/min (ver §5) |

---

## 8. ⛔ REQUIERE DECISIÓN (pendiente para revisión despierto)

*(Vacío al cierre — ninguna decisión de producto/arquitectura pendiente fuera del
alcance de este prompt. Las decisiones tomadas quedaron documentadas en el
cuerpo: rate limiters intactos, plan Free como techo real, fixes a/b aplicados.)*

---

## 9. Estado de herramientas

- Scripts reutilizables commiteados: seeds `_seed_load_test_{b,c,d,f,a,e}.py`,
  verificadores `_verificar_escenario_*.py`, `scenario_*.js` (k6),
  `_monitor_backend.py`, `_cleanup_load_test.py`, `_analizar_monitor.py`,
  `_check_leftovers_global.py`, `_probe_neon_pool.py`, `_probe_neon_slots.py`.
- k6 instalado en `C:\Program Files\k6\k6.exe` (v2.2.0).
- Backend local corriendo en `http://localhost:8000` con los fixes cargados.
