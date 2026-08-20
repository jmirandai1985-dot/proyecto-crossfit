"""Probe 2: slots concurrentes de transacción del pooler (PgBouncer, plan Free).

Uso: python _probe_neon_slots.py [N]   (default 16)

Conexiones cliente en paralelo, cada una ejecuta BEGIN + SELECT pg_sleep(2)
+ COMMIT. Mide cuántas consiguen slot de servidor en la primera ola (~2s);
las que tardan mas quedaron en cola del pooler.
"""
import sys
import time
import threading
import psycopg2
from urllib.parse import urlparse
from app.core.config import settings

N = int(sys.argv[1]) if len(sys.argv) > 1 else 16
url = urlparse(settings.DATABASE_URL)
P = dict(host=url.hostname, port=url.port or 5432, user=url.username,
         password=url.password, dbname=url.path.lstrip("/"),
         sslmode="require", connect_timeout=5)

resultados = [None] * N
errores = [None] * N


def worker(i):
    t0 = time.time()
    try:
        c = psycopg2.connect(**P)
        cur = c.cursor()
        cur.execute("BEGIN")
        cur.execute("SELECT pg_sleep(2)")
        cur.execute("COMMIT")
        cur.close()
        c.close()
        resultados[i] = time.time() - t0
    except Exception as e:
        errores[i] = str(e).splitlines()[0][:120]
        resultados[i] = -1


print(f"[probe2] conectando {N} clientes en paralelo (pg_sleep 2s)...", flush=True)
inicio = time.time()
threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
for t in threads:
    t.start()
for t in threads:
    t.join()
total = time.time() - inicio

segunda_ola = []
for i in range(N):
    if errores[i]:
        print(f"  cliente {i:02d}: ERROR {errores[i]}")
    elif resultados[i] > 3.0:
        segunda_ola.append((i, resultados[i]))
        print(f"  cliente {i:02d}: {resultados[i]:.2f}s  <-- EN COLA")

primera_ola = sum(1 for r in resultados if r is not None and 0 < r < 3.0)
print("\n" + "=" * 60)
print(f"N={N}: primera_ola={primera_ola}  en_cola={len(segunda_ola)}  "
      f"errores={sum(1 for e in errores if e)}")
print(f"  duracion total del batch: {total:.1f}s")
print("=" * 60)
