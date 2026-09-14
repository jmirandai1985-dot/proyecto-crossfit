"""Validación del módulo de segmentación contra PROD (SOLO LECTURA).

Corre `ml.segmentacion.entrenar_segmentacion` contra la BD de PRODUCCIÓN y
compara con los números ya conocidos del análisis exploratorio (fases 1-2):
    - silhouette 0.4699 (K=5, semilla 42, StandardScaler)
    - conteos por arquetipo: ACTIVO_FIEL=42, NUEVO=17, ACTIVO_EN_DECLIVE=18,
      ABANDONADO_RECUPERABLE=18, ABANDONADO_PERDIDO=11  (total 106)

No escribe nada (build_features solo hace SELECT). Guard: 'withered-silence'.

Uso (dentro del contenedor, con la URL de PROD como env var):
    docker cp backend/_validar_segmentacion.py box-crossfit-backend-1:/tmp/
    docker exec -e DATABASE_URL=<PROD> -w /app box-crossfit-backend-1 \
        python /tmp/_validar_segmentacion.py
"""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.core.config import settings  # noqa: E402

_url = settings.DATABASE_URL
if "withered-silence" not in _url or "polished-term" in _url:
    print("ERROR: la BD activa NO es PROD. Abortando.")
    sys.exit(1)

from app.db.database import SessionLocal  # noqa: E402
import ml.segmentacion as seg  # noqa: E402

TENANT_ID = 1
ESPERADO_SIL = 0.4699
ESPERADO_N = 106
ESPERADO_CONTEOS = {
    "ACTIVO_FIEL": 42,
    "NUEVO": 17,
    "ACTIVO_EN_DECLIVE": 18,
    "ABANDONADO_RECUPERABLE": 18,
    "ABANDONADO_PERDIDO": 11,
}

print("=" * 78)
print("VALIDACION ml/segmentacion.py contra PROD (SOLO LECTURA)")
print(f"host: {_url.split('@')[-1].split('/')[0]}")
print("=" * 78)

db = SessionLocal()
try:
    artefacto, metadata, etiquetas = seg.entrenar_segmentacion(db, TENANT_ID)
finally:
    db.close()

fallos = []


def check(nombre, ok, detalle=""):
    print(f"  [{'OK ' if ok else 'FAIL'}] {nombre} {detalle}")
    if not ok:
        fallos.append(nombre)


print(f"n_alumnos={metadata['n_alumnos']}  K={metadata['k']}  "
      f"silhouette={metadata['silhouette']}")
print(f"etiquetas generadas: {len(etiquetas)}")
print("-" * 78)
check("n_alumnos == 106", metadata["n_alumnos"] == ESPERADO_N,
      f"({metadata['n_alumnos']})")
check("silhouette ~ 0.4699", abs(metadata["silhouette"] - ESPERADO_SIL) < 5e-4,
      f"({metadata['silhouette']})")
check("len(etiquetas) == n_alumnos", len(etiquetas) == metadata["n_alumnos"])
print("-" * 78)
print(f"{'arquetipo':<24} {'n':>4}  esperado")
for arq in seg.ARQUETIPOS:
    n = metadata["arquetipos"].get(arq, 0)
    esp = ESPERADO_CONTEOS.get(arq, 0)
    check(f"conteo {arq}", n == esp, f"{n:>4}  {esp:>4}")

print("-" * 78)
print("Perfiles por cluster (medianas en unidades reales):")
for c in sorted(metadata["perfiles_cluster"], key=int):
    pf = metadata["perfiles_cluster"][c]
    med = pf["medianas"]
    print(f"  cluster {c}: n={pf['n_alumnos']:>3} "
          f"regla={metadata['reglas_cluster'][c]} "
          f"-> {metadata['nombres_cluster'][c]:<22} "
          f"dias={med['dias_desde_ultima_asistencia']:>6} "
          f"a30={med['asistencias_ultimos_30_dias']:>5} "
          f"a90={med['asistencias_ultimos_90_dias']:>5} "
          f"ant={med['antiguedad_dias']:>6} "
          f"susc={pf['pct_suscripcion_activa']}")

print("-" * 78)
print("Chequeos de integridad de las etiquetas:")
arqs = {e["arquetipo"] for e in etiquetas}
check("todos los arquetipos son validos", arqs <= set(seg.ARQUETIPOS),
      f"({sorted(arqs)})")
check("clusters 0..K-1 presentes",
      len({e["cluster_id"] for e in etiquetas}) == metadata["k"])
check("perfil_json tiene modelo/cluster/alumno",
      all(set(e["perfil_json"]) == {"modelo", "cluster", "alumno"}
          for e in etiquetas))

print("=" * 78)
if fallos:
    print(f"RESULTADO: {len(fallos)} CHEQUEOS FALLIDOS -> {fallos}")
    sys.exit(1)
print("RESULTADO: TODOS LOS CHEQUEOS OK (reproduce el analisis exploratorio)")
print("=" * 78)
