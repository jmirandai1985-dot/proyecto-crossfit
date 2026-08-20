"""Paso 0: mide el límite empírico de conexiones del pooler de Neon (plan Free).

Solo lectura (SELECT 1 / pg_stat_activity). Abre conexiones CLIENTE al endpoint
pooled (URL con -pooler) hasta que el pooler las rechaza o expira el tiempo.
Reporta:
  - probe_OK: conexiones adicionales que acepta el pooler (capacidad disponible
    con la app arriba).
  - server_total: conexiones reales al Postgres (pg_stat_activity) en el punto
    de fallo (POV informativo).
Cierra todo en finally. No modifica datos.
"""
import sys
import time
import psycopg2
from urllib.parse import urlparse
from app.core.config import settings

url = urlparse(settings.DATABASE_URL)
P = dict(host=url.hostname, port=url.port or 5432, user=url.username,
         password=url.password, dbname=url.path.lstrip("/"),
         sslmode="require", connect_timeout=5)

conns = []
testigo = None
ok = 0
error_msg = None
server_total = "?"
duracion = 0.0
try:
    testigo = psycopg2.connect(**P)
    cur = testigo.cursor()
    cur.execute("SELECT 1")
    cur.fetchone()
    cur.close()

    def total_activas():
        cur = testigo.cursor()
        cur.execute("SELECT count(*) FROM pg_stat_activity")
        n = cur.fetchone()[0]
        cur.close()
        return n

    print(f"[probe] server activas ANTES = {total_activas()}", flush=True)
    inicio = time.time()
    for i in range(1, 61):
        try:
            c = psycopg2.connect(**P)
            cur = c.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            cur.close()
            conns.append(c)
            ok += 1
            print(f"[{i}] OK (probe={ok}, server={total_activas()})", flush=True)
        except Exception as e:
            error_msg = str(e).splitlines()[0][:160]
            try:
                server_total = total_activas()
            except Exception:
                server_total = "?"
            print(f"[{i}] RECHAZADA: {error_msg}", flush=True)
            print(f"      server_total_al_fallar = {server_total}", flush=True)
            break
        if time.time() - inicio > 50:
            print("      (timeout global 50s)", flush=True)
            break
    duracion = time.time() - inicio
finally:
    for c in conns:
        try:
            c.close()
        except Exception:
            pass
    if testigo is not None:
        try:
            testigo.close()
        except Exception:
            pass

print("\n" + "=" * 60)
print(f"RESULTADO (plan Free):")
print(f"  probe_OK (conexiones cliente adicionales aceptadas) = {ok}")
print(f"  + testigo                                          = 1")
print(f"  server_total al fallar (pg_stat_activity)          = {server_total}")
print(f"  error observado                                    = {error_msg}")
print(f"  duracion                                           = {duracion:.1f}s")
print("  INTERPRETACION: probe_OK+1 ≈ limite del pooler (10 Free) menos las")
print("  conexiones cliente que ya tiene la app corriendo (backend PID 13732).")
print("=" * 60)
