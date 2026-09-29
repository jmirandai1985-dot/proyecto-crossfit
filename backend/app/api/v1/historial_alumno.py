"""Router del Historial del alumno: las 6 secciones del panel, para el box y para el alumno.

Dos entradas y UN solo servicio (`historial_alumno_service.panel`), que es donde viven las
reglas y los números del panel:

  * `GET /alumnos/me/historial`           → el PROPIO alumno (rol `alumno`), sin la gestión del
                                            box (arquetipo/riesgo).
  * `GET /alumnos/{alumno_id}/historial`  → admin del box sobre cualquier alumno; si el que
                                            consulta es el propio alumno, tampoco ve la gestión.

⚠️ ORDEN DE LAS RUTAS: `me` se registra ANTES de `{alumno_id}`. Al revés, FastAPI intentaría
parsear "me" como `int` y `/alumnos/me/historial` daría 422 (el literal nunca llega a
matchear). El test lo fija.

🔒 ACL: admin/administrador o el propio alumno. El COACH recibe 403 a propósito: el panel trae
plata (total pagado, membresías, pedidos del Bazar) y el coach ya tiene su ficha acotada sin
datos financieros (`AlumnoFichaCoach.jsx`). Es un criterio MÁS estricto que el de
`historial_rm.py` (ahí el coach sí entra: un PR es dato de su clase).

FIX 1 (plan de prueba): un alumno en modo prueba no puede usar el Performance Hub / Pizarra de
RMs, así que la sección `rms` le responde 403 con el mismo mensaje que el resto de las secciones
de pago. Las otras 5 sí: son su asistencia, su plan y sus pagos.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import es_usuario_prueba, get_current_user
from app.db.database import get_db
from app.services import historial_alumno_service as svc

router = APIRouter()

# Roles que pueden mirar el historial de CUALQUIER alumno del box.
ROLES_STAFF_HISTORIAL = ("admin", "administrador")

# Secciones que un alumno en plan de prueba NO puede ver (FIX 1, mismo criterio que el router
# de `historial_rm`).
SECCIONES_BLOQUEADAS_EN_PRUEBA = ("rms",)

# Patrón de `seccion`: una sección desconocida es un error del cliente (422), no un fallback
# silencioso; el servicio, igual, normaliza por si lo llaman desde otro lado.
PATRON_SECCION = "^(" + "|".join(s for s, _ in svc.SECCIONES) + ")$"

DESCRIPCION_SECCION = (
    "resumen | asistencia | pagos | membresias | rms | beneficios "
    "(beneficios llega con la Fase 2 de Fidelización)"
)


def verificar_acceso_historial(current_user: dict, alumno_id: int) -> None:
    """ACL del historial: admin del box o el PROPIO alumno; cualquier otro rol → 403."""
    rol = current_user.get("rol", "")
    if rol in ROLES_STAFF_HISTORIAL:
        return
    if rol == "alumno" and current_user.get("usuario_id") == alumno_id:
        return
    if rol == "alumno":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para ver el historial de otro alumno",
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=("El historial del alumno es una vista de administración "
                "(incluye pagos y membresías)"),
    )


def _responder(db: Session, alumno_id: int, tenant_id: int, seccion: str,
               pagina: int, por_pagina: int, incluir_privado: bool) -> dict:
    """Panel del servicio o 404. El alumno SIEMPRE se busca dentro del tenant del token."""
    panel = svc.panel(db, alumno_id, tenant_id, seccion=seccion, pagina=pagina,
                      por_pagina=por_pagina, incluir_privado=incluir_privado)
    if panel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alumno {alumno_id} no encontrado",
        )
    return panel


def _bloquear_prueba(db: Session, current_user: dict, seccion: str) -> None:
    """FIX 1: un alumno de prueba no ve RMs (ni por la puerta del historial)."""
    if seccion not in SECCIONES_BLOQUEADAS_EN_PRUEBA:
        return
    if es_usuario_prueba(db, current_user["usuario_id"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=("Acceso limitado: tu plan de prueba solo incluye Clases, Planes y "
                    "Reservas. Elige un plan y espera la aprobación para desbloquear "
                    "esta sección."),
        )


@router.get("/me/historial")
def mi_historial(
    seccion: str = Query(svc.DEFAULT_SECCION, pattern=PATRON_SECCION,
                         description=DESCRIPCION_SECCION),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(svc.DEFAULT_POR_PAGINA, ge=1, le=svc.MAX_POR_PAGINA),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Historial del PROPIO alumno (el staff usa `/alumnos/{alumno_id}/historial`).

    `incluir_privado=False`: el arquetipo y el riesgo de churn son insumo de gestión del box,
    no información del alumno.
    """
    if current_user.get("rol") != "alumno":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta ruta es del alumno; usa /alumnos/{alumno_id}/historial",
        )
    _bloquear_prueba(db, current_user, seccion)
    return _responder(db, current_user["usuario_id"], current_user["tenant_id"], seccion,
                      pagina, por_pagina, incluir_privado=False)


@router.get("/{alumno_id}/historial")
def historial_de_alumno(
    alumno_id: int,
    seccion: str = Query(svc.DEFAULT_SECCION, pattern=PATRON_SECCION,
                         description=DESCRIPCION_SECCION),
    pagina: int = Query(1, ge=1),
    por_pagina: int = Query(svc.DEFAULT_POR_PAGINA, ge=1, le=svc.MAX_POR_PAGINA),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Historial de un alumno del box: admin/administrador, o el propio alumno (sin gestión).

    El `tenant_id` sale SIEMPRE del token: un alumno de otro box es 404, no 403.
    """
    verificar_acceso_historial(current_user, alumno_id)
    incluir_privado = current_user.get("rol") in ROLES_STAFF_HISTORIAL
    return _responder(db, alumno_id, current_user["tenant_id"], seccion,
                      pagina, por_pagina, incluir_privado=incluir_privado)
