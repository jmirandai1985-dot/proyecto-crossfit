"""
Monitor del backend durante la carga (psutil).

Muestrea cada 0.5s al proceso python que escucha en el puerto 8000:
  - CPU% (delta desde la última muestra)
  - RSS (MB)
  - memoria usada total del sistema (%)
Escribe CSV con timestamp. Detener con Ctrl+C o tras N segundos (arg opcional).
"""
import sys
import time
import csv
import psutil

PORT = 8000
CSV = "backend_monitor.csv"


def find_backend_pid():
    for conn in psutil.net_connections(kind="tcp"):
        if conn.laddr.port == PORT and conn.status == "LISTEN":
            return conn.pid
    return None


def main():
    max_secs = float(sys.argv[1]) if len(sys.argv) > 1 else 3600
    pid = find_backend_pid()
    if not pid:
        print(f"ERROR: no hay proceso escuchando en :{PORT}")
        sys.exit(1)
    proc = psutil.Process(pid)
    print(f"[monitor] backend PID={pid} ({proc.name()}) -> {CSV}")
    print("[monitor] muestreo cada 0.5s. Ctrl+C para detener.")
    proc.cpu_percent(None)  # primera llamada = baseline
    with open(CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_sec", "cpu_pct", "rss_mb", "sys_mem_pct"])
        t0 = time.time()
        try:
            while time.time() - t0 < max_secs:
                cpu = proc.cpu_percent(None)
                rss = proc.memory_info().rss / (1024 * 1024)
                sysmem = psutil.virtual_memory().percent
                w.writerow([f"{time.time() - t0:.1f}", f"{cpu:.1f}",
                            f"{rss:.1f}", f"{sysmem:.1f}"])
                f.flush()
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\n[monitor] detenido por usuario")
    print(f"[monitor] fin. CSV: {CSV}")


if __name__ == "__main__":
    main()
