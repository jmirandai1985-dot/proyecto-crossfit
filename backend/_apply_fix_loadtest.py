"""Aplica los fixes confirmados para el test de esfuerzo:

1) pedidos.py (Bazar): descuento de stock ATÓMICO (UPDATE condicional
   WHERE stock >= cantidad) — elimina la race condition que podía dejar
   stock negativo bajo concurrencia.
2) solicitudes_planes.py: aprobar/rechazar solo si estado == "pending"
   (evita doble procesamiento → suscripciones/transacciones duplicadas).
Preserva CRLF/LF y verifica cada reemplazo (1 match).
"""
import io
import os

BASE = r"c:\Users\Asus\Desktop\Proyectos\proyecto-crossfit\backend"


def _leer(ruta):
    with io.open(ruta, "r", encoding="utf-8", newline="") as f:
        return f.read()


def aplicar(rel, tag, old, new):
    ruta = os.path.join(BASE, rel)
    src = _leer(ruta)
    e = "\r\n" if "\r\n" in src else "\n"
    old_crlf = old.replace("\n", e)
    new_crlf = new.replace("\n", e)
    n = src.count(old_crlf)
    if n != 1:
        raise SystemExit(f"[{tag}] bloque no encontrado o ambiguo (matches={n}) en {rel}")
    src = src.replace(old_crlf, new_crlf)
    with io.open(ruta, "w", encoding="utf-8", newline="") as f:
        f.write(src)
    print(f"[{tag}] OK - {rel}")


# ═══════════════ Fix 1 — pedidos.py: import update ═══════════════
aplicar(
    r"app\api\v1\pedidos.py", "pedidos import update",
    '''from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional''',
    '''from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import update
from sqlalchemy.orm import Session
from typing import List, Optional''',
)

# ═══════════════ Fix 1 — pedidos.py: descuento atómico ═══════════════
aplicar(
    r"app\api\v1\pedidos.py", "pedidos stock atomico",
    '''    # Descontar stock
    producto.stock -= pedido_data.cantidad

    db.add(db_pedido)
    db.commit()
    db.refresh(db_pedido)''',
    '''    # Descontar stock ATÓMICAMENTE (FIX concurrencia / test de esfuerzo):
    # UPDATE condicional — solo descuenta si hay stock suficiente. Si dos
    # compras concurrentes piden el último ítem, solo una obtiene rowcount=1
    # (la otra ve rowcount=0 → 400), evitando stock negativo.
    result = db.execute(
        update(Producto)
        .where(Producto.id == producto.id)
        .where(Producto.tenant_id == pedido_data.tenant_id)
        .where(Producto.stock >= pedido_data.cantidad)
        .values(stock=Producto.stock - pedido_data.cantidad)
    )
    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Stock insuficiente. Disponible: {producto.stock}, Solicitado: {pedido_data.cantidad}"
        )

    db.add(db_pedido)
    db.commit()
    db.refresh(db_pedido)''',
)

# ═══════════════ Fix 2 — solicitudes_planes.py: aprobar solo si pending ═══════════════
aplicar(
    r"app\api\v1\solicitudes_planes.py", "aprobar solo pending",
    '''    solicitud = db.query(SolicitudPlan).filter(
        SolicitudPlan.id == solicitud_id,
        SolicitudPlan.tenant_id == current_user["tenant_id"],
    ).first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    solicitud.estado = "approved"''',
    '''    solicitud = db.query(SolicitudPlan).filter(
        SolicitudPlan.id == solicitud_id,
        SolicitudPlan.tenant_id == current_user["tenant_id"],
    ).first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    # ── FIX doble-procesamiento (test de esfuerzo): una solicitud solo puede
    # aprobarse/rechazarse UNA vez. Sin este check, dos admins aprobando en
    # paralelo la misma solicitud creaban suscripciones/transacciones duplicadas.
    if solicitud.estado != "pending":
        raise HTTPException(
            status_code=400,
            detail="La solicitud ya fue procesada (aprobada o rechazada)",
        )

    solicitud.estado = "approved"''',
)

# ═══════════════ Fix 2 — solicitudes_planes.py: rechazar solo si pending ═══════════════
aplicar(
    r"app\api\v1\solicitudes_planes.py", "rechazar solo pending",
    '''    solicitud = db.query(SolicitudPlan).filter(
        SolicitudPlan.id == solicitud_id,
        SolicitudPlan.tenant_id == current_user["tenant_id"],
    ).first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    solicitud.estado = "rejected"''',
    '''    solicitud = db.query(SolicitudPlan).filter(
        SolicitudPlan.id == solicitud_id,
        SolicitudPlan.tenant_id == current_user["tenant_id"],
    ).first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    # ── FIX doble-procesamiento (test de esfuerzo): igual que aprobar.
    if solicitud.estado != "pending":
        raise HTTPException(
            status_code=400,
            detail="La solicitud ya fue procesada (aprobada o rechazada)",
        )

    solicitud.estado = "rejected"''',
)

print("\nOK: fixes de Bazar (stock atómico) y doble-aprobación aplicados.")
