"""Fortalecer el fix de doble-aprobación a ATOMIC.

El check `if solicitud.estado != "pending"` (leer-comprobar-escribir) NO es
seguro bajo MVCC: dos aprobaciones concurrentes pueden leer 'pending' antes
de que la otra commitee y ambas crear suscripción/transacción. Se reemplaza
por UPDATE condicional `WHERE estado='pending'` + rowcount (mismo patrón que
el cupo de clases y el stock del Bazar).
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


# import update
aplicar(
    r"app\api\v1\solicitudes_planes.py", "import update",
    '''from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session''',
    '''from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import FileResponse
from sqlalchemy import update
from sqlalchemy.orm import Session''',
)

# aprobar: UPDATE condicional atómico
aplicar(
    r"app\api\v1\solicitudes_planes.py", "aprobar atomico",
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

    solicitud.estado = "approved"
    solicitud.aprobado_por = admin_id
    solicitud.comentario_admin = "Aprobado"''',
    '''    # ── FIX doble-procesamiento (ATOMICO): una solicitud solo puede aprobarse
    # UNA vez. El UPDATE condicional con estado='pending' garantiza que de dos
    # admins aprobando en paralelo la misma solicitud, solo uno obtenga
    # rowcount=1. El check leído-comprobar previo NO era seguro bajo MVCC.
    result = db.execute(
        update(SolicitudPlan)
        .where(SolicitudPlan.id == solicitud_id)
        .where(SolicitudPlan.tenant_id == current_user["tenant_id"])
        .where(SolicitudPlan.estado == "pending")
        .values(estado="approved", aprobado_por=admin_id, comentario_admin="Aprobado")
    )
    if result.rowcount == 0:
        # Distinguir 404 (no existe / otro tenant) de 400 (ya procesada)
        solicitud = db.query(SolicitudPlan).filter(
            SolicitudPlan.id == solicitud_id,
            SolicitudPlan.tenant_id == current_user["tenant_id"],
        ).first()
        if not solicitud:
            raise HTTPException(status_code=404, detail="Solicitud no encontrada")
        raise HTTPException(
            status_code=400,
            detail="La solicitud ya fue procesada (aprobada o rechazada)",
        )
    solicitud = db.query(SolicitudPlan).filter(
        SolicitudPlan.id == solicitud_id).first()''',
)

# rechazar: UPDATE condicional atómico
aplicar(
    r"app\api\v1\solicitudes_planes.py", "rechazar atomico",
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

    solicitud.estado = "rejected"
    solicitud.aprobado_por = admin_id
    solicitud.comentario_admin = motivo
    db.commit()''',
    '''    # ── FIX doble-procesamiento (ATOMICO): igual que aprobar.
    result = db.execute(
        update(SolicitudPlan)
        .where(SolicitudPlan.id == solicitud_id)
        .where(SolicitudPlan.tenant_id == current_user["tenant_id"])
        .where(SolicitudPlan.estado == "pending")
        .values(estado="rejected", aprobado_por=admin_id, comentario_admin=motivo)
    )
    if result.rowcount == 0:
        # Distinguir 404 (no existe / otro tenant) de 400 (ya procesada)
        solicitud = db.query(SolicitudPlan).filter(
            SolicitudPlan.id == solicitud_id,
            SolicitudPlan.tenant_id == current_user["tenant_id"],
        ).first()
        if not solicitud:
            raise HTTPException(status_code=404, detail="Solicitud no encontrada")
        raise HTTPException(
            status_code=400,
            detail="La solicitud ya fue procesada (aprobada o rechazada)",
        )
    solicitud = db.query(SolicitudPlan).filter(
        SolicitudPlan.id == solicitud_id).first()
    db.commit()''',
)

print("\nOK: fix de doble-procesamiento ATOMICO aplicado.")
