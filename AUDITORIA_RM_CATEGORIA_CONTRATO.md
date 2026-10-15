# Auditoría — la categoría del RM viaja en la respuesta (H-03)

Fecha: 2026-10-15 · Autor: sesión de auditoría
**Decisión aprobada por Jebbus (15-oct): "expón/usa `categoria` en `/alumnos/{id}/rms` para que
Sled Push no pierda los minutos".** Hallazgo 1 del Bloque 5
(`AUDITORIA_BLOQUE5_ALUMNOS_RMS.md` §4), arreglado acá.

## 1. El bug, con el dato real de PRODUCCIÓN

Script: `%TEMP%\bloque5\rm_contrato.py` (engine del backend, SÓLO `SELECT`; alumno 5 =
"Alumno Demo"). Replica **exactamente** el armado del endpoint
(`historial_rm.py` → `RMPorMovimiento(**{campo: rm[campo] for campo in CAMPOS_SCHEMA})`):

```
cd backend
$env:ENVIRONMENT='production'; $env:PYTHONPATH=(Get-Location).Path
py -3.12 "$env:TEMP\bloque5\rm_contrato.py"
```

El movimiento "Sled Push" del alumno 5, tal como está en la BD:

```
{"mov": "Sled Push", "cat_dict": "cardio", "cat_json": "<FALTA>",
 "peso_kg": 1.0, "minutos": 2, "km": 0.4, "vueltas": 1,
 "unidad_backend": "min", "valor_backend": "2 min"}
```

- La BD dice **`cardio`** con **`minutos = 2`** (el `peso_kg = 1,0` es el dummy de siempre).
- El servicio **ya calculaba bien** `categoria` y `valor_mostrado` ("2 min").
- Pero el JSON del endpoint salía **sin `categoria`**: `RMPorMovimiento` no la declaraba y no
  estaba en `CAMPOS_SCHEMA`, así que el front la adivinaba por el NOMBRE
  (`frontend/src/utils/rm.js`): "sled" cae en la rama `metabolico`
  (`/sled|air.?runner|sandbag|farmer|carry/`), que **no tiene minutos** → el valor se dibujaba
  **"0.4 km, 1 vueltas"**.
- El mismo hueco tenía la **lista plana** (`GET /historial-rm`): `HistorialRMListItem` tampoco
  traía la categoría, y esa lista alimenta el gráfico semanal del alumno (`PerformanceHub`), que
  agrupa por categoría → Sled Push caía al cuadrante "Metabólico".

## 2. El arreglo (contrato, no parche de pantalla)

| archivo | cambio |
|---|---|
| `backend/app/services/rms_service.py:26-34` | `"categoria"` entra en `CAMPOS_SCHEMA` (viaja al schema; `unidad`/`valor_mostrado` siguen siendo presentación derivada) |
| `backend/app/schemas/historial_rm.py:99-103` | `RMPorMovimiento.categoria` |
| `backend/app/schemas/historial_rm.py:82-86` | `HistorialRMListItem.categoria` |
| `backend/app/api/v1/historial_rm.py:291-294` | la lista plana selecciona `Movimiento.categoria.label('categoria_mov')` |
| `backend/app/api/v1/historial_rm.py:321-324` | y la normaliza con `categoria_de(SimpleNamespace(...))` (BD → alias → nombre), igual que `rms_service` |

**No hizo falta tocar el frontend**: `utils/rm.js` (`inferirCategoriaRM`, H-03) ya prefería
`rm.categoria` sobre la heurística por nombre, y las pantallas que formatean (`AlumnoFichaCoach`,
`DashboardCoach`, `PerformanceHub`, `PizarraRMs`) pasan el objeto entero. Lo único que se actualizó
es el **fixture del harness** (`capturas-bloque2.mjs:115-127`), que ahora manda la categoría real de
cada movimiento.

## 3. Verificación

### 3.1 Contra PRODUCCIÓN (sólo lectura)

```
CAMPOS_SCHEMA: ('id', 'movimiento_id', 'movimiento_nombre', 'categoria', ...)
¿'categoria' en CAMPOS_SCHEMA? True     ¿'categoria' en RMPorMovimiento? True
{"mov": "Sled Push", "cat_dict": "cardio", "cat_json": "cardio", ... "valor_backend": "2 min"}
{"mov": "Air Runner", "cat_dict": "metabolico", "cat_json": "metabolico", ... "valor_backend": "300 cal"}
```

Lista plana (`%TEMP%\bloque5\rm_lista.py`, mismo alumno, 16 filas): el SQL del endpoint corre y
normaliza todo bien — `Sled Push → cardio` (3 filas), `Air Runner → metabolico` (6),
`Clean/Snatch → fuerza` (4), los tres `*Pull-up`/`C2B → gimnastico` (4). Borde del
`LEFT JOIN isouter`: un movimiento inexistente deja `categoria_mov = NULL` y la normalización cae
al nombre (`"fuerza"`), sin excepción.

### 3.2 El valor que ve el coach (harness, mismas 4 tomas)

`MEDIR_FICHA` (`capturas-bloque2.mjs:352-392`) lee el texto renderizado de cada fila:

| | valor del Sled Push |
|---|---|
| ANTES (`%TEMP%\bloque5\run1-antes.txt`, fixture sin `categoria` = respuesta de prod) | **"0.4 km, 1 vueltas"** |
| DESPUÉS (`%TEMP%\bloque5\run3-zindex.txt`) | **"0.4 km, 2 min, 1 vueltas"** |

Los otros tres valores de la lista no se movieron: `"160 kg"`, `"10 reps x 3 series"`,
`"300 cal, 3.5 km, 10 vueltas"`.

### 3.3 Tests

`backend/tests/test_rm_categoria_contrato.py` (nuevo, aislado: `--noconftest`, sin red ni base):

- `test_a1`: `categoria` es parte del contrato (`CAMPOS_SCHEMA` + `RMPorMovimiento`).
- `test_a2`: la fila REAL de Sled Push (los mismos valores de PROD) llega como `cardio` con
  `valor_mostrado == "2 min"` y el dummy `peso_kg == 1.0` intacto.
- `test_a3`: contra-prueba — sin el campo, el mismo RM pierde la categoría de la BD.
- `test_b1`: la lista plana declara el campo y el endpoint lo selecciona.
- `test_c1`: guard de fuente del front (`utils/rm.js` lee `rm.categoria` ANTES del nombre).

```
cd backend && py -3.12 -m pytest tests/test_rm_categoria_contrato.py -q --noconftest   # 5 passed
```

## 4. Lo que queda afuera (a propósito)

1. **La heurística por nombre sigue existiendo** como último recurso (`utils/rm.js:39-43`), y
   sigue clasificando `sled` como `metabolico`. Hoy casi no se usa (los dos endpoints ya mandan la
   categoría y los formularios pasan `categoriaForzada`), pero un objeto armado a mano en el front
   sin categoría caería ahí. Alinearla con la BD del box es una decisión de producto (¿"Sled Push"
   es cardio en todos los boxes?), no un bug de este contrato.
2. **El dummy `peso_kg`** sigue viajando (el schema lo declara obligatorio): el front lo ignora
   para cardio/máquinas. Anotado, sin tocar.
3. **`DashboardCoach.jsx:204`** pide `useHistorialRmTodos(5)` y hoy sólo usa el error (`:320-324`):
   el dato no se pinta. El cambio no tiene efecto visible ahí, pero deja la consulta consistente.
