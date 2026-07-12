"""
Diagnostico: clases de Lunes 13 - duplicadas y clasificacion manana/tarde
"""
from app.db.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    print("=" * 80)
    print("CLASES PARA LUNES 2026-07-13 (SIN AGRUPAR)")
    print("=" * 80)
    rows = db.execute(text("""
        SELECT c.id, c.hora_inicio, c.hora_fin, d.nombre as disciplina, u.nombre as coach, c.cupo_maximo, c.asistentes_confirmados
        FROM clases c
        LEFT JOIN disciplinas d ON c.disciplina_id = d.id
        LEFT JOIN usuarios u ON c.coach_id = u.id
        WHERE c.tenant_id = 1 AND c.fecha = '2026-07-13'
        ORDER BY c.hora_inicio, d.nombre, u.nombre
    """)).fetchall()
    for r in rows:
        inicio = str(r.hora_inicio)
        fin = str(r.hora_fin)
        manana = "MANANA" if int(inicio.split(':')[0]) < 14 else "TARDE"
        print(f"  id={r.id:>3} {inicio}-{fin} {r.disciplina or '?':>25} coach={r.coach or '?':>15} cupo={r.cupo_maximo} asistentes={r.asistentes_confirmados} -> {manana}")
    print(f"\n  Total filas (sin agrupar): {len(rows)}")

    # Ahora agrupar por (disciplina, hora_inicio, hora_fin)
    print()
    print("=" * 80)
    print("AGRUPADO POR (disciplina, hora_inicio, hora_fin) - Para mostrar en frontend")
    print("=" * 80)
    grupos = {}
    for r in rows:
        key = (r.disciplina, str(r.hora_inicio), str(r.hora_fin))
        if key not in grupos:
            grupos[key] = []
        grupos[key].append(r)

    for key in sorted(grupos.keys(), key=lambda k: (k[1], k[0])):
        items = grupos[key]
        disciplina, hi, hf = key
        inicio_hora = int(hi.split(':')[0])
        zona = "MANANA" if inicio_hora < 14 else "TARDE"
        cupo = items[0].cupo_maximo
        asistentes = sum(item.asistentes_confirmados for item in items)
        coaches = ", ".join(item.coach or "?" for item in items)
        print(
            f"  {hi}-{hf} {disciplina:>25} cupo={cupo} asistentes={asistentes} coaches=[{coaches}] -> {zona}")

    print(f"\n  Total únicos (a mostrar): {len(grupos)}")

    # Conteo por zona
    manana_count = sum(1 for k in grupos if int(k[1].split(':')[0]) < 14)
    tarde_count = sum(1 for k in grupos if int(k[1].split(':')[0]) >= 14)
    print(f"\n  MAÑANA: {manana_count} filas unicas")
    print(f"  TARDE: {tarde_count} filas unicas")

finally:
    db.close()
