# Cierre del punto 1 — Banner "Error al cargar los alumnos de la clase"

Fecha: 2026-10-15 · Autor: sesión de auditoría
**Conclusión: evento aislado de INFRAESTRUCTURA (instancia de Render reiniciándose). No hay bug
de código y no se toca el endpoint.** Queda documentado con reproducción determinista.

## El reporte (Jebbus, 15-oct)

1. **Síntoma**: banner rojo — "Error al cargar los alumnos de la clase" (no spinner infinito, no
   lista vacía silenciosa).
2. **Hora**: 06:44-06:56 am hora Chile (UTC-3) → coincide con la ventana en que la instancia de
   Render falló el health check y se reinició (`Instance srv-dagotnmq1p3s73bu0chg-jz19j restarted`
   a las 06:52:41).
3. **Pantalla**: pestaña Asistencia → tocar "Marcar" en una clase (07:00 CrossFit).

## Lo que NO se pudo hacer (declarado, para no inventar)

**No se pudieron leer los logs de Render de esa ventana**: este entorno no tiene `RENDER_API_KEY`
(`$env:RENDER_API_KEY` vacío), no existe `~/.render` y el repo sólo tiene `render.yaml` (blueprint,
sin credenciales). Sin esa clave no hay acceso a `GET /v1/services/{id}/logs`. **Todo lo de abajo
es evidencia de código + reproducción, no una lectura de logs.**

## Evidencia 1 — por dónde sale ese texto exacto

| archivo:línea | qué dice |
|---|---|
| `frontend/src/hooks/queries.js:222-231` | `useAlumnosDeClase` → `GET /api/v1/asistencia/clases/{id}/alumnos`, `enabled` sólo con la clase abierta (`staleTime 30 s`) |
| `frontend/src/components/AsistenciaClases.jsx:79-84` | si esa query está en error, `mensaje = { tipo: 'error', texto: error?.response?.data?.detail \|\| 'Error al cargar los alumnos de la clase' }` |
| `frontend/src/components/AsistenciaClases.jsx:337-347` | el banner rojo es ESE `mensaje`, dentro del modal de la clase (el que abre "Marcar") |

**Dato clave del texto**: el banner dice el texto GENÉRICO porque la respuesta de error **no traía
`detail`**. Los endpoints de la app devuelven `{"detail": ...}` (así lo muestra
`AsistenciaClases.jsx:55` para las clases de hoy). Un cuerpo sin `detail` es lo que devuelve el
**proxy/instancia caída** (HTML "502 Bad Gateway"), no el backend de la app.

## Evidencia 2 — reproducción determinista del síntoma

Se agregó al harness la posibilidad de inyectar esa falla (`FALLO_502`, con el cuerpo HTML real
de un 502) y una pantalla que hace el gesto reportado (Asistencia → "Marcar"):

```
cd frontend
$env:PANTALLA='asistencia-fallo'; $env:FALLO_502='/asistencia/clases/777/alumnos'
node scripts/capturas-bloque2.mjs
```

Salida real:

```
01-banner-502-al-abrir-la-clase  (390x844) -> ...\mockup\_audit\punto1-fallo-502\01-banner-502-al-abrir-la-clase.png

capturas: 1/1   ·   errores de consola: 0
RESULTADO: OK
```

La captura muestra **exactamente** el síntoma reportado: modal de la clase (CrossFit 18:00-19:00)
con el banner "Error al cargar los alumnos de la clase". Y 0 errores de consola: la app maneja
bien la falla (no revienta, no hay pantalla blanca).

Re-verificado el mismo 15-oct **después** de los otros arreglos de la serie (categoría del RM y
z-index del Layout): `capturas: 1/1 · errores de consola: 0 · RESULTADO: OK`.

### Control (el mismo flujo con el endpoint sano)

```
cd frontend
$env:PANTALLA='asistencia-fallo'; Remove-Item env:FALLO_502
node scripts/capturas-bloque2.mjs
```

Salida real (falla ESPERADA — es el control negativo):

```
[FALLA] 01-banner-502-al-abrir-la-clase: no apareció [data-testid="aviso-asistencia"]
capturas: 0/1   ·   errores de consola: 0
RESULTADO: FALLA
```

Es decir: **sin una falla del endpoint el banner no existe**. No hay condición de datos ni de
permisos que lo dispare: el coach tiene permiso sobre ese endpoint (mismo camino que el flujo
normal, que hoy funciona en las corridas de `PANTALLA=asistencia`).

## Conclusión

- El banner es la UI diciendo "el endpoint no contestó", y el timing (06:44-06:56, con el restart
  a las 06:52:41) lo ubica en la ventana en que Render estaba reiniciando la instancia: las
  peticiones en vuelo reciben 502 del proxy.
- **No es reproducible con la app sana** (control negativo arriba) y no hay nada en el endpoint ni
  en la pantalla que arreglar. Se cierra como **evento aislado de infraestructura**.

## Backlog relacionado (NO es el bug del punto 1)

1. `frontend/src/services/api.js` **no define `timeout`**. Con `retry: 1`, un cold-start lento se
   ve como espera larga en lugar de error: conviene un `timeout` explícito (~20 s) y un mensaje.
2. El banner de error de la clase **no ofrece "Reintentar"**: hay que cerrar y volver a abrir la
   clase. Un botón de reintento (como el que ya tiene la ficha del coach) ahorraría ese paso.
3. El texto genérico no distingue "la API no contesta" (502/timeout) de "no hay datos": con
   `response.status` se podría decir "el servidor no responde, reintentá en un momento".
