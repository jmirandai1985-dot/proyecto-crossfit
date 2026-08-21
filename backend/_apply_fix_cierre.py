"""Aplica los fixes de cierre (Iteración 2 del cierre del test de esfuerzo).

FIX 1 — wrapper de errores de BD (deadlock/timeout → 503 "Alta demanda"):
  - pedidos.py: UPDATE de stock + INSERT + commit.
  - reservas.py: UPDATE condicional de cupo.
  - historial_rm.py: INSERT de RM (commit inicial).
FIX 2 — enviar_email_solicitud_admin filtra por tenant del alumno (antes
  enviaba al primer admin GLOBAL de la BD).
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


# ═══════════ FIX 1 — pedidos.py (import + wrapper) ═══════════
aplicar(
    r"app\api\v1\pedidos.py", "pedidos import DBAPIError",
    '''from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import update
from sqlalchemy.orm import Session''',
    '''from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session''',
)
aplicar(
    r"app\api\v1\pedidos.py", "pedidos wrapper 503",
    '''    result = db.execute(
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
    '''    # ── FIX cierre (test de esfuerzo): wrapper de errores de BD ──
    # Bajo contención extrema el UPDATE condicional puede fallar con deadlock
    # o timeout (visto como 500 transitorio en el Escenario D). Se captura y
    # devuelve 503 "Alta demanda" en vez de un 500 genérico.
    try:
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
        db.refresh(db_pedido)
    except DBAPIError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Alta demanda, intentá de nuevo",
        )''',
)

# ═══════════ FIX 1 — reservas.py (import + wrapper cupo) ═══════════
aplicar(
    r"app\api\v1\reservas.py", "reservas import DBAPIError",
    '''from typing import List, Optional
from sqlalchemy import func, update
from sqlalchemy.orm import Session''',
    '''from typing import List, Optional
from sqlalchemy import func, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session''',
)
aplicar(
    r"app\api\v1\reservas.py", "reservas wrapper 503",
    '''    result = db.execute(
        update(Clase)
        .where(Clase.id == clase.id)
        .where(Clase.asistentes_confirmados < Clase.cupo_maximo)
        .values(asistentes_confirmados=Clase.asistentes_confirmados + 1)
    )

    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Clase sin cupos disponibles"
        )''',
    '''    # ── FIX cierre (test de esfuerzo): wrapper de errores de BD ──
    # Bajo contención extrema el UPDATE condicional puede fallar con deadlock
    # o timeout; se devuelve 503 "Alta demanda" en vez de un 500 genérico.
    try:
        result = db.execute(
            update(Clase)
            .where(Clase.id == clase.id)
            .where(Clase.asistentes_confirmados < Clase.cupo_maximo)
            .values(asistentes_confirmados=Clase.asistentes_confirmados + 1)
        )
    except DBAPIError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Alta demanda, intentá de nuevo",
        )

    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Clase sin cupos disponibles"
        )''',
)

# ═══════════ FIX 1 — historial_rm.py (import + wrapper INSERT) ═══════════
aplicar(
    r"app\api\v1\historial_rm.py", "historial import DBAPIError",
    '''from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional''',
    '''from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import DBAPIError
from typing import List, Optional''',
)
aplicar(
    r"app\api\v1\historial_rm.py", "historial wrapper 503",
    '''    db.add(db_historial)
    db.commit()
    db.refresh(db_historial)

    # --- CALCULO AUTOMATICO DE NIVEL ---''',
    '''    # ── FIX cierre (test de esfuerzo): wrapper de errores de BD ──
    # Bajo concurrencia (Escenario F2) el INSERT/commit puede fallar con
    # deadlock o timeout; se devuelve 503 "Alta demanda" en vez de 500.
    try:
        db.add(db_historial)
        db.commit()
        db.refresh(db_historial)
    except DBAPIError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Alta demanda, intentá de nuevo",
        )

    # --- CALCULO AUTOMATICO DE NIVEL ---''',
)

# ═══════════ FIX 2 — email_service.py (filtro tenant) ═══════════
aplicar(
    r"app\services\email_service.py", "email filtro tenant",
    '''def enviar_email_solicitud_admin(alumno: dict) -> bool:
    """Notifica al admin que un alumno nuevo está pendiente de activación."""
    nombre = alumno.get("nombre", "Alumno nuevo")
    correo_alumno = alumno.get("correo", "")
    correo_admin = None
    try:
        from app.db.database import SessionLocal
        from app.models.usuario import Usuario, RolUsuario
        db = SessionLocal()
        admin = db.query(Usuario).filter(
            Usuario.rol == RolUsuario.administrador, Usuario.activo == True
        ).order_by(Usuario.id).first()
        correo_admin = admin.correo if admin else None
        db.close()''',
    '''def enviar_email_solicitud_admin(alumno: dict, tenant_id: int) -> bool:
    """Notifica al admin del MISMO tenant que un alumno nuevo está pendiente
    de activación.

    FIX cierre (test de esfuerzo): antes buscaba el primer admin GLOBAL de la
    BD (sin filtro de tenant) y un alumno de un box podía generar un correo al
    admin de otro box. Ahora filtra por tenant_id del alumno registrado.
    """
    nombre = alumno.get("nombre", "Alumno nuevo")
    correo_alumno = alumno.get("correo", "")
    correo_admin = None
    try:
        from app.db.database import SessionLocal
        from app.models.usuario import Usuario, RolUsuario
        db = SessionLocal()
        admin = db.query(Usuario).filter(
            Usuario.tenant_id == tenant_id,
            Usuario.rol == RolUsuario.administrador,
            Usuario.activo == True,
        ).order_by(Usuario.id).first()
        correo_admin = admin.correo if admin else None
        db.close()''',
)

# ═══════════ FIX 2 — alumnos.py (caller pasa tenant_id) ═══════════
aplicar(
    r"app\api\v1\alumnos.py", "alumnos caller tenant",
    '''        enviar_email_solicitud_admin({
            "nombre": usuario.nombre,
            "correo": usuario.correo,
            "id": usuario.id,
        })''',
    '''        enviar_email_solicitud_admin({
            "nombre": usuario.nombre,
            "correo": usuario.correo,
            "id": usuario.id,
        }, tenant_id=datos.tenant_id)''',
)

print("\nOK: fixes de cierre (FIX 1 wrapper 503 + FIX 2 email tenant) aplicados.")
