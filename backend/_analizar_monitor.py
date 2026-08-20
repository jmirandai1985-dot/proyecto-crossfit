"""Análisis del CSV del monitor: CPU/RSS promediados por ventana de 30s."""
import csv
from collections import defaultdict

rows = []
with open("backend_monitor.csv", encoding="utf-8") as f:
    r = csv.DictReader(f)
    for line in r:
        rows.append((float(line["t_sec"]), float(line["cpu_pct"]),
                     float(line["rss_mb"]), float(line["sys_mem_pct"])))

buckets = defaultdict(list)
for t, cpu, rss, sysmem in rows:
    buckets[int(t // 30) * 30].append((cpu, rss, sysmem))

print("ventana(s) | cpu%avg | cpu%max | rss_avg(MB) | sysmem%avg | n")
for vent in sorted(buckets):
    cpus = [x[0] for x in buckets[vent]]
    rsss = [x[1] for x in buckets[vent]]
    sysm = [x[2] for x in buckets[vent]]
    print(f"  {vent:>5}-{vent+29:<3} | {sum(cpus)/len(cpus):6.1f} | {max(cpus):6.1f} | "
          f"{sum(rsss)/len(rsss):9.1f} | {sum(sysm)/len(sysm):9.1f} | {len(cpus)}")

print(f"\nTOTAL: {len(rows)} muestras | CPU avg {sum(x[1] for x in rows)/len(rows):.1f}% "
      f"max {max(x[1] for x in rows):.1f}% | RSS max {max(x[2] for x in rows):.1f}MB "
      f"| sysmem max {max(x[3] for x in rows):.1f}%")
