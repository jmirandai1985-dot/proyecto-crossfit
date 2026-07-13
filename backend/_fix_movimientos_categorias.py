"""
Temporary script: fix movimiento categorias in test DB
"""
import importlib
import os

os.environ["ENVIRONMENT"] = "test"

db = importlib.import_module("app.db.database").SessionLocal()
text = importlib.import_module("sqlalchemy").text

# Update existing
db.execute(text(
    "UPDATE movimientos SET categoria='gimnastico' WHERE nombre='Pull-ups' AND tenant_id=1"))
db.execute(text(
    "UPDATE movimientos SET categoria='metabolico' WHERE nombre='Burpees' AND tenant_id=1"))

# Add missing cardio
for nombre in ["Row", "Assault Bike", "Ski Erg"]:
    row = db.execute(text("SELECT id FROM movimientos WHERE nombre=:n AND tenant_id=1"), {
                     "n": nombre}).fetchone()
    if not row:
        db.execute(text(
            "INSERT INTO movimientos (tenant_id, nombre, categoria, activo) VALUES (1, :n, 'cardio', True)"), {"n": nombre})

db.commit()

# Show final table
rows = db.execute(text(
    "SELECT id, nombre, categoria FROM movimientos WHERE tenant_id=1 ORDER BY id")).fetchall()
print("ID | NOMBRE         | CATEGORIA")
print("-" * 40)
for r in rows:
    print(f"{r[0]:2} | {r[1]:<14} | {r[2]}")

db.close()
